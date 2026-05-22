# ELDON
**Edge Local Deterministic Orchestration Node**

A local agent runtime built for the Gemma 4 model family. Runs entirely on your hardware. No cloud dependency, no framework layer, no vendor-controlled behavioral layer. A model, a deterministic orchestration substrate, and your machine.

---

## Security — read this first

`code_run` executes arbitrary Python. `skill_make` writes Python files to `tools/learned/` that get imported on the next tool call. Neither is sandboxed. If adversarial content reaches the model through a web fetch, document parse, or crafted prompt — and the model acts on it — it runs as your user account.

**This is by design, not an oversight.**

The mitigation strategy is structural, not behavioral:

- `shell` runs only against an explicit allowlist (`runtime/allowlist.txt`) with a blocklist regex layer (`runtime/blacklist.txt`)
- `fs_read` / `fs_write` / `fs_list` are scoped to declared root paths (`runtime/fs_roots.txt`)
- Gemma 4's base alignment provides a reasonable behavioral floor — no abliteration required for general agentic tasks
- You are the watchdog. This is not designed to run unattended on untrusted input.

**Do not expose the proxy to the internet. Do not feed it untrusted documents without understanding what `code_run` can do.**

If you need sandboxing, add it. The tool functions in `tools/core/` are plain Python — wrap `code_run` in a restricted subprocess if your use case requires it.

---

## What this is

A Flask proxy and a Python tool execution substrate that turns a local Gemma 4 instance into a multi-step agent.

The proxy intercepts chat completion requests, runs an internal tool dispatch loop — model calls tool, proxy executes it, result feeds back to model — and returns the final answer to the client. The client sees normal chat completions. It has no visibility into the tool calls happening inside the proxy.

`loop.py` provides a separate direct agentic loop using llama-server's `/completion` endpoint with a GBNF grammar that constrains output to valid tool calls at the token sampling level. No JSON schema validation after the fact — the grammar is compiled into llama-server and operates on logits directly.

On top of that: a meta-orchestrator (`wiggum.py`) that decomposes goals into sequential jobs, a cron-based scheduler (`scheduler.py`), Playwright browser automation, ChromaDB semantic memory, and `skill_make` — a mechanism that lets the model write and load new tools without restarting.

39 tools. Each one is a plain Python file with a `run(args: dict) -> dict` function.

---

## Why the architecture matters

This section is the point of the project. The design choices interact in ways that matter more for small models than large ones.

### Grammar constraints

`grammar.gbnf` defines a GBNF (GGML BNF) formal grammar that llama-server compiles at startup and enforces during token sampling on the direct loop path. At each sampling step during a tool call, the grammar masks the logit distribution — only tokens that could continue a valid grammar sequence are assigned non-zero probability.

The grammar enumerates all 39 tool names exactly:

```
tool-name ::= "browser_act" | "browser_close" | ... | "web_search"
```

This has a specific consequence: the model cannot hallucinate a tool name. It cannot output an invalid tool name because the token sequence for an invalid tool name is grammatically impossible — the logit for every token that would start one is zeroed before sampling. It also enforces that arguments are valid JSON and that the structure is `<tool>...</tool><args>...</args><reason>...</reason>` exactly. The model cannot produce a malformed tool call on the grammar-constrained path.

This is not prompt engineering. It is not JSON schema validation applied after generation. The grammar operates at the logit level, before any token is sampled.

For small models, this effect should be disproportionately large. A larger model has a more peaked output distribution — it's more confident about the next token and more likely to sample the correct one anyway. A small model's distribution is flatter. Without grammar constraints, a flat distribution over a large vocabulary means structural errors are more frequent. With grammar constraints, the probability mass is concentrated onto the grammatically valid set regardless of how peaked the underlying distribution is. The grammar acts as a structural correctness floor; we expect this to benefit weaker models disproportionately.

The grammar is regenerated automatically by `_meta.py` on every `loop.py` startup from the current tool set. If you add a tool, the grammar updates. No manual maintenance.

### Token-budget engineering and prefix caching

llama-server implements KV cache prefix reuse. When a prompt begins with an identical token sequence to a previous request, llama-server reuses the cached key-value activations for those tokens rather than recomputing them. This is fast and reduces memory bandwidth pressure.

The context `loop.py` sends to the model each turn is:

```
TOPO        — hardware snapshot (invariant within session)
IDENTITY    — agent identity (invariant)
TOOLS       — tool list and signatures (invariant unless skill_make fires)
STATE       — what has happened (grows and trims)
OPEN_LOOPS  — any tracked loops
TASK        — current task (invariant within a job)
```

