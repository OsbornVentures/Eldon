# Why Gemma 4

ELDON is built specifically for Gemma 4 E4B. This is not incidental.

## The model

Gemma 4 E4B is a 4-billion-parameter dense edge model in the Gemma 4 family (the "E" stands for Edge in Google's E2B/E4B naming). At Q8_0 quantization (Bartowski), it runs entirely on GPU on hardware with 7-8 GB of effective VRAM — including unified memory systems like AMD Radeon 880M/840M with a 24 GB UMA pool.

Its instruction-following at this size is strong enough to reliably parse tool call formats, stay on multi-step tasks, and use the wiggum context prefix correctly.

It is aligned well enough out of the box that no abliteration or jailbreak is needed for general agentic tasks. The system does not need safety guardrails removed to be useful.

## The template

`gemma4.jinja` implements Gemma 4's native chat format including its tool call tokens (`<|tool_call>`, `<|tool_response>`, `<|channel>`). Without the correct template, llama-server falls back to a generic format and tool calling breaks.

The template is what allows the structured thinking block (reasoning), the tool call block, and the text answer to render as distinct UI elements in the browser client.

## The grammar

`grammar.gbnf` is used on the direct completion path (`loop.py`). It constrains the model's output to exactly one valid tool call per turn — right tool name, valid JSON arguments, brief reason. This eliminates malformed tool calls without requiring the model to self-correct.

The grammar is compiled once by llama-server. Its per-token cost is negligible compared to matrix multiply time.

## Why not a larger model

On hardware with 7-8 GB effective VRAM, a larger model means more layers offloaded to CPU RAM, which drops generation speed below the usable threshold for interactive agentic work. At ngl=99 (all layers on GPU), Gemma 4 E4B generates at 10-15 t/s on this hardware. That is fast enough for real-time tool loops.

## What this means for portability

Any system that can run `llama-server` with `gemma4.jinja` and has enough VRAM for full GPU offload of Gemma 4 E4B Q8_0 (~5.5 GB model weight + KV cache overhead) can run ELDON at full performance. On systems with more VRAM, larger Gemma 4 variants will work with the same template.
