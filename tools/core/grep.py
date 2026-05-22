"""grep: ripgrep wrapper with Python fallback, max 50 results."""
import re
import subprocess
from pathlib import Path

from tools import _lib


def run(args: dict) -> dict:
    pattern = args.get("pattern", "")
    path    = args.get("path", str(_lib.ROOT))
    if not pattern:
        return {"error": "empty pattern"}
    if not _lib.path_allowed(path):
        return {"error": f"path not in fs_roots: {path}"}

    # Try ripgrep first (fast).
    try:
        r = subprocess.run(
            ["rg", "-n", "--max-count=20", "--max-columns=200", pattern, path],
            capture_output=True, text=True, timeout=30, errors="replace",
        )
        matches = r.stdout.splitlines()[:50]
        return {"matches": matches, "count": len(matches)}
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        return {"error": "grep timed out"}

    # Python fallback when rg is not installed.
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return {"error": f"bad pattern: {e}"}
    matches = []
    p = Path(path).expanduser().resolve()
    files = [p] if p.is_file() else list(p.rglob("*"))
    for f in files:
        if not f.is_file():
            continue
        try:
            for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                if rx.search(line):
                    matches.append(f"{f}:{i}:{line[:200]}")
                    if len(matches) >= 50:
                        return {"matches": matches, "count": len(matches)}
        except Exception:
            continue
    return {"matches": matches, "count": len(matches)}
