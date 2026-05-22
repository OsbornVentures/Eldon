#!/usr/bin/env python3
"""eBay listing tool — tries eBay Sell API first, falls back to Playwright DOM automation."""
import json
import os
import time
from pathlib import Path

TOOL_META = {
    "summary": "Create or draft an eBay listing. Uses eBay Sell API if EBAY_APP_ID is set; falls back to Playwright browser automation otherwise.",
    "args": {
        "title":       "Listing title (required)",
        "price":       "Buy-it-now price as a float (required)",
        "description": "Item description (required)",
        "condition":   "Condition: New | Used | Refurbished (default: Used)",
        "category":    "eBay category name or number hint (optional)",
        "quantity":    "Quantity available (default: 1)",
        "draft":       "If true, save as draft rather than publish (default: true)",
        "session_id":  "Existing browser session ID — reuse rather than opening a new one (optional)",
    },
    "returns": "status, listing_id or draft_url, method (api|browser), error if failed",
    "tags":    ["ebay", "ecommerce", "listing", "browser"],
    "cost":    "medium",
    "human_pace": True,
}

_MAX_BYTES = 3800
ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# eBay Sell API path (requires EBAY_APP_ID + EBAY_USER_TOKEN env vars)
# ---------------------------------------------------------------------------

def _try_api(args: dict) -> dict | None:
    """Return result dict on success, None if API unavailable or auth missing."""
    app_id    = os.environ.get("EBAY_APP_ID", "")
    user_token = os.environ.get("EBAY_USER_TOKEN", "")
    if not app_id or not user_token:
        return None

    try:
        import urllib.request, urllib.error

        # Create inventory item (simplified — requires full Sell API access)
        sku = f"sku-{int(time.time())}"
        payload = {
            "availability": {"shipToLocationAvailability": {"quantity": int(args.get("quantity", 1))}},
            "condition": args.get("condition", "USED_EXCELLENT").upper().replace(" ", "_"),
            "product": {
                "title": args["title"],
                "description": args.get("description", ""),
            },
        }
        url  = f"https://api.ebay.com/sell/inventory/v1/inventory_item/{sku}"
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(url, data=data, method="PUT")
        req.add_header("Authorization",  f"Bearer {user_token}")
        req.add_header("Content-Type",   "application/json")
        req.add_header("Content-Language", "en-US")
        req.add_header("X-EBAY-C-MARKETPLACE-ID", "EBAY_US")

        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 201, 204):
                return {"status": "ok", "listing_id": sku, "method": "api"}

    except Exception as e:
        return {"status": "error", "error": str(e)[:200], "method": "api"}

    return None


# ---------------------------------------------------------------------------
# Playwright browser fallback
# ---------------------------------------------------------------------------

def _browser_list(args: dict) -> dict:
    """Open eBay sell form via Playwright and fill in the listing details."""
    try:
        import sys
        sys.path.insert(0, str(ROOT))
        from tools.core import browser_open, browser_nav, browser_dom, browser_act, browser_close
    except ImportError as e:
        return {"status": "error", "error": f"playwright not installed: {e}", "method": "browser"}

    session_id = args.get("session_id", "")
    opened_here = False

    try:
        if not session_id:
            r = browser_open.run({"url": "https://www.ebay.com/sl/sell", "human_pace": 1200})
            if r.get("error"):
                return {"status": "error", "error": r["error"], "method": "browser"}
            session_id  = r["session_id"]
            opened_here = True
        else:
            browser_nav.run({"session_id": session_id, "url": "https://www.ebay.com/sl/sell"})

        time.sleep(1.5)

        dom = browser_dom.run({"session_id": session_id})
        if dom.get("vl_needed"):
            return {
                "status": "vl_needed",
                "session_id": session_id,
                "error": "eBay sell page requires VL — captcha or canvas detected",
                "method": "browser",
            }

        # Fill title
        title_el = _find_input(dom, "title")
        if title_el:
            browser_act.run({"session_id": session_id, "action": "click",  "target": title_el})
            browser_act.run({"session_id": session_id, "action": "type",   "target": title_el, "text": args["title"]})

        # Fill price
        price_el = _find_input(dom, "price")
        if price_el:
            browser_act.run({"session_id": session_id, "action": "click",  "target": price_el})
            browser_act.run({"session_id": session_id, "action": "type",   "target": price_el, "text": str(args.get("price", ""))})

        # Fill description
        desc_el = _find_input(dom, "description")
        if desc_el:
            browser_act.run({"session_id": session_id, "action": "click",  "target": desc_el})
            browser_act.run({"session_id": session_id, "action": "type",   "target": desc_el, "text": args.get("description", "")})

        current_url = dom.get("url", "https://www.ebay.com/sl/sell")

        if args.get("draft", True):
            return {
                "status": "draft",
                "draft_url": current_url,
                "session_id": session_id,
                "method": "browser",
                "note": "Form partially filled — review in browser before submitting",
            }

        # Submit
        submit_el = _find_button(dom, ("list", "post", "submit", "sell"))
        if submit_el:
            browser_act.run({"session_id": session_id, "action": "click", "target": submit_el})
            time.sleep(2)
            dom2 = browser_dom.run({"session_id": session_id})
            new_url = dom2.get("url", "")
            return {"status": "ok", "listing_url": new_url, "method": "browser"}

        return {
            "status": "partial",
            "session_id": session_id,
            "draft_url": current_url,
            "method": "browser",
            "note": "Could not locate submit button — inspect DOM and act manually",
        }

    except Exception as e:
        return {"status": "error", "error": str(e)[:200], "method": "browser"}

    finally:
        if opened_here and session_id and not args.get("draft", True):
            try:
                browser_close.run({"session_id": session_id})
            except Exception:
                pass


def _find_input(dom: dict, hint: str) -> str:
    """Find a form field whose name/placeholder contains hint."""
    for form in dom.get("forms", []):
        for field in form.get("fields", []):
            needle = hint.lower()
            for attr in ("name", "placeholder", "id", "label"):
                if needle in str(field.get(attr, "")).lower():
                    return field.get("id", "")
    # fallback: search interactive elements
    for el in dom.get("interactive", []):
        tag  = el.get("tag", "")
        text = (el.get("text", "") + el.get("name", "") + el.get("placeholder", "")).lower()
        if tag in ("input", "textarea") and hint.lower() in text:
            return el.get("id", "")
    return ""


def _find_button(dom: dict, keywords: tuple) -> str:
    for el in dom.get("interactive", []):
        if el.get("tag") in ("button", "input", "a"):
            text = el.get("text", "").lower()
            if any(kw in text for kw in keywords):
                return el.get("id", "")
    return ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(args: dict) -> dict:
    if not args.get("title"):
        return {"error": "title is required"}
    if args.get("price") is None:
        return {"error": "price is required"}

    # 1. Try API
    result = _try_api(args)
    if result is not None:
        return result

    # 2. Browser fallback
    return _browser_list(args)
