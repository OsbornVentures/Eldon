"""browser_shot: take a screenshot of the current browser page.
VL FALLBACK ONLY — call this only when browser_dom() returns vl_needed=True.
"""
from pathlib import Path
from tools import _lib
from tools.core.browser_open import _SESSIONS, SESSIONS_DIR

TOOL_META = {
    "summary": "Screenshot current browser page. VL fallback: use ONLY when browser_dom vl_needed=True.",
    "args":    '{"session_id": str}',
    "returns": '{"path": str, "width": int, "height": int, "note": str}',
    "tags":    ["browser", "playwright", "vl"],
    "notes":   "Output path can be fed to VL model. Do NOT call routinely — DOM is preferred.",
}

SHOTS_DIR = _lib.ROOT / "runtime" / "browser_sessions"


def run(args: dict) -> dict:
    session_id = (args.get("session_id") or "").strip()
    if not session_id:
        return {"error": "session_id required"}

    sess = _SESSIONS.get(session_id)
    if not sess:
        return {"error": f"session not found: {session_id} — call browser_open first"}

    try:
        page = sess["page"]
        SHOTS_DIR.mkdir(parents=True, exist_ok=True)
        shot_path = SHOTS_DIR / f"{session_id}_shot.png"
        page.screenshot(path=str(shot_path), full_page=False)
        size = page.evaluate("() => ({width: window.innerWidth, height: window.innerHeight})")
        return {
            "path":   str(shot_path),
            "width":  size.get("width", 0),
            "height": size.get("height", 0),
            "note":   "Feed this path to VL. Only use when DOM was insufficient.",
        }
    except Exception as e:
        return {"error": str(e)[:200]}
