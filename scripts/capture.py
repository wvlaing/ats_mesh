"""Open a URL in a real browser and save every useful network request as JSON.
HTML fragments inside JSON responses are parsed into structured data.

Edit the settings below, then run:  python scripts/capture.py [optional_url]"""

import json
import re
import sys
import time
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

# ---- settings ----
URL = "https://www.kpmguscareers.com/wp-content/themes/understrap-child-main/page-templates/google/get-jobs.php?ajax=1&career-level-parents=&career-level=Early%20Career%7CAdministrative%2FTechnical%20Support%7CAssociate%7CSenior%20Associate%7CManager%7C&order=posted&spage=1&_=1791918048984"

HEADED = False
INTERACTIVE = False  # True = Press Enter to exit
KEEP_ALL = False  # True = turn off the noise filter
PARSE_HTML = True  # True = turn HTML strings inside bodies into structured data
KEEP_RAW_HTML = False  # True = also keep the raw HTML next to the parsed data
WAIT = 3  # extra seconds to wait after the page loads
NAV_TIMEOUT = 45  # seconds to wait for the page to go idle
MAX_BODY = 5_000_000  # bodies larger than this are not stored
OUT = Path.home() / "Desktop"

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
KEEP_TYPES = {"xhr", "fetch", "document"}  # scripts are dropped unless KEEP_ALL
REDACT_HEADERS = {"cookie", "set-cookie", "authorization", "proxy-authorization"}

HTML_RE = re.compile(r"<[a-zA-Z][^>]*>")


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
    name = p.path.rstrip("/").rsplit("/", 1)[-1] or p.hostname or "request"
    if p.query:
        name += "?" + p.query
    return re.sub(r"[/:\\\x00]", "_", name)[:120]


def clean_headers(headers):
    return {
        k: ("<redacted>" if k.lower() in REDACT_HEADERS else v)
        for k, v in headers.items()
    }


# ---- HTML to structured data ----
class _HtmlParser(HTMLParser):
    """Collects every <a> as {href, data-*, text: [...]} and all loose text lines."""

    SKIP = {"script", "style", "svg"}  # noqa: RUF012

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items, self.lines = [], []
        self.cur, self.skip = None, 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "a":
            keep = {k: v for k, v in attrs if k == "href" or k.startswith("data-")}
            self.cur = {**keep, "text": []}

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "a" and self.cur is not None:
            self.cur["text"] = list(
                dict.fromkeys(self.cur["text"])
            )  # dedupe, keep order
            self.items.append(self.cur)
            self.cur = None

    def handle_data(self, data):
        text = " ".join(data.split())
        if not text or self.skip:
            return
        self.lines.append(text)
        if self.cur is not None:
            self.cur["text"].append(text)


def parse_html(s):
    p = _HtmlParser()
    p.feed(s)
    p.close()
    if p.items:
        return p.items
    lines = list(dict.fromkeys(p.lines))
    return lines[0] if len(lines) == 1 else lines


def normalize(value):
    """Walk a decoded body. Parse HTML strings and JSON-in-strings recursively."""
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, str):
        s = value.strip()
        if s[:1] in "{[" and s[-1:] in "}]":
            try:
                return normalize(json.loads(s))
            except ValueError:
                pass
        if HTML_RE.search(s):
            parsed = parse_html(s)
            return {"parsed": parsed, "raw_html": value} if KEEP_RAW_HTML else parsed
    return value


def decode_body(raw, ctype):
    text = raw.decode("utf-8", errors="replace")
    stripped = text.lstrip()
    body = text
    if "json" in ctype or stripped[:1] in ("{", "["):
        try:
            body = json.loads(text)
        except ValueError:
            pass
    if PARSE_HTML:
        try:
            body = normalize(body)
        except Exception as e:  # never lose a capture over a parsing problem
            body = {"parse_error": str(e), "body": body}
    return body


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else URL
    out = OUT / f"{urlparse(url).hostname}_{time.strftime('%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)

    saved = []  # (devtools name, data) in response order

    def on_response(r):
        try:
            req = r.request
            if not KEEP_ALL and noisy(req.url, req.resource_type):
                return
            try:
                raw = r.body()
            except Exception:  # redirects / aborted requests have no body
                raw = b""
            ctype = r.headers.get("content-type", "")
            if len(raw) > MAX_BODY:
                body = f"<body not stored: {len(raw)} bytes>"
            else:
                body = decode_body(raw, ctype)
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
                        "request_headers": clean_headers(req.headers),
                        "post_data": post,
                        "status": r.status,
                        "redirect_to": r.headers.get("location"),
                        "response_headers": clean_headers(r.headers),
                        "size": len(raw),
                        "body": body,
                    },
                )
            )
        except Exception as e:  # one bad response must not kill the run
            print(f"skipped a response: {e}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not HEADED)
        try:
            # Headless Chrome announces itself in the user agent; present as normal Chrome.
            ua = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                f"(KHTML, like Gecko) Chrome/{browser.version} Safari/537.36"
            )
            page = browser.new_context(user_agent=ua).new_page()
            page.on("response", on_response)
            try:
                page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT * 1000)
            except PlaywrightTimeout:
                print("page never went idle, saving what was captured so far")
            except Exception as e:
                print(f"navigation error: {e}")
            try:
                page.mouse.wheel(0, 4000)  # trigger lazy loading
                page.wait_for_timeout(WAIT * 1000)
            except Exception:  # noqa: S110
                pass
            if INTERACTIVE:
                input(
                    "Click around in the browser, then press Enter here to finish... "
                )
        finally:
            browser.close()

    # Name files exactly like F12; only repeated names get " (1)", " (2)", ...
    totals = Counter(n for n, _ in saved)
    seen = Counter()
    lines = []
    for name, data in saved:
        seen[name] += 1
        fname = f"{name} ({seen[name]})" if totals[name] > 1 else name
        (out / f"{fname}.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        lines.append(
            f"{fname}.json  {data['status']}  {data['size']}B  {data['url'][:120]}"
        )
    (out / "_index.md").write_text("\n".join(lines), encoding="utf-8")  # request order
    print("\n".join(lines))
    print(f"\n{len(saved)} requests saved to {out}/")


if __name__ == "__main__":
    main()
