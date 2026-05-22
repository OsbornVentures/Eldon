"""shell: run one allowlisted command, no chaining, 30s timeout."""
import subprocess

from tools import _lib


def run(args: dict) -> dict:
    cmd = str(args.get("cmd", "")).strip()
    if not cmd:
        return {"error": "empty cmd"}
    for pat in _lib.BLACKLIST_PATTERNS:
        if pat.search(cmd):
            return {"error": f"blocked by blacklist: {pat.pattern}"}
    tokens = cmd.split()
    if not tokens:
        return {"error": "empty cmd"}
    first = tokens[0].lower()
    if first not in {c.lower() for c in _lib.ALLOWLIST}:
        return {"error": f"not in allowlist: {tokens[0]}"}
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=30, errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"error": "command timed out"}
    except Exception as e:
        return {"error": str(e)[:120]}
    return {
        "exit":   r.returncode,
        "stdout": (r.stdout or "")[-2000:],
        "stderr": (r.stderr or "")[-500:],
    }
