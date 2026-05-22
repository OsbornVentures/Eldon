#!/usr/bin/env python3
"""
ELDON proxy — tool-dispatch layer between the client and llama-server.

llama-server runs on BACKEND_PORT (default 8081) — never talk to it directly.
This proxy runs on PORT (default 8080) — the URL you point your client at.

Every request is forwarded transparently EXCEPT /v1/chat/completions,
which runs an internal tool-dispatch loop:
  model → tool_call? → execute → feed result back → repeat → final answer → client

/v1/stats  — live inference metrics JSON (tps, kv%, slots)
logs/events.jsonl — append-only timestamped event log

Configuration (env vars):
  LLAMA_BACKEND   upstream llama-server URL  (default: http://127.0.0.1:8081)
  PROXY_PORT      port this proxy listens on  (default: 8080)
  PROXY_HOST      bind address               (default: 127.0.0.1)
"""

import importlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests as req
from flask import Flask, Response, request, stream_with_context

BACKEND        = os.environ.get("LLAMA_BACKEND", "http://127.0.0.1:8081")
PORT           = int(os.environ.get("PROXY_PORT", "8080"))
MAX_TOOL_TURNS = 20

_HERE    = Path(__file__).parent.resolve()
LOGS_DIR = _HERE / "logs"
sys.path.insert(0, str(_HERE))

