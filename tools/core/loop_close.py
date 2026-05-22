"""loop_close: close a tracked loop with an outcome summary."""
import json
from pathlib import Path
from tools._lib import ROOT, now

LOOPS_DIR = ROOT / "logs" / "loops"

def run(args: dict) -> dict:
    loop_id = args.get("loop_id", "").strip()
    outcome = args.get("outcome", "completed").strip()
    if not loop_id:
        return {"error": "loop_id required"}
    path = LOOPS_DIR / f"{loop_id}.json"
    if not path.exists():
        return {"error": f"loop not found: {loop_id}"}
    rec = json.loads(path.read_text())
    rec.update({"status": "closed", "outcome": outcome, "closed": now()})
    path.write_text(json.dumps(rec, indent=2))
    return {"loop_id": loop_id, "status": "closed", "steps": len(rec["steps"])}
