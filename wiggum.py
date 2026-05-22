#!/usr/bin/env python3
"""
wiggum.py — Meta-loop orchestrator for Gemma Agent OS.

Decomposes a goal into jobs, runs each job with a context-compressed prompt,
tracks progress in CHECKLIST.md, detects stuck states, and rehydrates the
goal context at every turn so the model never loses its bearings.

Usage:
    python wiggum.py "your goal here"
    python wiggum.py --manifest runtime/manifests/abc123.json
    python wiggum.py --task-id linkedin-adds-0300  (from scheduled_tasks.json)
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

import loop as loop_mod
from tools import _lib
from tools.core.ctx_compress import run as ctx_compress
from tools.core.goal_check import run as goal_check
from tools.core.goal_plan import run as goal_plan


# ── Event log helpers ────────────────────────────────────────────────────────

_LOGS_DIR = ROOT / "logs"


def _log(kind: str, **kw) -> None:
    try:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        ev = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **kw}
        with open(_LOGS_DIR / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── Wiggum context prefix ────────────────────────────────────────────────────

def _build_wiggum_prefix(
    goal: str,
    job_id: str,
    job_title: str,
    step: int,
    total_steps: int,
    done: int,
    total: int,
    last_result: str = "",
) -> str:
    lines = [
        "[WIGGUM-CONTEXT]",
        f"GOAL:  {goal[:120]}",
        f"JOB:   {job_id} — {job_title[:100]}",
        f"STEP:  {step}/{total_steps}",
        f"DONE:  {done}/{total}",
    ]
    if last_result:
        lines.append(f"LAST:  {last_result[:120]}")
    lines.append("[/WIGGUM-CONTEXT]")
    lines.append("")
    return "\n".join(lines)


# ── Manifest loading / creation ──────────────────────────────────────────────

def _load_manifest(manifest_path: str) -> dict:
    p = Path(manifest_path)
    if not p.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    return json.loads(p.read_text(encoding="utf-8"))


def _create_manifest(goal: str, max_jobs: int = 10, token_budget: int = 2048) -> dict:
    result = goal_plan({"goal": goal, "max_jobs": max_jobs, "token_budget": token_budget})
    if "error" in result:
        raise RuntimeError(f"goal_plan failed: {result['error']}")
    manifest_path = result.get("manifest_path")
    if manifest_path:
        return _load_manifest(manifest_path)
    return {"goal": goal, "jobs": result["jobs"]}


# ── Job runner ───────────────────────────────────────────────────────────────

def _run_job(
    job: dict,
    goal: str,
    done_count: int,
    total_jobs: int,
    context_budget: int = 512,
    backend_url: str = "",
) -> dict:
    """Run one job via loop.loop() with wiggum context injected. Returns job result dict."""
    job_id    = job["id"]
    job_title = job["title"]
    max_turns = job.get("max_turns", 20)

    ctx = ctx_compress({"budget_tokens": context_budget, "include_loops": True})
    compressed_ctx = ctx.get("compressed", "")

    prefix = _build_wiggum_prefix(
        goal       = goal,
        job_id     = job_id,
        job_title  = job_title,
        step       = 1,
        total_steps= max_turns,
        done       = done_count,
        total      = total_jobs,
        last_result= compressed_ctx[-200:] if compressed_ctx else "",
    )

    _log("loop_job", job_id=job_id, title=job_title[:80], budget=context_budget)
    print(f"  [{job_id}] {job_title[:80]}", flush=True)

    result = loop_mod.loop(
        task          = job_title,
        max_turns     = max_turns,
        wiggum_prefix = prefix,
        backend_url   = backend_url,
    )

    status     = "done" if result.get("done") else ("stuck" if result.get("stuck") else "done")
    result_txt = result.get("reason", "") or (f"turns={result.get('turns', 0)}")

    if result.get("stuck"):
        _log("loop_stuck", job_id=job_id, reason=result.get("reason", ""))

    goal_check({"job_id": job_id, "status": status, "result": result_txt})
    return {**result, "status": status, "result": result_txt}


# ── Main run function ────────────────────────────────────────────────────────

def run(
    goal: str = "",
    manifest_path: str = "",
    max_jobs: int = 10,
    token_budget: int = 2048,
    context_budget: int = 512,
    backend_url: str = "",
    skip_done: bool = True,
) -> dict:
    """
    Main entry point.
    - goal: natural language goal (will be decomposed)
    - manifest_path: pre-built manifest JSON (skips decomposition)
    Returns summary dict.
    """
    if manifest_path:
        manifest = _load_manifest(manifest_path)
        goal = manifest.get("goal", goal)
    elif goal:
        manifest = _create_manifest(goal, max_jobs, token_budget)
    else:
        return {"error": "goal or manifest_path required"}

    jobs        = manifest.get("jobs", [])
    total_jobs  = len(jobs)
    goal_text   = manifest.get("goal", goal)

    _log("wiggum_goal", goal=goal_text[:200], jobs=total_jobs)
    print(f"\n{'='*60}", flush=True)
    print(f"WIGGUM  goal={goal_text[:80]}", flush=True)
    print(f"        jobs={total_jobs}", flush=True)
    print(f"{'='*60}\n", flush=True)

    done_count   = 0
    stuck_jobs   = []
    results      = []

    for job in jobs:
        if skip_done and job.get("status") == "done":
            done_count += 1
            continue

        job_result = _run_job(
            job            = job,
            goal           = goal_text,
            done_count     = done_count,
            total_jobs     = total_jobs,
            context_budget = context_budget,
            backend_url    = backend_url,
        )
        results.append({"job_id": job["id"], **job_result})

        if job_result.get("status") == "done":
            done_count += 1
        else:
            stuck_jobs.append(job["id"])

    _log(
        "loop_close",
        goal_summary = goal_text[:120],
        done         = done_count,
        total        = total_jobs,
        stuck        = stuck_jobs,
    )

    print(f"\n{'='*60}", flush=True)
    print(f"WIGGUM COMPLETE  done={done_count}/{total_jobs}  stuck={stuck_jobs}", flush=True)
    print(f"{'='*60}\n", flush=True)

    return {
        "goal":       goal_text,
        "total_jobs": total_jobs,
        "done":       done_count,
        "stuck":      stuck_jobs,
        "results":    results,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Wiggum meta-loop orchestrator")
    p.add_argument("goal",             nargs="?",  default="", help="Goal text")
    p.add_argument("--manifest",       default="", help="Path to manifest JSON")
    p.add_argument("--max-jobs",       type=int,   default=10)
    p.add_argument("--token-budget",   type=int,   default=2048)
    p.add_argument("--context-budget", type=int,   default=512)
    p.add_argument("--backend",        default="", help="llama-server URL override")
    a = p.parse_args()

    result = run(
        goal           = a.goal,
        manifest_path  = a.manifest,
        max_jobs       = a.max_jobs,
        token_budget   = a.token_budget,
        context_budget = a.context_budget,
        backend_url    = a.backend,
    )
    print(json.dumps(result, indent=2))
