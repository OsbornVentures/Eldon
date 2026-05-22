"""code_run: execute a Python snippet in a subprocess, return stdout/stderr."""
import subprocess, sys, tempfile
from pathlib import Path

MAX_OUT = 3000

def run(args: dict) -> dict:
    code = args.get("code", "").strip()
    timeout = min(int(args.get("timeout", 10)), 30)
    if not code:
        return {"error": "code required"}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        tmp = f.name
    try:
        r = subprocess.run(
            [sys.executable, tmp],
            capture_output=True, text=True, timeout=timeout, errors="replace",
        )
        return {"exit": r.returncode, "stdout": r.stdout[-MAX_OUT:], "stderr": r.stderr[-500:]}
    except subprocess.TimeoutExpired:
        return {"error": f"timeout after {timeout}s"}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        Path(tmp).unlink(missing_ok=True)
