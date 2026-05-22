"""fs_read: read a whitelisted file, optional 1-indexed line range."""
from pathlib import Path

from tools import _lib


def run(args: dict) -> dict:
    path = args.get("path", "")
    if not path or not _lib.path_allowed(path):
        return {"error": f"path not in fs_roots: {path}"}
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return {"error": "not found"}
    if p.is_dir():
        return {"error": "is directory, use fs_list"}
    try:
        all_lines = p.read_text(errors="replace").splitlines()
    except Exception as e:
        return {"error": str(e)[:120]}
    total = len(all_lines)
    start = max(1, int(args.get("start", 1)))
    end   = args.get("end", total)
    if end is None or end == -1 or int(end) > total:
        end = total
    end = int(end)
    chunk = all_lines[start - 1:end]
    if len(chunk) > 500:
        chunk = chunk[:500]
        end = start + 499
    return {"path": str(p), "lines": chunk, "total": total, "shown": f"{start}-{end}"}
