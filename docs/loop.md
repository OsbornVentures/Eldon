# The Loop

ELDON has two execution paths. Understanding the difference matters.

## Proxy path (browser / API client)

Used when a client connects to the proxy on port 8080. The loop runs inside `proxy.py` transparently. The client never sees raw tool calls — it sees tool blocks and a final answer. Context is the full conversation history managed by the client.

## Loop path (loop.py / wiggum.py / scheduler.py)

Used when running tasks autonomously — via `loop.py` directly, scheduled tasks, or wiggum jobs. The model runs against the `/completion` endpoint (not chat completions). Context is composed fresh each turn from markdown files on disk.

### How loop.py works

Each turn:
1. Reads `TOPO.cache`, `IDENTITY.md`, `TOOLS.md`, `STATE.md`, `OPEN_LOOPS.md`.
2. Composes a single prompt string with all of these plus the current task.
3. Calls llama-server `/completion` with `grammar.gbnf` active.
4. Parses the response for `<tool>`, `<args>`, `<reason>` tags.
5. Dispatches the tool call.
6. Appends the result to `STATE.md`.
7. Repeats until `done` is called or `max_turns` is reached.

### STATE.md

A flat FIFO log. Each line is one tool call result with a UTC timestamp. When it exceeds 100 lines, the oldest batch is archived to `logs/state.archive` and replaced with a one-line summary. This keeps the context prompt bounded.

### Stuck detection

Before each turn, the loop checks the last 6 STATE.md lines for:
- Same tool + same args called 3+ times (exact repeat)
- Same tool name called 5+ times (spin)
- Same error message repeated twice in a row
- `NO_TOOL` appears twice (model stopped calling tools)

If any condition is true, the loop exits with `stuck=True` and logs the reason.

### OPEN_LOOPS.md

Tracks multi-step tasks the model opens with `loop_open`. Each open loop has a UUID, a task description, and a list of steps. The model updates it with `loop_update` and closes it with `loop_close`. This persists sub-task state across the STATE.md FIFO boundary.

### Hot reload

After a successful `skill_make` call (model writes a new tool), `_meta.regenerate_all()` is called and all tools are reloaded. The new tool is available on the next turn without restarting.

## Chat token format

`loop.py` wraps the prompt with `<start_of_turn>` / `<end_of_turn>` rather than Gemma 4's native `<|turn>` / `<turn|>` tokens. This is deliberate. llama.cpp's `/completion` endpoint does not yet reliably recognize Gemma 4's new control tokens on the raw completion path — the bundled chat-template state machine in current llama.cpp builds (as of the project drop date) lacks a dedicated `LLM_CHAT_TEMPLATE_GEMMA4` and falls back to heuristic detection. The legacy Gemma 2/3 markers are accepted by the same tokenizer and reliably activate the instruction-tuned head, so they are used here as a known-good compatibility path. The proxy path applies native Gemma 4 tokens via `gemma4.jinja` (rendered by llama-server, not Python). When llama.cpp adds first-class Gemma 4 template support, this file should be updated.
