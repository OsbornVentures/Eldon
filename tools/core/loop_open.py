"""loop_open: open a tracked task loop. Returns loop_id for update/close."""
import json, uuid
from pathlib import Path
from tools._lib import ROOT, now

LOOPS_DIR = ROOT / "logs" / "loops"

def run(args: dict) -> dict:
    task = args.get("task", "").strip()
    if not task:
        return {"error": "task required"}
    LOOPS_DIR.mkdir(parents=True, exist_ok=True)
    loop_id = str(uuid.uuid4())[:8]
    rec = {"id": loop_id, "task": task, "status": "open", "opened": now(), "steps": []}
    (LOOPS_DIR / f"{loop_id}.json").write_text(json.dumps(rec, indent=2))
    return {"loop_id": loop_id, "status": "opened"}