The first three sections are invariant across turns. If they stay compact, llama-server reuses their KV activations on every subsequent turn in the session — they are computed once. `STATE.md` is the variable part. It grows as tool calls complete, and is trimmed via FIFO at 100 lines, with overflow archived to `logs/state.archive`. The variable section is bounded.

Keeping the invariant prefix compact also matters for attention. In a transformer, every token in context attends to every earlier token. A larger orchestration header means more tokens outside the task-relevant portion of context, which reduces the effective budget for STATE (the record of what happened) and the TASK itself. Shorter invariant prefix = more of the context window available for the task state that actually changes behavior.

### Locality and colocated execution

In ELDON, inference and orchestration run on the same machine in the same process. A tool call is a Python function call. There is no network boundary between the model deciding to call a tool and the tool executing.

In cloud agent architectures, inference is remote, tools are remote, and every tool call involves HTTP round trips in both directions. Each round trip adds latency (typically 10–200ms) and introduces a failure surface: network errors, serialization bugs, timeout handling, retries. Over 10–20 tool calls in a single agent run, this accumulates.

ELDON's local-only tool calls (filesystem, code execution, memory) execute in milliseconds; network-bound tools (web_fetch, browser, http_call) incur their own latency but aren't routed through a remote orchestrator. The STATE.md record of each result is available to the next turn immediately. The feedback loop is tight.

This matters for small models specifically because tight feedback loops let you run more turns before context degrades. If you're getting 10–15 t/s generation and tool calls complete in under a second, you can complete 15–20 tool steps in a session in a few minutes. At cloud latencies, the same session takes longer and the accumulated latency pushes you toward fewer, larger tool calls — which conflicts with how small models perform best (short, focused steps with immediate feedback).

### External working memory and goal re-anchoring

Small models have limited ability to maintain multi-step task context across many tool calls. As STATE.md grows, the model's attention must reach further back to retrieve earlier context, and in practice, small models drift — they lose the thread of what they were originally doing.

Wiggum's `[WIGGUM-CONTEXT]` prefix, injected at every single turn, reads:

```
[WIGGUM-CONTEXT]
GOAL:  research competitors and write a summary report
JOB:   job-01 — search for main competitors
STEP:  3/20
DONE:  0/4
LAST:  [last 120 chars of compressed context]
[/WIGGUM-CONTEXT]
```

The goal is not stored in the model's attention over prior turns. It is re-stated explicitly on every turn. The model cannot forget it because it is always present in the current context window.

This is external working memory. Instead of relying on the model's latent attention to hold task state across turns, the orchestration layer makes the task state explicit at every step. This is how Wiggum compensates for limited multi-turn context retention in small models: the model's inability to maintain long-range context is compensated structurally, not by hoping the model is smart enough to remember.

### Five effects interacting simultaneously

These properties compound. For a small model running an agentic loop:

1. **Stable prefix caching** — compact, invariant TOPO + IDENTITY + TOOLS are computed once, reused every turn
2. **Reduced attention load** — smaller orchestration header leaves more context budget for STATE and TASK
3. **Grammar-induced structural correctness** — flat output distributions are corrected to valid tool calls at the logit level
4. **External working memory** — goal state is re-stated every turn, not trusted to latent attention
5. **Low-latency feedback** — tool results return in milliseconds, enabling more turns per session before drift

None of these effects requires a frontier model to deliver value. They are engineering properties of the orchestration layer. The model is Gemma 4 E4B — a 4B-parameter dense edge model at Q8_0 quantization, running at 10–15 t/s on 7–8 GB VRAM. At that size, every orchestration efficiency matters.

---

## The design premise

Most deployed AI systems operate across three distinct layers:

**Layer 1 — Statistical inference.** The transformer. Weights, attention, token prediction. Non-deterministic by nature.

**Layer 2 — Deterministic orchestration.** Routing, memory, tool dispatch, topology awareness, caching, schedulers. This orchestration substrate itself is deterministic given the same tool calls. It is the execution substrate the inference layer operates inside.

**Layer 3 — Economic substrate.** Token billing, product-safety boundaries, usage limits, behavioral incentives tied to the vendor's interests. In most cloud AI systems this layer is mixed invisibly into layer 2 — you cannot fully separate it, modify it independently, or remove it.

