#!/usr/bin/env python3
"""Gemma agent loop runner — Phase 2.
Startup: regenerates TOOLS.md + grammar.gbnf from current tool set, then runs.
Tool hot-reload: after skill_make, reloads the tool registry.
State trim: FIFO with deterministic summary line for dropped batches.
"""
import importlib
import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

from tools import _lib, _meta  # noqa: E402

GRAMMAR_FILE    = ROOT / "runtime" / "grammar.gbnf"
STATE_MAX_LINES = 100


def read(path: str) -> str:
    p = ROOT / path
    return p.read_text(encoding="utf-8") if p.exists() else ""


def trim_state() -> None:
    p = ROOT / "STATE.md"
    if not p.exists():
        return
    lines = p.read_text(encoding="utf-8").splitlines()
    if len(lines) <= STATE_MAX_LINES:
        return

    overflow = lines[: len(lines) - STATE_MAX_LINES + 1]
    keep     = lines[len(overflow):]

    counts: dict[str, int] = {}
    first_ts = last_ts = ""
    for line in overflow:
        parts = line.split(" ", 2)
        if len(parts) < 2:
            continue
        ts, tool = parts[0], parts[1]
        if not first_ts:
            first_ts = ts
        last_ts = ts
        counts[tool] = counts.get(tool, 0) + 1

    archive = ROOT / "logs" / "state.archive"
    archive.parent.mkdir(parents=True, exist_ok=True)
    batch_id = len(list(archive.parent.glob("state.archive*")))
    with archive.open("a", encoding="utf-8") as f:
        f.write(f"\n=== BATCH {batch_id} {first_ts} → {last_ts} ===\n")
        f.write("\n".join(overflow) + "\n")

    count_str = " ".join(
        f"{t.lower()}={c}" for t, c in sorted(counts.items(), key=lambda kv: -kv[1])
    )
    summary = (
        f"{_lib.now()} ARCHIVE {len(overflow)}_entries "
        f"[{count_str}] → state.archive#{batch_id}"
    )
    p.write_text(summary + "\n" + "\n".join(keep) + "\n", encoding="utf-8")


def state_append(line: str) -> None:
    p = ROOT / "STATE.md"
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    p.write_text(
        existing.rstrip() + "\n" + line + "\n" if existing else line + "\n",
        encoding="utf-8",
    )
    trim_state()


def load_tools() -> dict:
    tools = {}
    for subpkg in ("core", "learned"):
        d = ROOT / "tools" / subpkg
        if not d.exists():
            continue
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_") or f.stem == "__init__":
                continue
            try:
                mod = importlib.import_module(f"tools.{subpkg}.{f.stem}")
                mod = importlib.reload(mod)
            except Exception as e:
                state_append(f"{_lib.now()} TOOL_LOAD_FAIL {f.stem} {str(e)[:60]}")
                continue
            if callable(getattr(mod, "run", None)):
                tools[f.stem] = mod.run
    return tools


def compose_context(task: str, wiggum_prefix: str = "") -> str:
    snap, _, _ = _lib.ensure_topo()
    parts = [
        "## TOPO",       snap,
        "## IDENTITY",   read("IDENTITY.md"),
        "## TOOLS",      read("TOOLS.md"),
        "## STATE",      read("STATE.md") or "(empty)",
        "## OPEN_LOOPS", read("OPEN_LOOPS.md") or "(none)",
        "## TASK",       task,
    ]
    if wiggum_prefix:
        parts = [wiggum_prefix] + parts
    parts.append("Respond with exactly one tool call in the required format.")
    return "\n\n".join(parts)


def llama_call(prompt: str, backend_url: str = "") -> str:
    url = backend_url or _lib.LLAMA_URL
    grammar = GRAMMAR_FILE.read_text(encoding="utf-8") if GRAMMAR_FILE.exists() else ""
    # Wrap in Gemma chat markers so the instruction-tuned model activates correctly.
    # Without these, the model gets raw text and falls back to done immediately.
    wrapped = (
        "<start_of_turn>user\n"
        + prompt
        + "\n<end_of_turn>\n<start_of_turn>model\n"
    )
    payload: dict = {
        "prompt":      wrapped,
        "n_predict":   1024,
        "temperature": 0.3,
        "stop":        ["</reason>", "<end_of_turn>"],
    }
    if grammar:
        payload["grammar"] = grammar
    r = requests.post(url, json=payload, timeout=180)
    r.raise_for_status()
    return r.json()["content"] + "</reason>"


