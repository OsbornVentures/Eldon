"""task_list: list all scheduled tasks."""
import json
from pathlib import Path
from tools import _lib

TOOL_META = {
    "summary": "List all scheduled autonomous tasks.",
    "args":    '{"enabled_only"?: bool}',
    "returns": '{"tasks": list, "count": int}',
    "tags":    ["scheduler"],
}

TASKS_FILE = _lib.ROOT / "runtime" / "scheduled_tasks.json"


def run(args: dict) -> dict:
    enabled_only = bool(args.get("enabled_only", False))

    if not TASKS_FILE.exists():
        return {"tasks": [], "count": 0}

    try:
        tasks = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"tasks": [], "count": 0, "error": "could not parse scheduled_tasks.json"}

    if enabled_only:
        tasks = [t for t in tasks if t.get("enabled", True)]

    summary = [
        {
            "id":       t.get("id"),
            "name":     t.get("name"),
            "cron":     t.get("cron"),
            "enabled":  t.get("enabled", True),
            "next_run": t.get("next_run"),
            "last_run": t.get("last_run"),
            "wiggum":   t.get("wiggum", False),
        }
        for t in tasks
    ]

    return {"tasks": summary, "count": len(summary)}
