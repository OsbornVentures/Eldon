"""fs_list: list a whitelisted directory, kind/name/size per entry."""
from pathlib import Path

from tools import _lib


def run(args: dict) -> dict:
    path = args.get("path", str(_lib.ROOT))
    if not _lib.path_allowed(path):
        return {"error": f"path not in fs_roots: {path}"}
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        return {"error": "not a directory"}
    entries = []
    try:
        for e in sorted(p.iterdir()):
            kind = "d" if e.is_dir() else "f"
            size = e.stat().st_size if e.is_file() else 0
            entries.append(f"{kind} {e.name} {size}")
    except PermissionError:
        return {"error": "permission denied"}
    return {"path": str(p), "entries": entries[:100], "count": len(entries)}
