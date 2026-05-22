# Browser Tools (Playwright)

ELDON includes six browser tools backed by Playwright Chromium. They follow a DOM-first approach — the model reads the page as structured data, not as pixels.

## Install

```bash
pip install playwright
python -m playwright install chromium
```

## Tools

### browser_open(url, human_pace?)
Opens a Chromium browser session. Returns a `session_id` that must be passed to every subsequent browser call for this session. `human_pace` adds a millisecond delay multiplier between actions (0 = fast, 1200 = roughly human speed for social media workflows).

### browser_nav(session_id, url)
Navigates the existing session to a new URL. Does not open a new window.

### browser_dom(session_id)
Extracts a semantic snapshot of the current page: interactive elements (buttons, inputs, links, selects), visible text, forms, and alert dialogs. Returns structured data the model can act on directly. If the page cannot be semantically parsed (heavy canvas, dynamic rendering), returns `vl_needed: true`.

### browser_act(session_id, action, target, text?, value?)
Performs one action on an element identified by its ID from `browser_dom` or a CSS selector.

Actions: `click`, `type`, `select`, `scroll`, `wait`, `key`, `hover`, `clear`

### browser_shot(session_id)
Takes a screenshot. **Use only when `browser_dom` returns `vl_needed: true`.** This requires a vision-capable model. If running a text-only model, `browser_shot` will return image data the model cannot interpret.

### browser_close(session_id)
Closes the session and releases all Playwright resources.

## Operating principle

The model sees the browser through the DOM, not pixels. `browser_dom` first, `browser_act` on the returned element IDs. `browser_shot` is a last resort for pages that don't expose a usable DOM.

Session IDs are UUIDs stored in `runtime/browser_sessions/`. They persist across tool calls within the same session. Always call `browser_close` when done — open sessions hold browser processes.

## Human pace

For workflows that interact with social platforms or rate-limited sites, pass `human_pace=1200` to `browser_open`. This adds randomized delays between actions to avoid triggering bot detection. The scheduler is the right tool for timed social workflows — do not implement custom sleep loops inside a prompt.
