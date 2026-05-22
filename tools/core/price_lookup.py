"""price_lookup: Search eBay for item pricing.
Primary: eBay Finding API — set EBAY_APP_ID env var (free at developer.ebay.com).
Fallback: Bing Shopping scrape (no key needed).
"""
import html as htmlmod
import json
import os
import re
import requests

_EBAY_APP_ID = os.environ.get("EBAY_APP_ID", "")
_EBAY_FIND   = "https://svcs.ebay.com/services/search/FindingService/v1"

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"),
    "Accept-Language": "en-US,en;q=0.9",
}


def run(args: dict) -> dict:
    query = args.get("query", "").strip()
    if not query:
        return {"error": "query is required"}
    mode = args.get("mode", "sold").lower()  # sold | active

    listings = _ebay_api(query, mode) if _EBAY_APP_ID else []
    if not listings:
        listings = _bing_shopping(query)

    if not listings:
        tip = "" if _EBAY_APP_ID else " Tip: set EBAY_APP_ID env var (free at developer.ebay.com)."
        return {"error": f"no price data found.{tip}"}

    prices  = [r["price"] for r in listings if r.get("price")]
    summary = {}
    if prices:
        summary = {
            "low":   min(prices),
            "high":  max(prices),
            "avg":   round(sum(prices) / len(prices), 2),
            "count": len(prices),
        }

    return {"query": query, "mode": mode, "summary": summary, "listings": listings[:10]}


def _ebay_api(query: str, mode: str) -> list:
    op = "findCompletedItems" if mode == "sold" else "findItemsByKeywords"
    params = {
        "OPERATION-NAME":                 op,
        "SERVICE-VERSION":                "1.0.0",
        "SECURITY-APPNAME":               _EBAY_APP_ID,
        "RESPONSE-DATA-FORMAT":           "JSON",
        "keywords":                       query,
        "paginationInput.entriesPerPage": "20",
    }
    if mode == "sold":
        params["itemFilter(0).name"]  = "SoldItemsOnly"
        params["itemFilter(0).value"] = "true"
    try:
        r    = requests.get(_EBAY_FIND, params=params, timeout=15)
        data = r.json()
    except Exception:
        return []

    key   = "findCompletedItemsResponse" if mode == "sold" else "findItemsByKeywordsResponse"
    items = (data.get(key, [{}])[0]
                 .get("searchResult", [{}])[0]
                 .get("item", []))
    out = []
    for item in items:
        try:
            title = item["title"][0]
            price = float(item["sellingStatus"][0]["currentPrice"][0]["__value__"])
            url   = item["viewItemURL"][0]
            date  = (item.get("listingInfo", [{}])[0].get("endTime", [""])[0] or "")[:10]
            out.append({"title": title, "price": price, "url": url, "date": date})
        except (KeyError, IndexError, ValueError):
            continue
    return out


def _bing_shopping(query: str) -> list:
    try:
        r   = requests.get("https://www.bing.com/shop",
                           params={"q": query}, headers=_HEADERS, timeout=15)
        txt = r.text
    except Exception:
        return []

    out = []
    for raw in re.findall(r'data-m="(\{[^"]+\})"', txt):
        try:
            d = json.loads(htmlmod.unescape(raw))
        except Exception:
            continue
        price_str = str(d.get("price", "") or "")
        try:
            price = float(re.sub(r"[^\d.]", "", price_str))
        except (ValueError, TypeError):
            continue
        title = str(d.get("title", d.get("t", "")) or "")[:100]
        url   = str(d.get("url",   d.get("u", "")) or "")
        if title and price:
            out.append({"title": title, "price": price, "url": url})
        if len(out) >= 20:
            break
    return out
