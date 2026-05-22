"""browser_act: perform an action in an open browser session.
Human-pace mode: adds realistic jitter delays when session.human_pace=True.
Actions: click, type, select, scroll, wait, key, hover, clear.
"""
import json
import random
import time
from pathlib import Path
from tools import _lib
from tools.core.browser_open import _SESSIONS, SESSIONS_DIR

TOOL_META = {
    "summary": "Perform a browser action (click/type/scroll/wait/key/hover). Supports human_pace jitter.",
    "args":    '{"session_id": str, "action": str, "target"?: str, "value"?: str}',
    "returns": '{"success": bool, "new_url": str, "dom_changed": bool, "error"?: str}',
    "tags":    ["browser", "playwright"],
    "human_pace": True,
    "notes":   (
        "Actions: click(target), type(target,value), select(target,value), "
        "scroll(up|down|top|bottom), wait(ms), key(Enter|Tab|Escape...), hover(target), clear(target). "
        "target = DOM id from browser_dom()"
    ),
}

VALID_ACTIONS = {"click", "type", "select", "scroll", "wait", "key", "hover", "clear"}
SCROLL_DIRS   = {"up", "down", "top", "bottom"}


def _get_human_pace(session_id: str) -> bool:
    sess_file = SESSIONS_DIR / f"{session_id}.json"
    if sess_file.exists():
        try:
            rec = json.loads(sess_file.read_text(encoding="utf-8"))
            return bool(rec.get("human_pace", False))
        except Exception:
            pass
    return False


def _jitter(ms: int) -> float:
    return ms * random.uniform(0.8, 1.3) / 1000.0


def _human_sleep(base_ms: int = 1200) -> None:
    time.sleep(_jitter(base_ms))


def _update_session(session_id: str, new_url: str) -> None:
    sess_file = SESSIONS_DIR / f"{session_id}.json"
    if sess_file.exists():
        try:
            rec = json.loads(sess_file.read_text(encoding="utf-8"))
            rec["url"]           = new_url
            rec["last_action"]   = _lib.now()
            rec["actions_taken"] = rec.get("actions_taken", 0) + 1
            sess_file.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        except Exception:
            pass


def _find_element(page, target: str):
    """Locate element by DOM id (from browser_dom), text content, or CSS selector."""
    if not target:
        return None

    js = f"""
    () => {{
      // Try elements with matching generated id attribute or data we injected
      const TAGS = 'a,button,input,select,textarea,[role=button],[role=link],[tabindex]';
      for (const el of document.querySelectorAll(TAGS)) {{
        const text = (el.value||el.innerText||el.textContent||el.getAttribute('aria-label')||'').trim().slice(0,120);
        const name  = el.name || el.id || '';
        const tag   = el.tagName.toLowerCase();
        const hashKey = tag + ':' + text.slice(0,30) + ':' + name;
        const genId   = tag + '-' + Math.abs(hashKey.split('').reduce((a,c)=>(a<<5)-a+c.charCodeAt(0),0)).toString(36).slice(0,6);
        if (genId === {json.dumps(target)}) return el;
      }}
      // Fallback: CSS selector
      return document.querySelector({json.dumps(target)}) || null;
    }}
    """
    el = page.evaluate_handle(js)
    if el.as_element():
        return el.as_element()
    return None


def run(args: dict) -> dict:
    session_id = (args.get("session_id") or "").strip()
    action     = (args.get("action") or "").strip().lower()
    target     = (args.get("target") or "").strip()
    value      = (args.get("value") or "").strip()

    if not session_id:
        return {"error": "session_id required"}
    if action not in VALID_ACTIONS:
        return {"error": f"action must be one of {sorted(VALID_ACTIONS)}"}

    sess = _SESSIONS.get(session_id)
    if not sess:
        return {"error": f"session not found: {session_id} — call browser_open first"}

    human_pace = _get_human_pace(session_id)
    page       = sess["page"]
    prev_url   = page.url

    try:
        if action == "wait":
            ms = int(value) if value.isdigit() else 1000
            if human_pace:
                time.sleep(_jitter(ms))
            else:
                page.wait_for_timeout(ms)

        elif action == "scroll":
            direction = value.lower() if value else "down"
            if direction not in SCROLL_DIRS:
                direction = "down"
            scripts = {
                "down":   "window.scrollBy(0, window.innerHeight * 0.8)",
                "up":     "window.scrollBy(0, -window.innerHeight * 0.8)",
                "top":    "window.scrollTo(0, 0)",
                "bottom": "window.scrollTo(0, document.body.scrollHeight)",
            }
            page.evaluate(scripts[direction])
            if human_pace:
                _human_sleep(600)

        elif action == "key":
            key_name = value or target or "Enter"
            page.keyboard.press(key_name)
            if human_pace:
                _human_sleep(400)

        elif action in ("click", "hover", "clear", "type", "select"):
            el = _find_element(page, target)
            if el is None:
                return {
                    "success":     False,
                    "new_url":     page.url,
                    "dom_changed": False,
                    "error":       f"element not found: {target}",
                }

            if action == "click":
                if human_pace:
                    el.hover()
                    _human_sleep(300)
                el.click()
                if human_pace:
                    _human_sleep(800)

            elif action == "hover":
                el.hover()
                if human_pace:
                    _human_sleep(500)

            elif action == "clear":
                el.fill("")
                if human_pace:
                    _human_sleep(200)

            elif action == "type":
                if human_pace:
                    el.click()
                    _human_sleep(200)
                    for char in value:
                        el.type(char, delay=random.randint(60, 160))
                    _human_sleep(300)
                else:
                    el.fill(value)

            elif action == "select":
                el.select_option(value=value)
                if human_pace:
                    _human_sleep(500)

        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

        new_url = page.url
        _update_session(session_id, new_url)

        return {
            "success":     True,
            "new_url":     new_url,
            "dom_changed": new_url != prev_url,
        }

    except Exception as e:
        return {
            "success":     False,
            "new_url":     page.url,
            "dom_changed": False,
            "error":       str(e)[:200],
        }
