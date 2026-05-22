"""web_search: Bing primary (web/news/images/videos), YouTube for video, DDG fallback.
Google HTML is consent-walled â€” Bing is primary for everything except videos (YouTube).
Returns structured dicts: title, url, snippet, site, type, [thumb, img, date, content].
Opens Edge visually for each query.

type="deep"  : search + fetch page content from top 5 results (~4KB each, fits 32k context).
type="web"   : standard web search.  type="news": news.  type="images": images.

Optional Google Custom Search (100 free/day):
  Set env vars GOOGLE_CSE_KEY (API key) and GOOGLE_CSE_CX (Search Engine ID).
  Get key: console.cloud.google.com â†’ Custom Search JSON API
  Get CX:  programmablesearchengine.google.com
"""
import base64
import html as htmlmod
import json
import os
import re
import subprocess
import time
import urllib.parse

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0")
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
MAX         = 7
_DEEP_CHARS = 4000   # chars of page text to fetch per result in deep mode
_GOOGLE_KEY = os.environ.get("GOOGLE_CSE_KEY", "")
_GOOGLE_CX  = os.environ.get("GOOGLE_CSE_CX", "")


def run(args: dict) -> dict:
    q = args.get("query", "").strip()
    t = args.get("type", "web").lower()
    if not q:
        return {"error": "empty query"}

    # Open Edge visually (background, no wait)
    try:
        vis = {
            "videos": f"https://www.youtube.com/results?search_query={urllib.parse.quote(q)}",
            "images": f"https://www.bing.com/images/search?q={urllib.parse.quote(q)}",
            "news":   f"https://www.bing.com/news/search?q={urllib.parse.quote(q)}",
            "deep":   f"https://www.bing.com/search?q={urllib.parse.quote(q)}",
        }.get(t, f"https://www.bing.com/search?q={urllib.parse.quote(q)}")
        subprocess.Popen(
            [os.environ.get("ELDON_BROWSER_PATH", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"), vis],
            creationflags=0x00000008,
        )
        time.sleep(0.5)
    except Exception:
        pass

    results  = []
    _google  = [_google_cse] if _GOOGLE_KEY and _GOOGLE_CX else []

    if t == "videos":
        for fn in [_youtube, _bing_videos]:
            try:
                results = fn(q)
                if results: break
            except Exception:
                continue
    elif t == "images":
        for fn in [_bing_images, _ddg_images]:
            try:
                results = fn(q)
                if results: break
            except Exception:
                continue
    elif t == "news":
        for fn in [_google_news_rss, _ddg]:
            try:
                results = fn(q)
                if results: break
            except Exception:
                continue
    elif t == "deep":
        # Search then fetch full page content from top results
        for fn in _google + [_bing_web, _ddg]:
            try:
                results = fn(q)
                if results: break
            except Exception:
                continue
        for r in results[:5]:
            r["content"] = _fetch_page_text(r["url"], _DEEP_CHARS)
    else:  # web â€” use Google CSE if configured, else Bing
        for fn in _google + [_bing_web, _ddg]:
            try:
                results = fn(q)
                if results: break
            except Exception:
                continue

    results = results[:MAX]
    return {"results": results, "count": len(results), "query": q, "type": t}


# â”€â”€ Bing URL decoder â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _decode_bing(href: str) -> str:
    """Decode Bing ck/a redirect: u=a1<base64url> â†’ real URL."""
    if not href.startswith("https://www.bing.com/ck/"):
        return href
    m = re.search(r'[?&]u=a1([A-Za-z0-9_\-]+)', href)
    if not m:
        return href
    try:
        padded = m.group(1) + "=="
        decoded = base64.urlsafe_b64decode(padded).decode("utf-8", errors="ignore")
        if decoded.startswith("http"):
            return decoded
    except Exception:
        pass
    return href


def _clean(s: str) -> str:
    return htmlmod.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _domain(url: str) -> str:
    try:
        return re.sub(r"^www\.", "", urllib.parse.urlparse(url).netloc)
    except Exception:
        return ""


def _fetch_page_text(url: str, max_chars: int = 4000) -> str:
    """Fetch a URL, strip HTML/scripts, return cleaned text up to max_chars."""
    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        text = r.text
        text = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', ' ', text, flags=re.S | re.I)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = htmlmod.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_chars]
    except Exception:
        return ""


def _google_cse(q: str) -> list:
    """Google Custom Search JSON API â€” 100 free queries/day. Needs GOOGLE_CSE_KEY + GOOGLE_CSE_CX."""
    try:
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": _GOOGLE_KEY, "cx": _GOOGLE_CX, "q": q, "num": MAX},
            timeout=10,
        )
        data = r.json()
    except Exception:
        return []
    out = []
    for item in data.get("items", []):
        out.append({
            "title":   item.get("title", ""),
            "url":     item.get("link", ""),
            "snippet": (item.get("snippet") or "")[:200],
            "site":    _domain(item.get("link", "")),
            "type":    "web",
        })
    return out


# â”€â”€ Bing web â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _bing_web(q: str) -> list:
    r = requests.get("https://www.bing.com/search", params={"q": q},
                     headers=HEADERS, timeout=15)
    txt = r.text
    out = []

    # Each result is in <li class="b_algo ...">...</li>
    # h2 > a has the link (may be bing redirect, decode via u=a1...)
    for block in re.findall(r'<li[^>]+class="b_algo[^"]*"(.*?)</li>', txt, re.S):
        # h2 link
        m_h2 = re.search(r'<h2[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m_h2:
            continue
        raw_href = htmlmod.unescape(m_h2.group(1))
        url = _decode_bing(raw_href)
        if not url.startswith("http") or "bing.com" in url:
            continue
        title = _clean(m_h2.group(2))
        if not title or len(title) < 4:
            continue

        # Snippet: try b_caption p, then any p
        snip = ""
        for pat in [r'class="[^"]*b_caption[^"]*"[^>]*>.*?<p[^>]*>(.*?)</p>',
                    r'<p\b[^>]*>(.*?)</p>']:
            sm = re.search(pat, block, re.S)
            if sm:
                snip = _clean(sm.group(1))[:200]
                if snip: break

        # Cite (display URL fallback)
        cite = ""
        cm = re.search(r'<cite[^>]*>(.*?)</cite>', block, re.S)
        if cm:
            cite = _clean(cm.group(1))

        out.append({"title": title, "url": url, "snippet": snip,
                    "site": _domain(url) or cite, "type": "web"})
        if len(out) >= MAX:
            break
    return out


# â”€â”€ Bing news â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _google_news_rss(q: str) -> list:
    """Google News RSS â€” most reliable news source, no JS required."""
    r = requests.get(
        "https://news.google.com/rss/search",
        params={"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"},
        headers=HEADERS, timeout=15,
    )
    out = []
    for item in re.findall(r"<item>(.*?)</item>", r.text, re.S):
        t_m  = re.search(r"<title>(.*?)</title>", item, re.S)
        l_m  = re.search(r"<link>(.*?)</link>", item, re.S)
        d_m  = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
        s_m  = re.search(r"<source[^>]*>(.*?)</source>", item, re.S)
        if not t_m or not l_m: continue
        title = _clean(t_m.group(1))
        url   = l_m.group(1).strip()
        date  = d_m.group(1).strip()[:22] if d_m else ""
        src   = _clean(s_m.group(1)) if s_m else ""
        snip  = " Â· ".join(x for x in [src, date] if x)
        out.append({"title": title, "url": url, "snippet": snip,
                    "site": src, "type": "news"})
        if len(out) >= MAX: break
    return out


# â”€â”€ Bing images â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _bing_images(q: str) -> list:
    # Use Bing's async images endpoint â€” returns clean HTML fragment with thumbnails
    r = requests.get("https://www.bing.com/images/async",
                     params={"q": q, "first": 1, "count": MAX, "adlt": "Moderate"},
                     headers=HEADERS, timeout=15)
    txt = r.text
    out = []

    # Each result: <img alt="LABEL" ... data-src="THUMB_URL" ...>
    # Parent <a href="SOURCE_PAGE"> wraps each image
    for m in re.finditer(
        r'<a[^>]+href="([^"]+)"[^>]*>[\s\S]{0,200}?'
        r'<img[^>]+(?:alt="([^"]*)"[^>]+data-src|data-src="([^"]+)"[^>]+alt="([^"]*)")'
        r'="([^"]+)"',
        txt, re.S
    ):
        # This pattern is complex â€” use simpler paired approach below
        pass

    # Simpler: pair data-src thumbnails with nearby alt text and parent hrefs
    thumb_positions = [(m.start(), m.group(1), m.group(2))
                       for m in re.finditer(r'data-src="(https?://[^"]+)"[^>]*alt="([^"]*)"', txt)
                       if not m.group(1).startswith("https://r.bing")]

    if not thumb_positions:
        # alt before data-src
        thumb_positions = [(m.start(), m.group(2), m.group(1))
                           for m in re.finditer(r'alt="([^"]*)"[^>]*data-src="(https?://[^"]+)"', txt)
                           if not m.group(2).startswith("https://r.bing")]

    for pos, thumb, label in thumb_positions:
        if not label or not thumb: continue
        # Find nearest preceding <a href> for source page
        purl_m = re.search(r'<a[^>]+href="(https?://[^"]+)"', txt[max(0, pos-300):pos])
        purl = purl_m.group(1) if purl_m else thumb
        if "bing.com" in purl: purl = thumb
        out.append({"title": label[:80], "url": htmlmod.unescape(purl),
                    "thumb": htmlmod.unescape(thumb), "snippet": "",
                    "site": _domain(purl), "type": "image"})
        if len(out) >= MAX:
            break
    return out


def _ddg_images(q: str) -> list:
    """DuckDuckGo image search via their JSON API."""
    # DDG images endpoint
    token_r = requests.get("https://duckduckgo.com/", params={"q": q}, headers=HEADERS, timeout=10)
    vqd_m = re.search(r'vqd="?([^"&]+)"?', token_r.text)
    if not vqd_m:
        return []
    vqd = vqd_m.group(1)
    api_r = requests.get(
        "https://duckduckgo.com/i.js",
        params={"q": q, "vqd": vqd, "f": ",,,,,", "p": "1"},
        headers={**HEADERS, "Referer": "https://duckduckgo.com/"},
        timeout=10,
    )
    try:
        data = api_r.json()
    except Exception:
        return []
    out = []
    for item in data.get("results", []):
        out.append({"title": item.get("title", q), "url": item.get("url", ""),
                    "img": item.get("image", ""), "thumb": item.get("thumbnail", ""),
                    "snippet": f"{item.get('width','?')}Ã—{item.get('height','?')}",
                    "site": item.get("source", ""), "type": "image"})
        if len(out) >= MAX: break
    return out


# â”€â”€ Bing videos â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _bing_videos(q: str) -> list:
    r = requests.get("https://www.bing.com/videos/search", params={"q": q},
                     headers=HEADERS, timeout=15)
    out = []
    for raw in re.findall(r'data-m="(\{[^"]+\})"', r.text):
        try:
            d = json.loads(htmlmod.unescape(raw))
        except Exception:
            continue
        purl  = d.get("purl", "")
        title = d.get("tit", "")
        if not purl or not title:
            continue
        snip = " Â· ".join(x for x in [d.get("pubDate",""), d.get("cname",""), d.get("dur","")] if x)
        out.append({"title": title, "url": purl,
                    "snippet": snip, "thumb": d.get("turl",""),
                    "site": _domain(purl), "type": "video"})
        if len(out) >= MAX:
            break
    return out


# â”€â”€ YouTube â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _youtube(q: str) -> list:
    r = requests.get("https://www.youtube.com/results",
                     params={"search_query": q}, headers=HEADERS, timeout=15)
    out = []
    # Extract ytInitialData JSON
    m = re.search(r"ytInitialData\s*=\s*(\{.+?\});\s*(?:var |</script)", r.text, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            contents = (data.get("contents", {})
                           .get("twoColumnSearchResultsRenderer", {})
                           .get("primaryContents", {})
                           .get("sectionListRenderer", {})
                           .get("contents", [{}])[0]
                           .get("itemSectionRenderer", {})
                           .get("contents", []))
            for item in contents:
                vr = item.get("videoRenderer", {})
                if not vr:
                    continue
                vid   = vr.get("videoId", "")
                title = (vr.get("title", {}).get("runs", [{}])[0].get("text", ""))
                chan   = ((vr.get("ownerText") or vr.get("longBylineText") or {})
                           .get("runs", [{}])[0].get("text", ""))
                dur   = (vr.get("lengthText", {}).get("simpleText", "") or
                         vr.get("lengthText", {}).get("runs", [{}])[0].get("text", ""))
                views = (vr.get("viewCountText", {}).get("simpleText", "") or
                         vr.get("viewCountText", {}).get("runs", [{}])[0].get("text", ""))
                snip  = " Â· ".join(x for x in [chan, dur, views] if x)
                out.append({"title": title,
                            "url": f"https://www.youtube.com/watch?v={vid}",
                            "snippet": snip,
                            "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                            "site": "youtube.com", "type": "video"})
                if len(out) >= MAX:
                    break
        except Exception:
            pass

    # Fallback: extract video IDs from raw HTML
    if not out:
        for vid in dict.fromkeys(re.findall(r'watch\?v=([A-Za-z0-9_-]{11})', r.text)):
            out.append({"title": vid, "url": f"https://www.youtube.com/watch?v={vid}",
                        "snippet": "", "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                        "site": "youtube.com", "type": "video"})
            if len(out) >= MAX:
                break
    return out


# â”€â”€ DuckDuckGo web fallback â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _ddg(q: str) -> list:
    r = requests.post("https://html.duckduckgo.com/html/",
                      data={"q": q}, headers=HEADERS, timeout=15)
    out = []
    for m in re.finditer(
        r'class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'class="result__snippet"[^>]*>(.*?)</a>',
        r.text, re.S
    ):
        url   = urllib.parse.unquote(m.group(1).split("uddg=")[-1])
        title = _clean(m.group(2))
        snip  = _clean(m.group(3))[:200]
        out.append({"title": title, "url": url, "snippet": snip,
                    "site": _domain(url), "type": "web"})
        if len(out) >= MAX:
            break
    return out

