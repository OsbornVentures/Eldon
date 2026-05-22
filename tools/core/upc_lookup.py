"""upc_lookup: Product lookup by UPC/EAN barcode.
Primary: UPCitemdb trial (free, 100 lookups/day, no signup required).
         Set UPCITEMDB_KEY env var for paid tier (unlimited).
Food fallback: Open Food Facts (free, open data, no key needed).
"""
import os
import re
import requests

_TRIAL_URL     = "https://api.upcitemdb.com/prod/trial/lookup"
_PAID_URL      = "https://api.upcitemdb.com/prod/v1/lookup"
_OFF_URL       = "https://world.openfoodfacts.org/api/v2/product/{upc}.json"
_UPCITEMDB_KEY = os.environ.get("UPCITEMDB_KEY", "")

_HEADERS = {"Accept": "application/json", "User-Agent": "GemmaTools/1.0"}


def run(args: dict) -> dict:
    upc = re.sub(r"[^0-9]", "", args.get("upc", "").strip())
    if not upc:
        return {"error": "upc is required (digits only, e.g. 012345678905)"}

    result = _upcitemdb(upc)
    if "error" in result and len(upc) in (8, 13):
        food = _open_food_facts(upc)
        if "error" not in food:
            return food
    return result


def _upcitemdb(upc: str) -> dict:
    url  = _PAID_URL if _UPCITEMDB_KEY else _TRIAL_URL
    hdrs = {**_HEADERS, **({"user_key": _UPCITEMDB_KEY} if _UPCITEMDB_KEY else {})}
    try:
        r = requests.get(url, params={"upc": upc}, headers=hdrs, timeout=10)
    except Exception as e:
        return {"error": str(e)}

    if r.status_code == 429:
        return {"error": "upcitemdb rate limit reached (100/day on trial). "
                         "Set UPCITEMDB_KEY env var for unlimited access."}
    if r.status_code != 200:
        return {"error": f"upcitemdb HTTP {r.status_code}"}

    try:
        data = r.json()
    except Exception:
        return {"error": "invalid JSON from upcitemdb"}

    items = data.get("items", [])
    if not items:
        return {"error": f"no product found for UPC {upc}"}

    item = items[0]
    return {
        "upc":         upc,
        "title":       item.get("title", ""),
        "description": (item.get("description") or "")[:300],
        "brand":       item.get("brand", ""),
        "category":    item.get("category", ""),
        "images":      item.get("images", [])[:3],
        "offers":      [
            {"merchant": o.get("merchant", ""), "price": o.get("price"),
             "condition": o.get("condition", "")}
            for o in item.get("offers", [])[:5]
        ],
        "source": "upcitemdb",
    }


def _open_food_facts(upc: str) -> dict:
    try:
        r    = requests.get(_OFF_URL.format(upc=upc), headers=_HEADERS, timeout=10)
        data = r.json()
    except Exception as e:
        return {"error": str(e)}

    if data.get("status") != 1:
        return {"error": f"not found in Open Food Facts (upc={upc})"}

    p    = data.get("product", {})
    cats = p.get("categories", "")
    return {
        "upc":         upc,
        "title":       p.get("product_name", ""),
        "brand":       p.get("brands", ""),
        "category":    cats.split(",")[0].strip() if cats else "",
        "ingredients": (p.get("ingredients_text") or "")[:300],
        "nutriscore":  (p.get("nutriscore_grade") or "").upper(),
        "labels":      p.get("labels", ""),
        "image":       p.get("image_url", ""),
        "source":      "openfoodfacts",
    }
