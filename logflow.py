#!/usr/bin/env python3
"""
logflow.py — Event timeline viewer for Gemma Agent OS.

Usage:
    python logflow.py                    # all events
    python logflow.py --tail 50          # last 50 events
    python logflow.py --kind tool_call   # filter by event kind
    python logflow.py --loops            # wiggum/loop events only
    python logflow.py --browser          # browser session events
    python logflow.py --sched            # scheduler events
    python logflow.py --since 09:00      # events after 09:00 today
    python logflow.py --summary          # one-line daily stats
    python logflow.py --live             # tail -f mode (Ctrl+C to stop)
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

EVENTS = Path(__file__).parent / "logs" / "events.jsonl"
LOOPS  = Path(__file__).parent / "logs" / "loops"
BOLD   = "\033[1m"
RESET  = "\033[0m"

KIND_COLORS = {
    "chat_start":       "\033[36m",
    "chat_end":         "\033[32m",
    "tool_call":        "\033[33m",
    "tool_error":       "\033[31m",
    "error":            "\033[31m",
    "wiggum_goal":      "\033[35m",
    "loop_job":         "\033[34m",
    "loop_stuck":       "\033[31m",
    "loop_close":       "\033[32m",
    "sched_fire":       "\033[35m",
    "sched_done":       "\033[32m",
    "sched_error":      "\033[31m",
    "sched_start":      "\033[36m",
    "browser_open":     "\033[34m",
    "browser_act":      "\033[33m",
    "browser_err":      "\033[31m",
    "doc_parse":        "\033[36m",
    "checklist_update": "\033[32m",
}

LOOP_KINDS   = {"wiggum_goal", "loop_job", "loop_stuck", "loop_close", "loop_open", "loop_update", "loop_close_ev"}
BROWSER_KINDS = {"browser_open", "browser_act", "browser_err", "browser_close", "browser_shot"}
SCHED_KINDS   = {"sched_fire", "sched_done", "sched_error", "sched_start", "sched_stop"}


def _color(kind: str, text: str) -> str:
    return KIND_COLORS.get(kind, "") + text + RESET


def _load(path: Path) -> list:
    if not path.exists():
        return []
    return [l for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]


def _parse_since(since_str: str) -> str:
    """Return ISO-prefix like '2026-05-13T09:00' for filtering."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{today}T{since_str}"


def _summary(lines: list) -> None:
    by_day: dict = {}
    for raw in lines:
        try:
            e    = json.loads(raw)
            date = e.get("ts", "?")[:10]
            if date not in by_day:
                by_day[date] = {"chats": 0, "tools": 0, "errors": 0, "loops": 0, "sched": 0}
            kind = e.get("kind", "")
            if kind == "chat_start":
                by_day[date]["chats"] += 1
            elif kind == "tool_call":
                by_day[date]["tools"] += 1
            elif kind in ("tool_error", "error", "loop_stuck", "sched_error"):
                by_day[date]["errors"] += 1
            elif kind in LOOP_KINDS:
                by_day[date]["loops"] += 1
            elif kind in SCHED_KINDS:
                by_day[date]["sched"] += 1
        except Exception:
            continue

    print(f"\n{BOLD}  DAILY SUMMARY{RESET}")
    for date in sorted(by_day):
        d = by_day[date]
        print(f"  {date}  chats={d['chats']}  tools={d['tools']}  loops={d['loops']}  sched={d['sched']}  errors={d['errors']}")
    print()


