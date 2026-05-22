"""topo: return cached topology snapshot; force=true to refresh."""
from tools import _lib


def run(args: dict) -> dict:
    force = bool(args.get("force", False))
    snap, cached, age = _lib.ensure_topo(force=force)
    return {"snapshot": snap, "cached": cached, "age_sec": age}