def parse_response(text: str) -> dict:
    tool   = re.search(r"<tool>(.*?)</tool>",     text, re.S)
    args   = re.search(r"<args>(.*?)</args>",     text, re.S)
    reason = re.search(r"<reason>(.*?)</reason>", text, re.S)
    try:
        parsed_args = json.loads(args.group(1)) if args else {}
    except Exception:
        parsed_args = {}
    return {
        "tool":   tool.group(1).strip() if tool else None,
        "args":   parsed_args,
        "reason": reason.group(1).strip() if reason else "",
    }


def dispatch(call: dict, tools: dict) -> dict:
    fn = tools.get(call["tool"])
    if not fn:
        return {"error": f"unknown tool: {call['tool']}"}
    try:
        return fn(call["args"])
    except Exception as e:
        return {"error": str(e)[:120]}


def _detect_stuck(state_lines: list, window: int = 6) -> tuple:
    """Returns (is_stuck, reason)."""
    from collections import Counter
    recent = state_lines[-window:]

    # Primary: same tool+args 3x (requires complete JSON in state line)
    tool_arg_pairs = []
    for line in recent:
        m = re.search(r"\s+([A-Z_]+)\s+(\{[^}]*\})", line)
        if m:
            tool_arg_pairs.append((m.group(1).lower(), m.group(2)[:80]))
    for (tool, args), count in Counter(tool_arg_pairs).items():
        if count >= 3:
            return True, f"repeated {tool} with same args ({count}x)"

    # Fallback: same tool name 5x in window regardless of args
    tool_names = []
    for line in recent:
        m = re.search(r"\s+([A-Z_]{2,})\s+\{", line)
        if m:
            tool_names.append(m.group(1).lower())
    for tool, count in Counter(tool_names).items():
        if count >= 5:
            return True, f"looping on {tool} ({count}x in window={window})"

    errors = [l for l in recent if "error" in l.lower()]
    if len(errors) >= 2:
        def _err_sig(s):
            m = re.search(r"error.*", s, re.I)
            return m.group()[:40] if m else ""
        if _err_sig(errors[-1]) and _err_sig(errors[-1]) == _err_sig(errors[-2]):
            return True, f"repeated error: {_err_sig(errors[-1])[:60]}"

    # Cross-run detection: NO_TOOL may appear in archived STATE.md from a previous run.
    no_tools = sum(1 for l in recent if "NO_TOOL" in l)
    if no_tools >= 2:
        return True, "model stopped calling tools"

    return False, ""


def loop(
    task: str,
    max_turns: int = 20,
    wiggum_prefix: str = "",
    backend_url: str = "",
) -> dict:
    """Run one agent loop. Returns {turns, done, stuck, reason}."""
    n_tools = _meta.regenerate_all()
    tools   = load_tools()
    state_append(f'{_lib.now()} TASK_START "{task[:60]}" tools={n_tools}')

    final_turn = 0
    done_called = False
    stuck = False
    stuck_reason = ""

    for turn in range(max_turns):
        final_turn = turn

        # Stuck check on STATE before each turn
        state_lines = (ROOT / "STATE.md").read_text(encoding="utf-8").splitlines() \
            if (ROOT / "STATE.md").exists() else []
        is_stuck, reason = _detect_stuck(state_lines)
        if is_stuck:
            state_append(f"{_lib.now()} STUCK {reason}")
            stuck = True
            stuck_reason = reason
            break

        prompt = compose_context(task, wiggum_prefix)
        try:
            raw = llama_call(prompt, backend_url)
        except Exception as e:
            state_append(f"{_lib.now()} ERROR llama_call {str(e)[:80]}")
            break
        try:
            call = parse_response(raw)
        except Exception as e:
            state_append(f"{_lib.now()} PARSE_FAIL turn={turn} {str(e)[:60]}")
            break
        if not call["tool"]:
            state_append(f"{_lib.now()} NO_TOOL turn={turn}")
            break

        result = dispatch(call, tools)
        summary = json.dumps(result, ensure_ascii=False)[:200]
        state_append(f"{_lib.now()} {call['tool'].upper()} {summary}")

        if call["tool"] == "skill_make" and "error" not in result:
            _meta.regenerate_all()
            tools = load_tools()
            state_append(f"{_lib.now()} RELOAD tools={len(tools)}")

        if call["tool"] == "done":
            done_called = True
            break

    state_append(f"{_lib.now()} TASK_END turns={final_turn + 1}")
    return {
        "turns":  final_turn + 1,
        "done":   done_called,
        "stuck":  stuck,
        "reason": stuck_reason,
    }


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) or "Run topo, then call done."
    result = loop(task)
    print(json.dumps(result, indent=2))
