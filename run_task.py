#!/usr/bin/env python3
"""
run_task.py — Manually fire a scheduled task by ID, bypassing cron timing.

Usage:
    python run_task.py                       # list all tasks
    python run_task.py <task_id>             # fire immediately
    python run_task.py <task_id> --dry-run   # print prompt, don't run
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

from scheduler import _load_tasks, _fire_task


def _list_tasks(tasks: list) -> None:
    if not tasks:
        print("No scheduled tasks found.")
        return
    print(f"\n{'ID':<42} {'STATUS':<8} {'NEXT RUN':<20}  NAME")
    print("-" * 90)
    for t in tasks:
        enabled  = "ON " if t.get("enabled", True) else "off"
        next_run = str(t.get("next_run", ""))[:19] or "(unset)"
        print(f"  {t['id']:<40} {enabled:<8} {next_run:<20}  {t.get('name', '')}")
    print()


def main() -> None:
    tasks = _load_tasks()

    if len(sys.argv) < 2:
        _list_tasks(tasks)
        print("Usage: python run_task.py <task_id> [--dry-run]")
        sys.exit(0)

    task_id = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        print(f"Task not found: {task_id!r}")
        _list_tasks(tasks)
        sys.exit(1)

    print(f"\n[run_task] firing: {task_id} — {task.get('name', '')}")
    _fire_task(task, dry_run=dry_run)
    print("[run_task] done.")


if __name__ == "__main__":
    main()
