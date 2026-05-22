"""web_fetch: GET a URL, strip HTML, return up to 8KB of text."""
import re

import requests


def run(args: dict) -> dict:
    url = args.get("url", "")
    if not url.startswith(("http://", "https://")):
        return {"error": "url must be http(s)"}
    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        r.raise_for_status()
    except Exception as e:
        return {"error": str(e)[:120]}
    text = re.sub(r"<script.*?</script>", "", r.text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>",  "", text,   flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return {"url": url, "text": text[:8000], "bytes": len(text)}