ELDON is an explicit implementation of layer 1 and 2 with layer 3 absent. The orchestration is fully inspectable — every routing decision, memory operation, topology check, and tool dispatch is readable Python. The economic substrate is replaced with technical controls you configure yourself: an allowlist, a blocklist, filesystem boundaries, and a grammar that enforces output structure at the token level.

**The unified execution property.** In ELDON, inference and orchestration run on the same machine in the same process. A tool call is a local Python function call — there is no network hop between the model deciding to act and the action executing. In cloud agent architectures, inference is remote, tools are remote, and coordination happens over HTTP. These are structurally different systems. Whether colocation produces better behavior is an open question. That it eliminates an entire category of latency, failure modes, and intermediary state is not.

The observation this was built from: when the orchestration layer is explicit and the economic substrate is absent, the system's behavior is fully determined by the task, the tools, and the model — nothing else is in the loop.

---

## How it works

### Agent mode (proxy path)

```
You type a message in the browser or send to /v1/chat/completions
    ↓
Proxy receives it (port 8080)
    ↓
Proxy asks llama-server: "what do you want to do?"
    ↓
Model replies with a tool call
    ↓
Proxy runs the tool in Python, gets results
    ↓
Results fed back to model as tool response
    ↓
Model decides: call another tool, or answer
    ↓
When model is done, proxy streams the final answer back
    ↓
Client sees: [thinking block] [tool block] [answer]
```

The tool loop runs up to 20 times per message. The client — browser UI, opencode, curl, whatever — sees a normal chat completion. It has no visibility into the tool calls. Every tool call is logged to `logs/events.jsonl`.

### Loop mode (direct path)

```
python loop.py "find all TODO comments in this codebase"
    ↓
_meta.py regenerates TOOLS.md + grammar.gbnf from current tool set
    ↓
Each turn: context = TOPO + IDENTITY + TOOLS + STATE + TASK
    ↓
Sent to llama-server /completion with grammar active
    ↓
Model outputs: <tool>grep</tool><args>{"pattern":"TODO","path":"."}</args><reason>...</reason>
    ↓
loop.py parses, dispatches, appends result to STATE.md
    ↓
Next turn: model sees what happened, decides what to do next
    ↓
Model calls done when finished
```

STATE.md is a rolling log of what happened. When it exceeds 100 lines, the oldest entries are archived to `logs/state.archive` with a summary line replacing them. The model's view of history is always bounded.

### Wiggum mode (orchestration)

```
python wiggum.py "research competitors and write a summary report"
    ↓
goal_plan decomposes goal into discrete jobs (model call)
    ↓
For each job, loop.py runs with the wiggum prefix injected:
    [WIGGUM-CONTEXT]
    GOAL:  research competitors and write a summary report
    JOB:   job-01 — search for main competitors
    STEP:  1/20
    DONE:  0/4
    [/WIGGUM-CONTEXT]
    ↓
Model cannot lose the goal — it is present in every single turn
    ↓
Progress tracked in CHECKLIST.md, results in logs/events.jsonl
    ↓
Next job starts when current job calls done
```

### Scheduler

```
runtime/scheduled_tasks.json defines tasks with cron expressions
    ↓
scheduler.py polls every 60 seconds
    ↓
Due task fires as loop.py or wiggum.run() call
    ↓
Results logged, next_run updated
```

---

## Model support

Built for the Gemma 4 family. `gemma4.jinja` implements Gemma 4's native chat format including tool call tokens (`<|tool_call>`, `<|tool_response>`, `<|channel>`). Without the correct template, llama-server falls back to a generic format and tool calling breaks.

Any Gemma 4 GGUF variant that llama-server can load should work — E4B is the target, larger variants if your hardware can hold them.

Tested on: Gemma 4 E4B Q8_0 (Bartowski).

Other model families will not work without a matching jinja template and potentially grammar adjustments. The proxy path may work with other instruction-tuned models if you swap the template. The direct loop path (grammar-constrained `/completion`) is tuned to Gemma 4's output behavior and token format.

---

## Is this different or just another agent framework

Honest answer: it depends what you're comparing it to.

**AutoGPT / BabyAGI** — cloud-dependent, brittle, mostly abandoned. ELDON runs locally, works, and doesn't require an OpenAI key.

**LangChain / LangGraph** — a toolkit for building agent pipelines. You write Python around it. ELDON is a complete runtime, not a library. There's no LangChain underneath.

**Open Interpreter** — the closest spiritual match. Local model, code execution, tool loop. But it defaults to cloud, has no grammar constraints, no scheduler, no wiggum-style orchestration, and isn't built around a specific model's token format.