def _render_event(e: dict) -> str:
    ts   = e.get("ts", "?")
    time = ts[11:19] if len(ts) >= 19 else ts
    kind = e.get("kind", "?")

    if kind == "tool_call":
        tool   = e.get("tool", "?")
        result = e.get("result", "")[:60]
        return f"  {time}  {_color(kind, f'TOOL  {tool:<22}')}  {result}"

    if kind == "tool_error":
        tool = e.get("tool", "?")
        err  = e.get("error", "")[:60]
        return f"  {time}  {_color(kind, f'ERR   {tool:<22}')}  {err}"

    if kind == "chat_start":
        n = e.get("n_messages", 0)
        return f"  {time}  {_color(kind, 'CHAT  start     ')}  messages={n}"

    if kind == "chat_end":
        turns  = e.get("turns", 0)
        tps    = e.get("tps", 0)
        tokens = e.get("tokens", 0)
        return f"  {time}  {_color(kind, 'CHAT  end       ')}  turns={turns}  tps={tps}  tokens={tokens}"

    if kind == "wiggum_goal":
        goal = e.get("goal", "")[:60]
        jobs = e.get("jobs", 0)
        return f"  {time}  {_color(kind, 'WIGGUM goal     ')}  jobs={jobs}  {goal}"

    if kind == "loop_job":
        job_id = e.get("job_id", "?")
        title  = e.get("title", "")[:50]
        return f"  {time}  {_color(kind, f'LOOP  job {job_id:<8}')}  {title}"

    if kind == "loop_stuck":
        job_id = e.get("job_id", "?")
        reason = e.get("reason", "")[:60]
        return f"  {time}  {_color(kind, f'LOOP  STUCK {job_id:<5}')}  {reason}"

    if kind == "loop_close":
        done  = e.get("done", 0)
        total = e.get("total", 0)
        stuck = e.get("stuck", [])
        return f"  {time}  {_color(kind, 'LOOP  close     ')}  done={done}/{total}  stuck={stuck}"

    if kind == "sched_fire":
        task_id = e.get("task_id", "?")
        name    = e.get("name", "")[:40]
        return f"  {time}  {_color(kind, f'SCHED fire {task_id:<10}')}  {name}"

    if kind == "sched_done":
        task_id = e.get("task_id", "?")
        turns   = e.get("turns", 0)
        elapsed = e.get("elapsed_sec", 0)
        return f"  {time}  {_color(kind, f'SCHED done {task_id:<10}')}  turns={turns}  {elapsed:.0f}s"

    if kind == "browser_open":
        url = e.get("url", "")[:50]
        sid = e.get("session_id", "?")[:8]
        return f"  {time}  {_color(kind, f'BROW  open {sid:<8}')}  {url}"

    if kind == "browser_act":
        action = e.get("action", "?")
        target = e.get("target", "")[:30]
        sid    = e.get("session_id", "?")[:8]
        return f"  {time}  {_color(kind, f'BROW  {action:<8} {sid:<8}')}  {target}"

    if kind == "browser_err":
        err = e.get("error", "")[:60]
        sid = e.get("session_id", "?")[:8]
        return f"  {time}  {_color(kind, f'BROW  ERR  {sid:<8}')}  {err}"

    if kind == "doc_parse":
        path   = e.get("path", "")[-40:]
        pages  = e.get("pages", 0)
        chunks = e.get("chunks", 0)
        return f"  {time}  {_color(kind, 'DOC   parse     ')}  pages={pages}  chunks={chunks}  {path}"

    if kind == "error":
        return f"  {time}  {_color(kind, 'ERROR           ')}  {e.get('msg','')[:60]}"

    return f"  {time}  {kind:<16}  {str(e)[:70]}"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tail",    type=int,  default=0,     help="Show last N events")
    p.add_argument("--kind",    default="",               help="Filter by event kind")
    p.add_argument("--loops",   action="store_true",      help="Show loop/wiggum events")
    p.add_argument("--browser", action="store_true",      help="Show browser events")
    p.add_argument("--sched",   action="store_true",      help="Show scheduler events")
    p.add_argument("--since",   default="",               help="Events after HH:MM today")
    p.add_argument("--summary", action="store_true",      help="Daily stats summary")
    p.add_argument("--live",    action="store_true",      help="Tail -f mode (Ctrl+C to stop)")
    a = p.parse_args()

    def _read_and_filter():
        lines = _load(EVENTS)

        if a.kind:
            lines = [l for l in lines if f'"kind": "{a.kind}"' in l]
        elif a.loops:
            lines = [l for l in lines if any(f'"kind": "{k}"' in l for k in LOOP_KINDS)]
        elif a.browser:
            lines = [l for l in lines if any(f'"kind": "{k}"' in l for k in BROWSER_KINDS)]
        elif a.sched:
            lines = [l for l in lines if any(f'"kind": "{k}"' in l for k in SCHED_KINDS)]

        if a.since:
            prefix = _parse_since(a.since)
            lines = [l for l in lines if '"ts"' not in l or l[l.find('"ts"'):l.find('"ts"')+40] >= f'"ts": "{prefix}']

        if a.tail:
            lines = lines[-a.tail:]
        return lines

    if a.summary:
        _summary(_load(EVENTS))
        return

    if a.live:
        seen = set()
        print(f"{BOLD}[logflow live — Ctrl+C to stop]{RESET}", flush=True)
        while True:
            lines = _read_and_filter()
            for raw in lines:
                if raw not in seen:
                    seen.add(raw)
                    try:
                        e = json.loads(raw)
                        print(_render_event(e), flush=True)
                    except Exception:
                        pass
            time.sleep(2)

    lines = _read_and_filter()

    print(f"\n{BOLD}{'='*72}{RESET}")
    print(f"  {BOLD}EVENT TIMELINE{RESET}  {len(lines)} events  {EVENTS}")
    print(f"{BOLD}{'='*72}{RESET}\n")

    prev_date = ""
    for raw in lines:
        try:
            e = json.loads(raw)
        except Exception:
            continue
        ts   = e.get("ts", "?")
        date = ts[:10]
        if date != prev_date:
            print(f"  {BOLD}--- {date} ---{RESET}")
            prev_date = date
        print(_render_event(e))

    # Show open loops if any
    if LOOPS.exists():
        open_loops = list(LOOPS.glob("*.json"))
        if open_loops:
            print(f"\n{BOLD}  --- OPEN LOOPS ({len(open_loops)}) ---{RESET}")
            for lf in sorted(open_loops):
                try:
                    rec    = json.loads(lf.read_text(encoding="utf-8"))
                    status = rec.get("status", "?")
                    col    = "\033[33m" if status == "open" else "\033[32m"
                    print(f"  {rec.get('id','?')}  {col}{status}{RESET}  {rec.get('task','?')[:60]}")
                    print(f"           opened={rec.get('opened','?')[:19]}  steps={len(rec.get('steps',[]))}")
                except Exception:
                    pass

    checklist = Path(__file__).parent / "CHECKLIST.md"
    if checklist.exists():
        lines_cl = checklist.read_text(encoding="utf-8").splitlines()
        pending  = sum(1 for l in lines_cl if l.startswith("[ ]"))
        done     = sum(1 for l in lines_cl if l.startswith("[x]"))
        stuck    = sum(1 for l in lines_cl if l.startswith("[!]"))
        if pending + done + stuck > 0:
            print(f"\n{BOLD}  --- CHECKLIST ---{RESET}")
            goal_line = next((l for l in lines_cl if l.startswith("# GOAL:")), "")
            print(f"  {goal_line}")
            print(f"  done={done}  pending={pending}  stuck={stuck}")

    print(f"\n{BOLD}{'='*72}{RESET}\n")


if __name__ == "__main__":
    main()
