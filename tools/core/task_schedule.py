"""task_schedule: create or update a scheduled autonomous task."""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from tools import _lib

TOOL_META = {
    "summary": "Create a scheduled autonomous task (cron-based prompt injection).",
    "args":    '{"name": str, "prompt": str, "cron": str, "enabled"?: bool, "max_turns"?: int, "wiggum"?: bool}',
    "returns": '{"id": str, "name": str, "cron": str, "next_run": str}',
    "tags":    ["scheduler"],
    "notes":   "cron format: '0 9 * * 1-5' (9am Mon-Fri). Use wiggum=true for multi-step goals.",
}

TASKS_FILE = _lib.ROOT / "runtime" / "scheduled_tasks.json"


def _compute_next_run(cron: str) -> str:
    try:
        from croniter import croniter
        it = croniter(cron, datetime.now(timezone.utc))
        return it.get_next(datetime).isoformat()
    except Exception:
        return ""


def _load_tasks() -> list:
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TASKS_FILE.exists():
        return []
    try:
        return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_tasks(tasks: list) -> None:
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASKS_FILE.write_text(json.dumps(tasks, indent=2), encoding="utf-8")


def _validate_cron(cron: str) -> bool:
    try:
        from croniter import croniter
        return croniter.is_valid(cron)
    except ImportError:
        parts = cron.strip().split()
        return len(parts) == 5


def run(args: dict) -> dict:
    name      = (args.get("name") or "").strip()
    prompt    = (args.get("prompt") or "").strip()
    cron      = (args.get("cron") or "").strip()
    enabled   = bool(args.get("enabled", True))
    max_turns = int(args.get("max_turns", 30))
    wiggum    = bool(args.get("wiggum", False))

    if not name:
        return {"error": "name required"}
    if not prompt:
        return {"error": "prompt required"}
    if not cron:
        return {"error": "cron required (e.g. '0 9 * * 1-5')"}
    if not _validate_cron(cron):
        return {"error": f"invalid cron expression: {cron}"}

    next_run = _compute_next_run(cron)
    tasks    = _load_tasks()

    task_id = re.sub(r"[^a-z0-9\-]", "-", name.lower())[:40]
    existing = next((t for t in tasks if t["id"] == task_id), None)
    if existing:
        existing.update({
            "prompt":    prompt,
            "cron":      cron,
            "enabled":   enabled,
            "max_turns": max_turns,
            "wiggum":    wiggum,
            "next_run":  next_run,
            "updated":   _lib.now(),
        })
        _save_tasks(tasks)
        return {"id": task_id, "name": name, "cron": cron, "next_run": next_run, "action": "updated"}

    task = {
        "id":        task_id,
        "name":      name,
        "prompt":    prompt,
        "cron":      cron,
        "enabled":   enabled,
        "max_turns": max_turns,
        "wiggum":    wiggum,
        "last_run":  None,
        "next_run":  next_run,
        "created":   _lib.now(),
    }
    tasks.append(task)
    _save_tasks(tasks)

    return {"id": task_id, "name": name, "cron": cron, "next_run": next_run, "action": "created"}
