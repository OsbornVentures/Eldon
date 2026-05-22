"""fs_write: write or append to a whitelisted path; auto-mkdir parents."""
from pathlib import Path

from tools import _lib


def run(args: dict) -> dict:
    path    = args.get("path", "")
    content = args.get("content", "")
    mode    = args.get("mode", "replace")
    if not path or not _lib.path_allowed(path):
        return {"error": f"path not in fs_roots: {path}"}
    if mode not in ("replace", "append"):
        return {"error": "mode must be replace or append"}
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    if mode == "append":
        with p.open("a", encoding="utf-8") as f:
            f.write(content)
    else:
        p.write_text(content, encoding="utf-8")
    return {"path": str(p), "bytes": len(content), "mode": mode}
