# The Proxy

`proxy.py` is a Flask server that sits between the client (browser UI or any OpenAI-compatible client) and llama-server.

```
client → proxy:8080 → llama-server:8081
```

Every request is forwarded transparently except `/v1/chat/completions`, which runs a tool-dispatch loop.

## How it works

1. Client sends a chat completion request (streaming or non-streaming).
2. Proxy makes a **non-streaming** request to llama-server to get a complete response.
3. If `finish_reason == "tool_calls"`:
   - Emits `delta.tool_calls` streaming events to the client (renders as tool block in the UI).
   - Executes the tool locally in Python.
   - Appends the tool result to the message history as a `role: tool` message.
   - Loops back to step 2.
4. When `finish_reason != "tool_calls"` (final answer):
   - Switches to streaming mode, forwards the SSE stream directly to the client.
   - Client renders the answer as a text block.

Max tool turns per request is controlled by `MAX_TOOL_TURNS` (default: 20).

## Why non-streaming for tool turns

The tool dispatch loop needs the complete model response to parse the tool call before executing. Streaming is only enabled for the final answer turn, which gives the client live token output without buffering the entire response.

## Tool loading

Tools are loaded from `tools/core/` and `tools/learned/` at startup. Any `.py` file with a `run(args: dict) -> dict` function is registered. The proxy builds OpenAI-format tool definitions from `_TOOL_META` and injects them into every request that doesn't already include a `tools` field.

## Configuration

| Env var        | Default                    | Purpose                    |
|----------------|----------------------------|----------------------------|
| LLAMA_BACKEND  | http://127.0.0.1:8081      | llama-server URL           |
| PROXY_PORT     | 8080                       | port this proxy listens on |
| PROXY_HOST     | 127.0.0.1                  | bind address               |

## /v1/stats

Returns a JSON snapshot of llama-server metrics: tps, kv cache ratio, slot states. Useful for monitoring inference state without reading raw Prometheus output.

## Event log

Every tool call, chat start, and chat end is appended to `logs/events.jsonl`. Use `logflow.py` to view it.
