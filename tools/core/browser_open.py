"""browser_open: open a Playwright browser session. Returns session_id."""
import json
import uuid
from pathlib import Path
from tools import _lib

TOOL_META = {
    "summary": "Open a Playwright browser session. Returns session_id for other browser_ tools.",
    "args":    '{"url": str, "headless"?: bool, "profile"?: str, "human_pace"?: bool}',
    "returns": '{"session_id": str, "url": str, "title": str, "dom_ready": bool}',
    "tags":    ["browser", "playwright"],
    "human_pace": True,
}

SESSIONS_DIR = _lib.ROOT / "runtime" / "browser_sessions"

# Module-level storage for active playwright instances.
# Key: session_id → {"browser": Browser, "context": BrowserContext, "page": Page}
_SESSIONS: dict = {}


def _sessions_dir() -> Path:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return SESSIONS_DIR


def run(args: dict) -> dict:
    url         = (args.get("url") or "").strip()
    headless    = args.get("headless", True)
    profile     = (args.get("profile") or "default").strip()
    human_pace  = bool(args.get("human_pace", False))

    if not url:
        return {"error": "url required"}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"error": "playwright not installed — run: pip install playwright && python -m playwright install chromium"}

    session_id = str(uuid.uuid4())[:8]

    try:
        pw      = sync_playwright().start()
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        title = page.title()

        _SESSIONS[session_id] = {
            "pw": pw, "browser": browser, "context": context, "page": page,
        }

        rec = {
            "id":           session_id,
            "url":          page.url,
            "profile":      profile,
            "human_pace":   human_pace,
            "headless":     headless,
            "opened":       _lib.now(),
            "actions_taken": 0,
            "last_action":  _lib.now(),
        }
        (_sessions_dir() / f"{session_id}.json").write_text(
            json.dumps(rec, indent=2), encoding="utf-8"
        )

        return {
            "session_id": session_id,
            "url":        page.url,
            "title":      title,
            "dom_ready":  True,
        }
    except Exception as e:
        return {"error": str(e)[:200]}
