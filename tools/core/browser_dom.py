"""browser_dom: extract semantic DOM snapshot from an open browser session.
DOM-first architecture: model sees structured data, not pixels.
vl_needed=True only when DOM yields insufficient content (canvas, image-only UI).
"""
import hashlib
import re
from tools.core.browser_open import _SESSIONS

TOOL_META = {
    "summary": "Semantic DOM snapshot: interactive elements + visible text. Primary browser perception tool.",
    "args":    '{"session_id": str, "selector"?: str, "depth"?: int}',
    "returns": '{"url": str, "title": str, "interactive": list, "text_nodes": list, "forms": list, "alerts": str, "vl_needed": bool}',
    "tags":    ["browser", "playwright"],
    "notes":   "Use this before browser_act. Only call browser_shot if vl_needed=True.",
}

_JS_EXTRACT = """
() => {
  const TAGS = 'a,button,input,select,textarea,[role=button],[role=link],[role=menuitem],[role=tab],[tabindex]';
  const items = [];
  document.querySelectorAll(TAGS).forEach(el => {
    const rect = el.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) return;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return;
    if (el.getAttribute('aria-hidden') === 'true') return;

    const text = (
      el.value || el.innerText || el.textContent ||
      el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
      el.getAttribute('title') || el.getAttribute('alt') || ''
    ).trim().slice(0, 120);

    const tag  = el.tagName.toLowerCase();
    const type = el.type || '';
    const href = el.href || el.getAttribute('href') || '';
    const role = el.getAttribute('role') || tag;
    const name = el.name || el.id || '';

    const hashKey = tag + ':' + text.slice(0,30) + ':' + name;
    const id      = tag + '-' + Math.abs(hashKey.split('').reduce((a,c) => (a<<5)-a+c.charCodeAt(0),0)).toString(36).slice(0,6);

    items.push({id, tag, text, type, href: href.slice(0,200), role, name, visible: true});
  });
  return items;
}
"""

_JS_TEXT = """
() => {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const texts = new Set();
  let node;
  while ((node = walker.nextNode())) {
    const t = node.textContent.replace(/\\s+/g, ' ').trim();
    if (t.length > 10) texts.add(t.slice(0, 200));
    if (texts.size >= 150) break;
  }
  return [...texts];
}
"""

_JS_FORMS = """
() => {
  return [...document.querySelectorAll('form')].map((form, fi) => {
    const fields = [...form.querySelectorAll('input,select,textarea')].map(f => ({
      name:        f.name || f.id || '',
      type:        f.type || f.tagName.toLowerCase(),
      placeholder: f.placeholder || '',
      value:       (f.type === 'password' ? '***' : (f.value || '')).slice(0,60),
      required:    f.required,
    }));
    return {id: form.id || ('form-' + fi), action: form.action || '', fields};
  });
}
"""

_JS_ALERT = """
() => {
  const modal = document.querySelector('[role=dialog],[role=alertdialog],[aria-modal=true],.modal,.alert,.popup');
  return modal ? modal.innerText.trim().slice(0, 300) : '';
}
"""

_JS_VL_CHECK = """
() => {
  const canvases  = document.querySelectorAll('canvas').length;
  const imgs      = document.querySelectorAll('img').length;
  const textLen   = (document.body.innerText || '').trim().length;
  return {canvases, imgs, textLen};
}
"""


def run(args: dict) -> dict:
    session_id = (args.get("session_id") or "").strip()
    if not session_id:
        return {"error": "session_id required"}

    sess = _SESSIONS.get(session_id)
    if not sess:
        return {"error": f"session not found: {session_id} — call browser_open first"}

    try:
        page = sess["page"]

        interactive = page.evaluate(_JS_EXTRACT) or []
        text_nodes  = page.evaluate(_JS_TEXT) or []
        forms       = page.evaluate(_JS_FORMS) or []
        alert_text  = page.evaluate(_JS_ALERT) or ""
        vl_info     = page.evaluate(_JS_VL_CHECK) or {}

        text_total = sum(len(t) for t in text_nodes)
        vl_needed  = (
            vl_info.get("canvases", 0) > 2 or
            text_total < 100
        )

        deduped_text = list(dict.fromkeys(text_nodes))[:60]
        capped_text  = []
        budget = 3000
        for t in deduped_text:
            if budget <= 0:
                break
            capped_text.append(t)
            budget -= len(t)

        return {
            "url":         page.url,
            "title":       page.title(),
            "interactive": interactive[:80],
            "text_nodes":  capped_text,
            "forms":       forms[:10],
            "alerts":      alert_text,
            "vl_needed":   vl_needed,
        }
    except Exception as e:
        return {"error": str(e)[:200]}