logging.basicConfig(level=logging.INFO, format="[proxy] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

# ── Event log ─────────────────────────────────────────────────────────────────

def _log(kind: str, **kw):
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        ev = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **kw}
        with open(LOGS_DIR / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass

# ── Tool loader ───────────────────────────────────────────────────────────────

def _load_tools() -> dict:
    tools = {}
    for subpkg in ("core", "learned"):
        d = _HERE / "tools" / subpkg
        if not d.exists():
            continue
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_") or f.stem == "__init__":
                continue
            try:
                mod = importlib.import_module(f"tools.{subpkg}.{f.stem}")
                if callable(getattr(mod, "run", None)):
                    tools[f.stem] = mod.run
            except Exception as e:
                log.warning("tool load failed: %s — %s", f.stem, e)
    return tools

TOOLS = _load_tools()
log.info("Loaded tools: %s", sorted(TOOLS.keys()))

# ── URL linkifier (injected into llama-server web UI) ─────────────────────────

_LINK_SCRIPT = """<script>
(function(){
  var URL_RE=/(https?:\\/\\/[^\\s<>"'\\]\\[)\\}]{4,})/g;
  function linkify(el){
    if(!el)return;
    var walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);
    var nodes=[];
    while(walker.nextNode())nodes.push(walker.currentNode);
    nodes.forEach(function(node){
      var t=node.textContent;
      if(!URL_RE.test(t))return;
      URL_RE.lastIndex=0;
      var p=node.parentNode;
      if(!p||p.tagName==='A'||p.tagName==='SCRIPT'||p.tagName==='STYLE')return;
      var frag=document.createDocumentFragment(),last=0,m;
      while((m=URL_RE.exec(t))!==null){
        if(m.index>last)frag.appendChild(document.createTextNode(t.slice(last,m.index)));
        var a=document.createElement('a');
        a.href=m[1];a.target='_blank';a.rel='noopener noreferrer';
        a.textContent=m[1];
        a.style.cssText='color:#58a6ff;text-decoration:underline;word-break:break-all;';
        frag.appendChild(a);
        last=m.index+m[1].length;
      }
      if(last<t.length)frag.appendChild(document.createTextNode(t.slice(last)));
      p.replaceChild(frag,node);
    });
  }
  var obs=new MutationObserver(function(muts){
    muts.forEach(function(m){m.addedNodes.forEach(function(n){
      if(n.nodeType===1)linkify(n);
      else if(n.nodeType===3&&n.parentNode)linkify(n.parentNode);
    });});
  });
  function start(){obs.observe(document.body,{childList:true,subtree:true});linkify(document.body);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);
  else start();
})();
</script>"""

# ── OpenAI tool definitions ───────────────────────────────────────────────────

_TOOL_META = {
    "web_search":    ("Search the web. Returns titles, URLs, snippets, typed results. "
                      "type=deep fetches page content from top results (uses 32k context budget). "
                      "Google CSE used automatically when GOOGLE_CSE_KEY+GOOGLE_CSE_CX are set.",
                      {"query": ("string", "Search query"),
                       "type":  ("string", "Result type: web, news, images, videos, deep (default: web)")}),
    "web_fetch":     ("Fetch a URL and return stripped text (8KB cap).",
                      {"url": ("string", "URL to fetch")}),
    "http_call":     ("GET or POST an HTTP/HTTPS API endpoint.",
                      {"url":     ("string", "URL"),
                       "method":  ("string", "GET or POST"),
                       "body":    ("string", "JSON body for POST"),
                       "headers": ("string", "JSON headers")}),
    "fs_read":       ("Read a file. Optional 1-indexed start/end lines.",
                      {"path":  ("string",  "File path"),
                       "start": ("integer", "Start line"),
                       "end":   ("integer", "End line")}),
    "fs_write":      ("Write or append to a file.",
                      {"path":    ("string", "File path"),
                       "content": ("string", "Content"),
                       "mode":    ("string", "replace or append")}),
    "fs_list":       ("List a directory.",
                      {"path": ("string", "Directory path")}),
    "grep":          ("Search for a pattern in files using ripgrep.",
                      {"pattern": ("string", "Regex pattern"),
                       "path":    ("string", "Path to search")}),
    "shell":         ("Run one allowlisted shell command.",
                      {"cmd": ("string", "Command to run")}),
    "code_run":      ("Execute a Python snippet, return stdout/stderr.",
                      {"code":    ("string",  "Python code"),
                       "timeout": ("integer", "Timeout seconds (max 30)")}),
    "skill_make":    ("Write a new skill to tools/learned/. Code must define run(args)->dict.",
                      {"name":        ("string", "Skill name"),
                       "code":        ("string", "Python source"),
                       "description": ("string", "One-line description")}),
    "loop_open":     ("Open a tracked task loop, returns loop_id.",
                      {"task": ("string", "Task description")}),
    "loop_update":   ("Append a step to an open loop.",
                      {"loop_id": ("string", "Loop ID"),
                       "step":    ("string", "Step description")}),
    "loop_close":    ("Close a loop with an outcome summary.",
                      {"loop_id": ("string", "Loop ID"),
                       "outcome": ("string", "Outcome summary")}),
    "topo":          ("Return system topology snapshot.",
                      {"force": ("boolean", "Force refresh")}),
    "memory_store":  ("Store text/fact for semantic recall.",
                      {"content":  ("string", "Text to store"),
                       "category": ("string", "Category tag")}),
    "memory_recall": ("Semantic search of stored memories.",
                      {"query":    ("string",  "Search query"),
                       "n_results":("integer", "Results to return (default 3)")}),
    "memory_list":   ("List all stored memories.",
                      {"limit": ("integer", "Max entries (default 50)")}),
    "done":          ("Signal task complete.", {}),
    "browser_open":  ("Open a Playwright browser session. Returns session_id.",
                      {"url":        ("string",  "URL to open"),
                       "human_pace": ("integer", "Delay multiplier ms (0=fast, 1200=human speed)")}),
    "browser_nav":   ("Navigate an existing browser session to a new URL.",
                      {"session_id": ("string", "Session ID from browser_open"),
                       "url":        ("string", "URL to navigate to")}),
    "browser_dom":   ("Extract the semantic DOM: interactive elements, visible text, forms, alerts. "
                      "Returns vl_needed=true if page needs screenshot instead.",
                      {"session_id": ("string", "Session ID from browser_open")}),
    "browser_act":   ("Perform an action on a browser element. "
                      "Actions: click, type, select, scroll, wait, key, hover, clear.",
                      {"session_id": ("string", "Session ID from browser_open"),
                       "action":     ("string", "Action: click | type | select | scroll | wait | key | hover | clear"),
                       "target":     ("string", "Element ID from browser_dom, or CSS selector"),
                       "text":       ("string", "Text for type/select actions"),
                       "value":      ("string", "Scroll direction: up|down|top|bottom, or key name")}),
    "browser_close": ("Close a browser session and clean up.",
                      {"session_id": ("string", "Session ID from browser_open")}),
    "browser_shot":  ("Take a screenshot of the current browser page. Use only when browser_dom returns vl_needed=true.",
                      {"session_id": ("string", "Session ID from browser_open")}),
    "task_schedule": ("Create or update a scheduled cron task.",
                      {"name":      ("string",  "Task name"),
                       "prompt":    ("string",  "Task prompt to run"),
                       "cron":      ("string",  "Cron expression e.g. '0 9 * * 1-5'"),
                       "enabled":   ("boolean", "Whether to enable the task"),
                       "max_turns": ("integer", "Max turns per run"),
                       "wiggum":    ("boolean", "Use wiggum orchestrator")}),
    "task_list":     ("List all scheduled tasks.",
                      {"enabled_only": ("boolean", "Only show enabled tasks")}),
    "doc_parse":     ("Parse a PDF or DOCX into chunks. Returns doc_id for subsequent doc_chunk calls.",
                      {"path": ("string", "File path to document")}),
    "doc_chunk":     ("Retrieve one chunk from a parsed document.",
                      {"doc_id":   ("string",  "Doc ID from doc_parse"),
                       "chunk_id": ("integer", "Chunk index (0-based)")}),
    "weather":       ("Get current weather and 3-day forecast.",
                      {"location": ("string", "City name, e.g. 'Austin, TX'")}),
    "price_lookup":  ("Search eBay for price data on sold/active listings.",
                      {"query": ("string", "Item to search"),
                       "mode":  ("string", "sold (default) or active")}),
    "upc_lookup":    ("Look up a product by UPC/EAN barcode.",
                      {"upc": ("string", "Barcode digits")}),
    "lint_code":     ("Lint Python (ruff/flake8) or JavaScript (eslint).",
                      {"code": ("string", "Source code to lint"),
                       "path": ("string", "File path to lint instead of inline code"),
                       "lang": ("string", "python or javascript")}),
    "site_scaffold": ("Generate a starter website (index.html, style.css, app.js).",
                      {"name":     ("string", "Project name"),
                       "path":     ("string", "Output directory"),
                       "template": ("string", "basic, bootstrap, or tailwind")}),
    "ctx_compress":  ("Compress STATE.md + OPEN_LOOPS to fit a token budget. Used by wiggum loop.",
                      {"budget_tokens":  ("integer", "Target token budget for compressed output"),
                       "include_loops":  ("boolean", "Include OPEN_LOOPS.md in compression (default true)")}),
    "ebay_list":     ("Create or draft an eBay listing. Uses eBay Sell API if EBAY_APP_ID is set; falls back to Playwright browser automation otherwise.",
                      {"title":       ("string",  "Listing title"),
                       "price":       ("string",  "Buy-it-now price as a float"),
                       "description": ("string",  "Item description"),
                       "condition":   ("string",  "Condition: New | Used | Refurbished (default: Used)"),
                       "category":    ("string",  "eBay category name or number hint"),
                       "quantity":    ("integer", "Quantity available (default: 1)"),
                       "draft":       ("boolean", "Save as draft rather than publish (default: true)"),
                       "session_id":  ("string",  "Existing browser session ID to reuse")}),
    "goal_check":    ("Mark a wiggum job done/stuck/skip in CHECKLIST.md.",
                      {"job_id":  ("string", "Job ID to update (e.g. JOB-001)"),
                       "status":  ("string", "New status: done | stuck | skip | pending | active"),
                       "result":  ("string", "Optional result summary")}),
    "goal_plan":     ("Decompose a goal into wiggum job manifest. Writes CHECKLIST.md.",
                      {"goal":         ("string",  "Goal to decompose into jobs"),
                       "max_jobs":     ("integer", "Maximum number of jobs (default 10)"),
                       "token_budget": ("integer", "Token budget per job (default 2048)")}),
    "roadmap_chunk": ("Parse a large spec/roadmap by headers into a job manifest for wiggum.",
                      {"path":               ("string",  "Path to markdown spec/roadmap file"),
                       "chunk_size_tokens":  ("integer", "Max tokens per job chunk (default 1500)")}),
    "skill_validate":("Validate a learned skill: AST safety check + smoke run with test args.",
                      {"name":       ("string", "Skill name to validate"),
                       "smoke_args": ("string", "JSON args to pass to run() for smoke test (default '{}')")}),
}

_TOOL_REQUIRED = {
    "lint_code":      ["code"],
    "site_scaffold":  ["name"],
    "price_lookup":   ["query"],
    "browser_open":   ["url"],
    "browser_nav":    ["session_id", "url"],
    "browser_dom":    ["session_id"],
    "browser_act":    ["session_id", "action", "target"],
    "browser_close":  ["session_id"],
    "browser_shot":   ["session_id"],
    "task_schedule":  ["name", "prompt", "cron"],
    "doc_parse":      ["path"],
    "doc_chunk":      ["doc_id", "chunk_id"],
    "ebay_list":      ["title", "price", "description"],
    "goal_check":     ["job_id", "status"],
    "goal_plan":      ["goal"],
    "roadmap_chunk":  ["path"],
    "skill_validate": ["name"],
}

_AUTO_OPTIONAL = {"start", "end", "mode", "force", "body", "headers",
                  "description", "type", "path", "lang", "template"}

TOOL_DEFS = []
for name, fn in TOOLS.items():
    meta = _TOOL_META.get(name, (f"{name} tool", {}))
    desc, params = meta
    props = {k: {"type": t, "description": d} for k, (t, d) in params.items()}
    if name in _TOOL_REQUIRED:
        required = _TOOL_REQUIRED[name]
    else:
        required = [k for k, (t, _) in params.items()
                    if t == "string" and k not in _AUTO_OPTIONAL]
    TOOL_DEFS.append({
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    })


def _dispatch(name: str, args: dict) -> dict:
    fn = TOOLS.get(name)
    if not fn:
        return {"error": f"unknown tool: {name}"}
    try:
        result = fn(args)
        preview = str(result)[:80]
        log.info("%s -> %s", name, preview)
        _log("tool_call", tool=name,
             args={k: str(v)[:80] for k, v in args.items()},
             result=preview)
        return result
    except Exception as e:
        err = str(e)[:200]
        _log("tool_error", tool=name, error=err)
        return {"error": err}


def _make_chunk(text: str) -> str:
    chunk = {
        "id": f"chatcmpl-proxy-{int(time.time())}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "eldon-agent",
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }
    return f"data: {json.dumps(chunk)}\n\n"


def _make_tool_chunk(index: int, tool_id: str, tool_name: str, tool_args: str) -> str:
    chunk = {
        "id": f"chatcmpl-proxy-{int(time.time())}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "eldon-agent",
        "choices": [{
            "index": 0,
            "delta": {
                "tool_calls": [{
                    "index": index,
                    "id": tool_id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": tool_args},
                }]
            },
            "finish_reason": None,
        }],
    }
    return f"data: {json.dumps(chunk)}\n\n"


# ── /v1/stats ─────────────────────────────────────────────────────────────────

def _parse_prom(raw: str) -> dict:
    out = {}
    for line in raw.splitlines():
        if line.startswith("#"):
            continue
        m = re.match(r"llamacpp:(\w+)\s+([\d.eE+\-]+)", line)
        if m:
            try:
                out[m.group(1)] = float(m.group(2))
            except ValueError:
                pass
    return out

@app.route("/v1/stats")
def stats():
    result = {}
    try:
        m = _parse_prom(req.get(f"{BACKEND}/metrics", timeout=2).text)
        result.update({
            "tps_gen":         round(m.get("predicted_tokens_per_second", 0), 1),
            "tps_prompt":      round(m.get("prompt_tokens_per_second", 0), 1),
            "n_generated":     int(m.get("n_tokens_predicted_total", 0)),
            "n_prompt":        int(m.get("n_prompt_tokens_processed_total", 0)),
            "requests_active": int(m.get("requests_processing", 0)),
            "requests_queued": int(m.get("requests_pending", 0)),
            "kv_ratio":        round(m.get("kv_cache_usage_ratio", 0), 3),
        })
    except Exception as e:
        result["metrics_error"] = str(e)[:80]
    try:
        slots_raw = req.get(f"{BACKEND}/slots", timeout=2).json()
        result["slots"] = [
            {
                "id":     sl.get("id"),
                "n_past": int(sl.get("n_past", 0)),
                "ctx":    int(sl.get("n_ctx", 1)),
                "pct":    round(int(sl.get("n_past", 0)) / max(int(sl.get("n_ctx", 1)), 1) * 100, 1),
                "state":  {0: "idle", 1: "gen", 2: "wait"}.get(int(sl.get("state", 0)), "?"),
            }
            for sl in slots_raw
        ]
    except Exception as e:
        result["slots_error"] = str(e)[:80]
    return Response(json.dumps(result), mimetype="application/json",
                    headers={"Access-Control-Allow-Origin": "*"})


# ── Chat completions with tool loop ───────────────────────────────────────────

@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    body = request.get_json(force=True)
    messages = list(body.get("messages", []))
    orig_stream = body.get("stream", False)
    max_turns = int(body.pop("max_tool_turns", MAX_TOOL_TURNS))

    if "tools" not in body:
        body["tools"] = TOOL_DEFS

    _log("chat_start", n_messages=len(messages))

    if orig_stream:
        def generate_stream():
            for turn in range(max_turns):
                body["stream"] = False
                body["messages"] = messages
                try:
                    resp = req.post(f"{BACKEND}/v1/chat/completions", json=body, timeout=300)
                    resp.raise_for_status()
                except Exception as e:
                    yield _make_chunk(f"\n[Proxy Error: {e}]\n")
                    return

                data   = resp.json()
                choice = data["choices"][0]
                msg    = choice["message"]
                finish = choice.get("finish_reason", "")

                if finish == "tool_calls" and msg.get("tool_calls"):
                    messages.append(msg)
                    for idx, tc in enumerate(msg["tool_calls"]):
                        fn_name  = tc["function"]["name"]
                        raw_args = tc["function"]["arguments"]
                        tool_args_str = (raw_args if isinstance(raw_args, str)
                                         else json.dumps(raw_args, ensure_ascii=False))
                        yield _make_tool_chunk(idx, tc.get("id", f"call_{fn_name}_{idx}"),
                                               fn_name, tool_args_str)
                        try:
                            args = (json.loads(raw_args)
                                    if isinstance(raw_args, str) else raw_args)
                        except Exception:
                            args = {}
                        result = _dispatch(fn_name, args)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", "0"),
                            "content": json.dumps(result, ensure_ascii=False),
                        })
                    log.info("turn %d: executed %d tool call(s)", turn, len(msg["tool_calls"]))
                else:
                    _log("chat_end", turns=turn,
                         tps=round(data.get("timings", {}).get("predicted_per_second", 0), 1),
                         tokens=data.get("usage", {}).get("completion_tokens", 0))
                    body["stream"] = True
                    body["messages"] = messages
                    try:
                        up = req.post(f"{BACKEND}/v1/chat/completions",
                                      json=body, stream=True, timeout=300)
                        for line in up.iter_lines():
                            if line:
                                yield line.decode("utf-8", errors="replace") + "\n\n"
                    except Exception as e:
                        yield _make_chunk(f"\n[Stream Error: {e}]\n")
                    return

            yield _make_chunk("\n[max tool turns exceeded]\n")

        return Response(
            stream_with_context(generate_stream()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    else:
        body["stream"] = False
        for turn in range(max_turns):
            body["messages"] = messages
            try:
                resp = req.post(f"{BACKEND}/v1/chat/completions", json=body, timeout=300)
                resp.raise_for_status()
            except Exception as e:
                return Response(json.dumps({"error": str(e)}), status=502,
                                mimetype="application/json")

            data   = resp.json()
            choice = data["choices"][0]
            msg    = choice["message"]
            finish = choice.get("finish_reason", "")

            if finish == "tool_calls" and msg.get("tool_calls"):
                messages.append(msg)
                for tc in msg["tool_calls"]:
                    fn = tc["function"]
                    try:
                        args = (json.loads(fn["arguments"])
                                if isinstance(fn["arguments"], str)
                                else fn["arguments"])
                    except Exception:
                        args = {}
                    result = _dispatch(fn["name"], args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", "0"),
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                log.info("turn %d: executed %d tool call(s)", turn, len(msg["tool_calls"]))
            else:
                _log("chat_end", turns=turn,
                     tps=round(data.get("timings", {}).get("predicted_per_second", 0), 1),
                     tokens=data.get("usage", {}).get("completion_tokens", 0))
                return Response(resp.content, status=200, mimetype="application/json")

        return Response(json.dumps({"error": "max tool turns exceeded"}), status=500,
                        mimetype="application/json")


# ── Transparent proxy for everything else ─────────────────────────────────────

@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"])
@app.route("/<path:path>",             methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"])
def proxy_all(path):
    url = f"{BACKEND}/{path}"
    qs  = request.query_string.decode()
    if qs:
        url += f"?{qs}"

    skip_headers = {"host", "content-length", "transfer-encoding", "connection"}
    fwd_headers  = {k: v for k, v in request.headers if k.lower() not in skip_headers}

    try:
        upstream = req.request(
            method=request.method,
            url=url,
            headers=fwd_headers,
            data=request.get_data(),
            stream=True,
            timeout=300,
        )
    except Exception as e:
        return Response(f"proxy error: {e}", status=502)

    drop = {"content-encoding", "content-length", "transfer-encoding", "connection"}
    out_headers = [(k, v) for k, v in upstream.headers.items() if k.lower() not in drop]

    if (path in ("", "index.html") and request.method == "GET"
            and "text/html" in upstream.headers.get("content-type", "")):
        html = upstream.text
        html = html.replace("</head>", _LINK_SCRIPT + "</head>", 1)
        safe_headers = [(k, v) for k, v in upstream.headers.items()
                        if k.lower() not in drop | {"content-length"}]
        return Response(html, status=upstream.status_code, headers=safe_headers)

    def _passthrough():
        for chunk in upstream.iter_content(chunk_size=4096):
            yield chunk

    return Response(
        stream_with_context(_passthrough()),
        status=upstream.status_code,
        headers=out_headers,
    )


if __name__ == "__main__":
    PROXY_HOST = os.environ.get("PROXY_HOST", "127.0.0.1")
    log.info("ELDON proxy -> http://%s:%d", PROXY_HOST, PORT)
    log.info("backend     -> %s", BACKEND)
    app.run(host=PROXY_HOST, port=PORT, threaded=True, use_reloader=False)
