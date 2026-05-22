"""http_call: GET or POST a URL with optional JSON body. For API calls."""
import requests

MAX_BODY = 8000

def run(args: dict) -> dict:
    url = args.get("url", "").strip()
    method = args.get("method", "GET").upper()
    body = args.get("body")
    headers = args.get("headers") or {}

    if not url:
        return {"error": "url required"}
    if not url.startswith(("http://", "https://")):
        return {"error": "url must start with http:// or https://"}

    try:
        r = requests.request(
            method, url,
            json=body if isinstance(body, dict) else None,
            data=body if isinstance(body, str) else None,
            headers=headers, timeout=15, allow_redirects=True,
        )
        ct = r.headers.get("content-type", "")
        try:
            data = r.json() if "json" in ct else r.text[:MAX_BODY]
        except Exception:
            data = r.text[:MAX_BODY]
        return {"status": r.status_code, "data": data}
    except Exception as e:
        return {"error": str(e)[:200]}
