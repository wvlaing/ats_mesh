"""Open a URL in a real browser and save every useful network request as JSON.
Edit the settings below, then run:  python scripts/capture.py"""

import json
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

# ---- settings ----
URL = "https://careers.cisco.com/global/en/search-results"
HEADED = False
INTERACTIVE = False  # True = Press Enter to exit
KEEP_ALL = False  # True = turn off the noise filter
WAIT = 3  # extra seconds to wait after the page loads
OUT = Path.home() / "Desktop" / "captures"

SKIP_EXT = {
    ".ico",
    ".css",
    ".gif",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".webp",
    ".avif",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".mp4",
    ".webm",
    ".mp3",
    ".map",
}
SKIP_TYPES = {"image", "stylesheet", "font", "media", "manifest", "texttrack", "ping"}
SKIP_HOSTS = (
    "google-analytics",
    "googletagmanager",
    "doubleclick",
    "facebook.",
    "hotjar",
    "segment.",
    "sentry.",
    "datadoghq",
    "newrelic",
    "nr-data",
    "clarity.ms",
    "optimizely",
    "onetrust",
    "cookielaw",
    "trustarc",
    "linkedin.com/px",
    "fullstory",
    "mixpanel",
    "amplitude",
    "intercom",
    "hubspot",
    "adobedtm",
    "demdex",
    "omtrdc",
    "bing.com",
    "tiktok",
    "snap.licdn",
)
KEEP_TYPES = {"xhr", "fetch", "document"}  # scripts are dropped unless --all


def noisy(url, rtype):
    u = urlparse(url)
    if rtype in SKIP_TYPES or Path(u.path).suffix.lower() in SKIP_EXT:
        return True
    if any(h in url for h in SKIP_HOSTS):
        return True
    return rtype not in KEEP_TYPES


def devtools_name(url):
    """The name column in F12: last path segment + query (host if the path is empty)."""
    p = urlparse(url)
    name = p.path.rstrip("/").rsplit("/", 1)[-1] or p.hostname
    if p.query:
        name += "?" + p.query
    return re.sub(r"[/:\x00]", "_", name)[:120]


def main():
    out = OUT / f"{urlparse(URL).hostname}_{time.strftime('%H%M%S')}"
    out.mkdir(parents=True)

    saved = []  # (devtools name, data) in request order

    def on_response(r):
        req = r.request
        if not KEEP_ALL and noisy(req.url, req.resource_type):
            return
        try:
            raw = r.body()
        except Exception:  # redirects / aborted requests have no body
            raw = b""
        text = raw.decode("utf-8", errors="replace")
        ctype = r.headers.get("content-type", "")
        try:
            body = json.loads(text) if "json" in ctype or text[:1] in "{[" else text
        except ValueError:
            body = text
        post = req.post_data
        try:
            post = json.loads(post) if post else post
        except ValueError:
            pass
        saved.append(
            (
                devtools_name(req.url),
                {
                    "url": req.url,
                    "method": req.method,
                    "type": req.resource_type,
                    "request_headers": req.headers,
                    "post_data": post,
                    "status": r.status,
                    "redirect_to": r.headers.get("location"),
                    "response_headers": r.headers,
                    "size": len(raw),
                    "body": body,
                },
            )
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not HEADED)
        page = browser.new_context().new_page()
        page.on("response", on_response)
        page.goto(URL, wait_until="networkidle")
        page.mouse.wheel(0, 4000)  # trigger lazy loading
        page.wait_for_timeout(WAIT * 1000)
        if INTERACTIVE:
            input("Click around in the browser, then press Enter here to finish... ")
        browser.close()

    # Name files exactly like F12; only repeated names get " (1)", " (2)", ...
    totals = Counter(n for n, _ in saved)
    seen = Counter()
    lines = []
    for name, data in saved:
        seen[name] += 1
        fname = f"{name} ({seen[name]})" if totals[name] > 1 else name
        (out / f"{fname}.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False)
        )
        lines.append(
            f"{fname}.json  {data['status']}  {data['size']}B  {data['url'][:120]}"
        )
    (out / "_index.md").write_text("\n".join(lines))  # request order
    print("\n".join(lines))
    print(f"\n{len(saved)} requests saved to {out}/")


if __name__ == "__main__":
    main()
