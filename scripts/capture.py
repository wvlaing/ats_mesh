"""Open a URL in a real browser and save every useful network request to a folder.

    python sc https://careers.example.com/jobs
    python scripts/capture.py URL --headed --interactive   # you click around, Enter to finish
    python scripts/capture.py URL --all                    # disable the noise filter

Output (captures/<host>_<time>/):
    index.md        one line per request - read this first
    index.json      same, machine readable
    001_POST_api_jobs.json   request + response for each kept request
"""

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

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


def slug(url):
    p = urlparse(url)
    return re.sub(r"[^a-zA-Z0-9]+", "_", (p.path.strip("/") or p.netloc))[:50].strip(
        "_"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", default=str(Path.home() / "Desktop" / "captures"))
    ap.add_argument("--all", action="store_true", help="keep everything (no filtering)")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument(
        "--interactive",
        action="store_true",
        help="wait for Enter so you can click around",
    )
    ap.add_argument(
        "--wait", type=float, default=3, help="extra seconds to wait after load"
    )
    a = ap.parse_args()

    out = Path(a.out) / f"{urlparse(a.url).hostname}_{time.strftime('%H%M%S')}"
    out.mkdir(parents=True)
    rows = []

    def on_response(r):
        req = r.request
        if not a.all and noisy(req.url, req.resource_type):
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
        n = len(rows) + 1
        name = f"{n:03d}_{req.method}_{slug(req.url)}.json"
        post = req.post_data
        try:
            post = json.loads(post) if post else post
        except ValueError:
            pass
        (out / name).write_text(
            json.dumps(
                {
                    "url": req.url,
                    "method": req.method,
                    "type": req.resource_type,
                    "request_headers": req.headers,
                    "post_data": post,
                    "status": r.status,
                    "response_headers": r.headers,
                    "body": body,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        rows.append(
            {
                "file": name,
                "method": req.method,
                "status": r.status,
                "type": req.resource_type,
                "content_type": ctype.split(";")[0],
                "size": len(raw),
                "url": req.url,
            }
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not a.headed)
        page = browser.new_context().new_page()
        page.on("response", on_response)
        page.goto(a.url, wait_until="networkidle")
        page.mouse.wheel(0, 4000)  # trigger lazy loading
        page.wait_for_timeout(a.wait * 1000)
        if a.interactive:
            input("Click around in the browser, then press Enter here to finish... ")
        browser.close()

    # JSON/API responses first, biggest first - those are usually the interesting ones
    rows.sort(key=lambda r: ("json" not in r["content_type"], -r["size"]))
    (out / "index.json").write_text(json.dumps(rows, indent=2))
    lines = [
        f"{r['file']}  {r['status']}  {r['content_type']:<22} {r['size']:>8}B  {r['url'][:110]}"
        for r in rows
    ]
    (out / "index.md").write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"\n{len(rows)} requests saved to {out}/")


if __name__ == "__main__":
    main()
