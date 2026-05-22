"""loop_update: append a step to an open loop."""
import json
from pathlib import Path
from tools._lib import ROOT, now

LOOPS_DIR = ROOT / "logs" / "loops"

def run(args: dict) -> dict:
    loop_id = args.get("loop_id", "").strip()
    step = args.get("step", "").strip()
    if not loop_id or not step:
        return {"error": "loop_id and step required"}
    path = LOOPS_DIR / f"{loop_id}.json"
    if not path.exists():
        return {"error": f"loop not found: {loop_id}"}
    rec = json.loads(path.read_text())
    rec["steps"].append({"ts": now(), "step": step})
    rec["updated"] = now()
    path.write_text(json.dumps(rec, indent=2))
    return {"loop_id": loop_id, "steps": len(rec["steps"])}
