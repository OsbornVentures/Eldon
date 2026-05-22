"""goal_plan: decompose a goal into a job manifest and write CHECKLIST.md."""
import json
import re
import uuid
from tools import _lib

TOOL_META = {
    "summary": "Decompose a goal into wiggum job manifest. Writes CHECKLIST.md.",
    "args":    '{"goal": str, "max_jobs"?: int, "token_budget"?: int}',
    "returns": '{"checklist_path": str, "jobs": list, "total_jobs": int}',
    "tags":    ["wiggum", "planning"],
}

_MANIFEST_DIR = _lib.ROOT / "runtime" / "manifests"


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", text.lower()[:40]).strip("_")


def _split_goal_into_jobs(goal: str, max_jobs: int, token_budget: int) -> list:
    """
    Heuristic decomposition without LLM:
    - If goal contains numbered steps, use those as jobs.
    - If goal has "and then" / "then" / ";" splits, split on those.
    - Otherwise treat as single job.
    Returns list of {id, title, steps, budget, max_turns}.
    """
    parts = []

    numbered = re.findall(r"\d+\.\s+(.+?)(?=\d+\.|$)", goal, re.S)
    if len(numbered) >= 2:
        parts = [p.strip() for p in numbered if p.strip()]
    else:
        splits = re.split(r"\s+(?:and then|then|;|,\s*then)\s+", goal, flags=re.I)
        if len(splits) >= 2:
            parts = [s.strip() for s in splits if s.strip()]

    if not parts:
        parts = [goal.strip()]

    parts = parts[:max_jobs]

    jobs = []
    for i, title in enumerate(parts, 1):
        jobs.append({
            "id":         f"JOB-{i:03d}",
            "title":      title[:120],
            "steps":      [],
            "budget":     token_budget,
            "max_turns":  20,
            "status":     "pending",
        })
    return jobs


def _write_checklist(goal: str, jobs: list, checklist_path) -> None:
    lines = [
        f"# GOAL: {goal}",
        f"# STARTED: {_lib.now()}",
        "# STATUS: active",
        "",
    ]
    for job in jobs:
        box = "[x]" if job["status"] == "done" else "[!]" if job["status"] == "stuck" else "[ ]"
        line = (
            f"{box} {job['id']} | {job['title']} "
            f"| budget={job['budget']}tok | turns={job['max_turns']} "
            f"| status={job['status']}"
        )
        if job.get("result"):
            line += f" | result={job['result'][:80]}"
        lines.append(line)
    checklist_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: dict) -> dict:
    goal         = (args.get("goal") or "").strip()
    max_jobs     = int(args.get("max_jobs", 10))
    token_budget = int(args.get("token_budget", 2048))

    if not goal:
        return {"error": "goal required"}

    jobs = _split_goal_into_jobs(goal, max_jobs, token_budget)

    _MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    manifest_id = str(uuid.uuid4())[:8]
    manifest_path = _MANIFEST_DIR / f"{manifest_id}.json"
    manifest = {
        "id":    manifest_id,
        "goal":  goal,
        "jobs":  jobs,
        "created": _lib.now(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    checklist_path = _lib.ROOT / "CHECKLIST.md"
    _write_checklist(goal, jobs, checklist_path)

    return {
        "checklist_path": str(checklist_path),
        "manifest_path":  str(manifest_path),
        "jobs":           jobs,
        "total_jobs":     len(jobs),
    }
