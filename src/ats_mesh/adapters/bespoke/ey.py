# ~/src/ats_mesh/adapters/bespoke/ey.py

import asyncio
import html as htmllib
import re
from datetime import datetime

from ats_mesh.helpers.http_utils import Streak, get_with_retry
from ats_mesh.models import JobBasic

BASE = "https://careers.ey.com"
URL = f"{BASE}/search/"
PARAMS = {
    "q": "",
    "q2": "",
    "alertId": "",
    "locationsearch": "",
    "title": "",
    "location": "US",
}
PAGE_SIZE = 25  # the site's fixed page size, startrow steps by this
CONCURRENCY = 6  # detail pages in flight at once, 683 pages took about 100s
MAX_PAGES = 60  # safety stop, the list ends on an empty page well before this

ID_RE = re.compile(r"/(\d+)/?$")
HREF_RE = re.compile(
    r'class="jobTitle-link"[^>]*href="([^"]+)"|href="([^"]+)"[^>]*class="jobTitle-link"'
)
TITLE_RE = re.compile(r'class="jobTitle-link"[^>]*>([^<]+)<')
POSTED_RE = re.compile(r'itemprop="datePosted"\s+content="([^"]*)"')
META_RE = re.compile(r'<meta\s+itemprop="(\w+)"\s+content="([^"]*)"')


def clean(s):
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def parse_rows(page):
    rows = []
    for chunk in page.split('<tr class="data-row">')[1:]:
        href = HREF_RE.search(chunk)
        title = TITLE_RE.search(chunk)
        if not (href and title):
            continue
        path = htmllib.unescape(href.group(1) or href.group(2))
        job_id = ID_RE.search(path)
        if job_id:
            rows.append(
                {"id": job_id.group(1), "path": path, "title": clean(title.group(1))}
            )
    return rows


def parse_posted(value):
    """'Sun Sep 13 00:00:00 UTC 2026' -> '2026-09-13'"""
    try:
        return datetime.strptime(value, "%a %b %d %H:%M:%S UTC %Y").date().isoformat()  # noqa: DTZ007
    except ValueError:
        return None


def parse_detail(page):
    """Every location sits in its own <span itemprop="address"> as meta tags."""
    places = []
    for chunk in page.split('itemprop="address"')[1:]:
        block = chunk.split("</span>")[0]  # the metas live inside that one span
        meta = {
            k.lower(): htmllib.unescape(v).strip() for k, v in META_RE.findall(block)
        }
        parts = [
            meta.get("addresslocality"),
            meta.get("addressregion"),
            meta.get("addresscountry"),
        ]
        text = ", ".join(p for p in parts if p)
        if text:
            places.append(text)
    posted = POSTED_RE.search(page)
    return list(dict.fromkeys(places)), parse_posted(
        posted.group(1)
    ) if posted else None


class Ey:
    """SuccessFactors, server-rendered HTML. The list (25 a page, startrow paging,
    newest first) has only the title and id. The detail page has every location
    and the posted date as schema.org meta tags, so each new job costs one extra
    GET. Known ids are never fetched twice: the list walk stops after a few pages
    with nothing new, and details are only fetched for ids not in `known`."""

    def __init__(self, company):
        self.company = company

    async def _list_page(self, client, page):
        r = await get_with_retry(
            client, URL, params={**PARAMS, "startrow": page * PAGE_SIZE}
        )
        return r.text

    async def fetch_list(self, client, known):
        streak = Streak(known)
        rows = []
        for p in range(MAX_PAGES):
            try:
                got = parse_rows(await self._list_page(client, p))
            except Exception:
                if p == 0:
                    raise  # nothing to work with, let the run report it
                break  # keep what we have, the rest comes next run
            if not got:
                break
            rows += got
            streak.add([r["id"] for r in got])
            if streak.done:
                break
        return rows

    async def _detail(self, client, sem, row):
        async with sem:
            try:
                r = await get_with_retry(client, BASE + row["path"])
            except Exception:
                return None  # not returned, so it isn't known and gets retried next run
        return row, *parse_detail(r.text)

    def parse(self, row, places, posted):
        return JobBasic(
            ats=self.company["ats"],
            company_id=self.company["company_id"],
            company_name=self.company["name"],
            ats_job_id=row["id"],
            title=row["title"],
            url=BASE + row["path"],
            locations=places,
            posted=posted,
        )

    async def fetch_jobs(self, client, known=frozenset()):
        rows = {r["id"]: r for r in await self.fetch_list(client, known)}
        todo = [r for i, r in rows.items() if i not in known]
        sem = asyncio.Semaphore(CONCURRENCY)
        details = await asyncio.gather(*(self._detail(client, sem, r) for r in todo))
        return [self.parse(*d) for d in details if d]
