"""goal_check: update a job status in CHECKLIST.md and the manifest."""
import json
import re
from tools import _lib

TOOL_META = {
    "summary": "Mark a wiggum job done/stuck/skip in CHECKLIST.md.",
    "args":    '{"job_id": str, "status": str, "result"?: str}',
    "returns": '{"job_id": str, "old_status": str, "new_status": str, "remaining_jobs": int}',
    "tags":    ["wiggum", "planning"],
}

VALID_STATUSES = {"done", "stuck", "skip", "pending", "active"}


def run(args: dict) -> dict:
    job_id     = (args.get("job_id") or "").strip().upper()
    new_status = (args.get("status") or "").strip().lower()
    result_txt = (args.get("result") or "").strip()

    if not job_id:
        return {"error": "job_id required"}
    if new_status not in VALID_STATUSES:
        return {"error": f"status must be one of {sorted(VALID_STATUSES)}"}

    checklist_path = _lib.ROOT / "CHECKLIST.md"
    if not checklist_path.exists():
        return {"error": "CHECKLIST.md not found — call goal_plan first"}

    lines = checklist_path.read_text(encoding="utf-8").splitlines()
    old_status = "unknown"
    found = False
    new_lines = []
    remaining = 0

    for line in lines:
        if re.match(rf"^\[.?\]\s+{re.escape(job_id)}\b", line):
            found = True
            m = re.search(r"status=(\w+)", line)
            old_status = m.group(1) if m else "unknown"

            box = "[x]" if new_status == "done" else "[!]" if new_status in ("stuck", "skip") else "[ ]"
            line = re.sub(r"^\[.?\]", box, line)
            line = re.sub(r"status=\w+", f"status={new_status}", line)
            if result_txt:
                if "result=" in line:
                    line = re.sub(r"result=[^\|]*", f"result={result_txt[:80]}", line)
                else:
                    line += f" | result={result_txt[:80]}"
        new_lines.append(line)

    if not found:
        return {"error": f"job_id not found: {job_id}"}

    remaining = sum(
        1 for l in new_lines
        if re.match(r"^\[ \]", l) and "status=pending" in l
    )

    checklist_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    return {
        "job_id":         job_id,
        "old_status":     old_status,
        "new_status":     new_status,
        "remaining_jobs": remaining,
    }
