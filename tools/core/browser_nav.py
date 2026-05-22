"""browser_nav: navigate an open browser session to a new URL or path."""
from tools import _lib
from tools.core.browser_open import _SESSIONS, SESSIONS_DIR
import json

TOOL_META = {
    "summary": "Navigate an open browser session to a new URL or relative path.",
    "args":    '{"session_id": str, "url_or_path": str}',
    "returns": '{"url": str, "title": str, "dom_changed": bool}',
    "tags":    ["browser", "playwright"],
}


def run(args: dict) -> dict:
    session_id  = (args.get("session_id") or "").strip()
    url_or_path = (args.get("url_or_path") or "").strip()

    if not session_id:
        return {"error": "session_id required"}
    if not url_or_path:
        return {"error": "url_or_path required"}

    sess = _SESSIONS.get(session_id)
    if not sess:
        return {"error": f"session not found: {session_id} — call browser_open first"}

    try:
        page     = sess["page"]
        prev_url = page.url
        if url_or_path.startswith(("http://", "https://")):
            page.goto(url_or_path, wait_until="domcontentloaded", timeout=30000)
        else:
            from urllib.parse import urljoin
            page.goto(urljoin(prev_url, url_or_path), wait_until="domcontentloaded", timeout=30000)

        new_url = page.url
        title   = page.title()

        sess_file = SESSIONS_DIR / f"{session_id}.json"
        if sess_file.exists():
            rec = json.loads(sess_file.read_text(encoding="utf-8"))
            rec["url"]         = new_url
            rec["last_action"] = _lib.now()
            sess_file.write_text(json.dumps(rec, indent=2), encoding="utf-8")

        return {"url": new_url, "title": title, "dom_changed": new_url != prev_url}
    except Exception as e:
        return {"error": str(e)[:200]}