**Ollama / LM Studio** — model servers. No agentic layer.

**LocalAI (the project)** — Docker-based OpenAI-compatible server. Different problem, different solution.

**What's actually different:**

1. The proxy opacity pattern. Tool execution is inside the proxy, invisible to the client. Any OpenAI-compatible client works without modification.

2. GBNF grammar on the direct loop path. Not prompt engineering. Not JSON schema validation. Token-level structural enforcement at the logit layer. The model cannot hallucinate a tool name — the grammar enumerates them exactly.

3. A working Gemma 4 jinja template for llama.cpp. When ELDON was built, llama.cpp had no built-in chat template for Gemma 4 (`LLM_CHAT_TEMPLATE_GEMMA4` does not exist in current builds) and the public templates I could find were broken — tool calls didn't round-trip, thinking blocks bled into output, system roles were mis-routed. `templates/gemma4.jinja` is the result of iterating with Wiggum smoke-tests until thinking blocks, tool call blocks, and final answers rendered as distinct elements in the llama-server web UI and `tool_calls` round-tripped through the OpenAI-format response. If you want Gemma 4 tool calling on llama.cpp today, this template is a usable starting point regardless of whether you use the rest of ELDON.

4. The five interacting effects described above. Grammar constraints, prefix caching, locality, external working memory, and tight feedback loops are not independent features — they compound, and they compound more for small models.

5. `skill_make`. The model can write new tools and load them without restarting. The runtime is self-extending.

6. Built constraint-first for real hardware. Designed around 6–8 GB effective VRAM (AMD APU, low-end discrete). Not "works on whatever you have."

7. No framework dependency. Flask, requests, chromadb, croniter. That's the stack. You can read every line.

If none of that sounds interesting to you, it's probably just another agent framework. That's fine.

---

## What works

- Multi-step tool chains: 10+ sequential domain-switching calls before meaningful context degradation
- Web search → file write → memory store → recall in one run
- Browser automation on pages with usable DOM
- Scheduled autonomous workflows
- The model writing its own tools via `skill_make` and using them in the same session
- Runs on AMD UMA (Radeon 840M, 24 GB UMA pool) at 10–15 t/s generation speed

## What doesn't

- No sandboxing on `code_run` or `skill_make`
- `web_search` opens a browser window on Windows (visual side effect, configurable via `ELDON_BROWSER_PATH`)
- Browser tools require Playwright Chromium installed separately
- `doc_parse` requires Docling (~2 GB install)
- Windows-first. Linux/macOS needs minor path adjustments in `_lib.py` and the launcher
- No parallel agent execution — jobs are sequential
- Context degrades past ~15 complex steps in a single session

---

## Stack

```
llama-server (llama.cpp)
    gemma4.jinja       — Gemma 4 native chat template
    grammar.gbnf       — output constraint (loop path only, auto-regenerated)

proxy.py (Flask)
    tool dispatch loop (up to 20 turns per message)
    /v1/stats endpoint
    SSE streaming

tools/core/            — 39 tool functions
tools/learned/         — runtime-written tools (skill_make output)

loop.py                — direct agentic loop with grammar + STATE.md
wiggum.py              — multi-job orchestrator with goal re-anchoring
scheduler.py           — cron daemon
logflow.py             — event log viewer

runtime/
    allowlist.txt           — permitted shell commands
    blacklist.txt           — blocked shell patterns (regex)
    fs_roots.txt            — permitted filesystem paths
    scheduled_tasks.json    — cron task definitions

memory_db/             — ChromaDB (created on first use)
logs/
    events.jsonl       — structured event log
    state.archive      — archived STATE.md batches
```

---

## Requirements

- Python 3.10+
- llama-server (llama.cpp, Vulkan or CUDA build)
- Gemma 4 E4B GGUF (Bartowski Q8_0 recommended)
- 6 GB+ VRAM (unified memory counts on AMD APUs)
- `pip install flask requests chromadb croniter`
- Optional: `playwright` (browser tools), `docling` (PDF/DOCX parsing)

See [SETUP.md](SETUP.md) for full instructions.

---

## Who this is for

People running local models on real hardware who want a working, inspectable tool loop without assembling it from four different frameworks. People interested in what agents look like when the orchestration layer is explicit and the economic substrate is absent. People on constrained hardware who need something that actually fits in VRAM and performs at interactive speed.

If you're looking for a polished product, look elsewhere. If you want to understand exactly what's happening at every layer and modify it freely, this codebase is straightforward to read and change.

---

MIT License — Osborn Ventures Inc.
