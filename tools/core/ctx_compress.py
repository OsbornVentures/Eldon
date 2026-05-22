"""ctx_compress: compress STATE.md + OPEN_LOOPS.md to a token budget for wiggum context."""
import re
from collections import Counter
from tools import _lib

TOOL_META = {
    "summary": "Compress STATE.md + OPEN_LOOPS to fit a token budget. Used by wiggum loop.",
    "args":    '{"budget_tokens": int, "include_loops"?: bool}',
    "returns": '{"compressed": str, "original_tokens": int, "compressed_tokens": int}',
    "tags":    ["wiggum", "context"],
}

_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _compress_state(lines: list, keep_recent: int = 5) -> str:
    if not lines:
        return "(empty)"

    task_starts  = [l for l in lines if "TASK_START" in l]
    loop_opens   = [l for l in lines if "LOOP_OPEN" in l or "OPEN_LOOPS" in l]
    recent       = lines[-keep_recent:]

    older = lines[:-keep_recent] if len(lines) > keep_recent else []
    if older:
        counts: Counter = Counter()
        first_ts = last_ts = ""
        for line in older:
            parts = line.split(" ", 2)
            if len(parts) >= 2:
                if not first_ts:
                    first_ts = parts[0]
                last_ts = parts[0]
                counts[parts[1].lower()] += 1
        count_str = " ".join(f"{t}={c}" for t, c in counts.most_common(6))
        summary = f"[ARCHIVE {len(older)} entries {first_ts[:16]}→{last_ts[:16]}: {count_str}]"
    else:
        summary = ""

    out_lines = []
    if task_starts:
        out_lines.append(task_starts[-1])
    if loop_opens:
        out_lines.extend(loop_opens[-3:])
    if summary:
        out_lines.append(summary)
    out_lines.extend(recent)

    return "\n".join(dict.fromkeys(out_lines))


def run(args: dict) -> dict:
    budget  = int(args.get("budget_tokens", 512))
    inc_loops = args.get("include_loops", True)

    state_path = _lib.ROOT / "STATE.md"
    loops_path = _lib.ROOT / "OPEN_LOOPS.md"

    state_text = state_path.read_text(encoding="utf-8") if state_path.exists() else ""
    loops_text = loops_path.read_text(encoding="utf-8") if inc_loops and loops_path.exists() else ""

    original = state_text + ("\n" + loops_text if loops_text else "")
    original_tokens = _estimate_tokens(original)

    state_lines = [l for l in state_text.splitlines() if l.strip()]
    compressed_state = _compress_state(state_lines)

    if loops_text.strip():
        compressed = compressed_state + "\n\n## OPEN_LOOPS\n" + loops_text.strip()
    else:
        compressed = compressed_state

    char_budget = budget * _CHARS_PER_TOKEN
    if len(compressed) > char_budget:
        compressed = compressed[-char_budget:]
        idx = compressed.find("\n")
        if idx > 0:
            compressed = compressed[idx + 1:]

    return {
        "compressed":        compressed,
        "original_tokens":   original_tokens,
        "compressed_tokens": _estimate_tokens(compressed),
    }
