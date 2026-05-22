#!/usr/bin/env python3
"""
scheduler.py — Timer-based autonomous task injector for Gemma Agent OS.

"A task scheduler is just a prompt injection on a timer."
Every enabled task with next_run <= now() fires as a loop.loop() or wiggum.run() call.

Usage:
    python scheduler.py              # run indefinitely
    python scheduler.py --once       # fire due tasks once, then exit
    python scheduler.py --dry-run    # print what would fire, don't run

Stop: create runtime/scheduler.stop  (scheduler exits on next tick)
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

import loop as loop_mod
from tools import _lib

TASKS_FILE  = ROOT / "runtime" / "scheduled_tasks.json"
STOP_FILE   = ROOT / "runtime" / "scheduler.stop"
SCHED_LOG   = ROOT / "logs" / "scheduler.jsonl"
POLL_SEC    = 60


def _log(kind: str, **kw) -> None:
    try:
        SCHED_LOG.parent.mkdir(parents=True, exist_ok=True)
        ev = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **kw}
        with open(SCHED_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        with open(ROOT / "logs" / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _load_tasks() -> list:
    if not TASKS_FILE.exists():
        return []
    try:
        return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_tasks(tasks: list) -> None:
    TASKS_FILE.write_text(json.dumps(tasks, indent=2), encoding="utf-8")


def _compute_next_run(cron: str) -> str:
    try:
        from croniter import croniter
        it = croniter(cron, datetime.now(timezone.utc))
        return it.get_next(datetime).isoformat()
    except Exception:
        return ""


def _is_due(task: dict) -> bool:
    if not task.get("enabled", True):
        return False
    next_run = task.get("next_run")
    if not next_run:
        return False
    try:
        nr = datetime.fromisoformat(next_run)
        if nr.tzinfo is None:
            nr = nr.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= nr
    except Exception:
        return False


def _fire_task(task: dict, dry_run: bool = False) -> None:
    task_id = task.get("id", "?")
    name    = task.get("name", "?")
    prompt  = task.get("prompt", "")
    max_turns = int(task.get("max_turns", 30))
    use_wiggum = bool(task.get("wiggum", False))

    print(f"  [SCHED] firing: {task_id} — {name}", flush=True)
    _log("sched_fire", task_id=task_id, name=name)

    if dry_run:
        print(f"  [DRY-RUN] would run: {prompt[:80]}", flush=True)
        return

    t0 = time.perf_counter()
    try:
        if use_wiggum:
            import wiggum as wiggum_mod
            result = wiggum_mod.run(goal=prompt, max_jobs=10)
            turns  = result.get("done", 0)
            tps    = 0.0
        else:
            result = loop_mod.loop(prompt, max_turns=max_turns)
            turns  = result.get("turns", 0)
            tps    = 0.0
    except Exception as e:
        _log("sched_error", task_id=task_id, error=str(e)[:200])
        print(f"  [SCHED] error: {e}", flush=True)
        return

    elapsed = time.perf_counter() - t0
    _log("sched_done", task_id=task_id, turns=turns, elapsed_sec=round(elapsed, 1))
    print(f"  [SCHED] done: {task_id}  turns={turns}  elapsed={elapsed:.0f}s", flush=True)


def tick(tasks: list, dry_run: bool = False) -> list:
    due = [t for t in tasks if _is_due(t)]
    if not due:
        return tasks

    print(f"  [SCHED] {len(due)} task(s) due", flush=True)

    for task in due:
        _fire_task(task, dry_run=dry_run)
        if not dry_run:
            next_run = _compute_next_run(task.get("cron", ""))
            task["last_run"] = _lib.now()
            task["next_run"] = next_run

    return tasks


def run(once: bool = False, dry_run: bool = False) -> None:
    print(f"[scheduler] started  poll={POLL_SEC}s  stop_file={STOP_FILE}", flush=True)
    _log("sched_start", poll_sec=POLL_SEC)

    while True:
        if STOP_FILE.exists():
            print("[scheduler] stop file found — exiting", flush=True)
            _log("sched_stop", reason="stop_file")
            STOP_FILE.unlink(missing_ok=True)
            break

        tasks = _load_tasks()
        tasks = tick(tasks, dry_run=dry_run)
        if not dry_run:
            _save_tasks(tasks)

        if once:
            break

        time.sleep(POLL_SEC)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Gemma Agent OS task scheduler")
    p.add_argument("--once",    action="store_true", help="Fire due tasks once and exit")
    p.add_argument("--dry-run", action="store_true", help="Print tasks that would fire, don't run")
    a = p.parse_args()
    run(once=a.once, dry_run=a.dry_run)
