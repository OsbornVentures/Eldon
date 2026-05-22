"""browser_close: close an open Playwright browser session and clean up."""
import json
from tools import _lib
from tools.core.browser_open import _SESSIONS, SESSIONS_DIR

TOOL_META = {
    "summary": "Close a browser session and release resources.",
    "args":    '{"session_id": str}',
    "returns": '{"closed": bool, "session_id": str}',
    "tags":    ["browser", "playwright"],
}


def run(args: dict) -> dict:
    session_id = (args.get("session_id") or "").strip()
    if not session_id:
        return {"error": "session_id required"}

    sess = _SESSIONS.get(session_id)
    if not sess:
        sess_file = SESSIONS_DIR / f"{session_id}.json"
        if sess_file.exists():
            sess_file.unlink()
        return {"closed": False, "session_id": session_id, "note": "session not in memory (may have been reset)"}

    try:
        try:
            sess["context"].close()
        except Exception:
            pass
        try:
            sess["browser"].close()
        except Exception:
            pass
        try:
            sess["pw"].stop()
        except Exception:
            pass
    except Exception:
        pass

    del _SESSIONS[session_id]

    sess_file = SESSIONS_DIR / f"{session_id}.json"
    if sess_file.exists():
        sess_file.unlink()

    return {"closed": True, "session_id": session_id}
