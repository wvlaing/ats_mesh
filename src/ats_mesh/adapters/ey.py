import asyncio
import html
import re
from collections.abc import Set
from contextlib import aclosing
from datetime import UTC, datetime
from typing import NamedTuple

import httpx

from ats_mesh import net
from ats_mesh.adapters.base import Adapter
from ats_mesh.dates import cutoff
from ats_mesh.net import Streak
from ats_mesh.models import Job

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
CONCURRENCY = 25  # detail pages in flight at once
DETAIL_RETRIES = 2  # a stuck detail page gets skipped, it is retried next run
DETAIL_TIMEOUT = 15  # seconds, instead of the client's 30
MAX_PAGES = 60  # safety stop, the list ends on an empty page well before this

ID_RE = re.compile(r"/(\d+)/?$")
HREF_RE = re.compile(
    r'class="jobTitle-link"[^>]*href="([^"]+)"|href="([^"]+)"[^>]*class="jobTitle-link"'
)
TITLE_RE = re.compile(r'class="jobTitle-link"[^>]*>([^<]+)<')
POSTED_RE = re.compile(r'itemprop="datePosted"\s+content="([^"]*)"')
META_RE = re.compile(r'<meta\s+itemprop="(\w+)"\s+content="([^"]*)"')


class Listing(NamedTuple):
    id: str
    path: str
    title: str


type Detail = tuple[Listing, list[str], str | None]  # listing, locations, posted


def clean(s: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def parse_rows(page: str) -> list[Listing]:
    rows: list[Listing] = []
    for chunk in page.split('<tr class="data-row">')[1:]:
        href = HREF_RE.search(chunk)
        title = TITLE_RE.search(chunk)
        if not (href and title):
            continue
        path = html.unescape(href.group(1) or href.group(2))
        if job_id := ID_RE.search(path):
            rows.append(Listing(job_id.group(1), path, clean(title.group(1))))
    return rows


def parse_posted(value: str) -> str | None:
    """'Mon Oct 12 00:00:00 UTC 2026' -> '2026-10-12', or None."""
    try:
        parsed = datetime.strptime(value, "%a %b %d %H:%M:%S UTC %Y")  # noqa: DTZ007
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC).date().isoformat()


def parse_detail(page: str) -> tuple[list[str], str | None]:
    """Every location sits in its own <span itemprop="address"> as meta tags."""
    places: list[str] = []
    for chunk in page.split('itemprop="address"')[1:]:
        block = chunk.split("</span>")[0]  # the metas live inside that one span
        meta = {k.lower(): html.unescape(v).strip() for k, v in META_RE.findall(block)}
        parts = (meta.get("addresslocality"), meta.get("addressregion"), meta.get("addresscountry"))
        if text := ", ".join(p for p in parts if p):
            places.append(text)
    posted = POSTED_RE.search(page)
    return places, parse_posted(posted.group(1)) if posted else None


class Ey(Adapter):
    """SuccessFactors, server-rendered HTML. The list (25 a page, startrow paging,
    newest first) has only the title and id. The detail page is the only place with
    the posted date and every location, so each job we look at costs one GET.

    To keep that small the list is walked page by page and details are fetched only
    for ids not in `known`. The walk stops when a few pages in a row hold nothing new
    (see Streak) or a detail shows a job older than the cutoff, since everything after
    it is older still. Jobs past the cutoff are dropped, not stored.

    On each page the first unknown job is fetched alone, because if it is already
    past the cutoff the rest of the page is too and nothing else is fetched.
    Otherwise the rest of the page goes out at once, CONCURRENCY at a time."""

    async def _rows(self, client: httpx.AsyncClient, page: int) -> list[Listing]:
        r = await net.get(client, URL, params={**PARAMS, "startrow": page * PAGE_SIZE})
        return parse_rows(r.text)

    async def _detail(
        self, client: httpx.AsyncClient, sem: asyncio.Semaphore, row: Listing
    ) -> Detail | None:
        async with sem:
            try:
                r = await net.get(
                    client, BASE + row.path, retries=DETAIL_RETRIES, timeout=DETAIL_TIMEOUT
                )
            except httpx.HTTPError:
                return None  # not returned, so it isn't known and gets retried next run
        places, posted = parse_detail(r.text)
        return row, places, posted

    async def _details(
        self,
        client: httpx.AsyncClient,
        sem: asyncio.Semaphore,
        todo: list[Listing],
        oldest: str,
        jobs: list[Job],
    ) -> bool:
        """Looks up `todo` (newest first) and appends the ones inside the cutoff to
        `jobs`. Returns True once a job past the cutoff turns up."""
        got = [await self._detail(client, sem, todo[0])]
        if not (got[0] and got[0][2] and got[0][2] < oldest):
            got += await asyncio.gather(*(self._detail(client, sem, r) for r in todo[1:]))
        too_old = False
        for detail in got:
            if not detail:
                continue
            row, places, posted = detail
            if posted and posted < oldest:
                too_old = True
            else:
                jobs.append(self.job(row.id, row.title, BASE + row.path, places, posted))
        return too_old

    async def fetch_jobs(self, client: httpx.AsyncClient, known: Set[str]) -> list[Job]:
        oldest = cutoff()
        streak = Streak(known)
        sem = asyncio.Semaphore(CONCURRENCY)
        seen: set[str] = set()
        jobs: list[Job] = []
        async with aclosing(
            net.walk(lambda page: self._rows(client, page), limit=MAX_PAGES)
        ) as pages:
            async for rows in pages:
                if not rows:
                    break
                streak.add(r.id for r in rows)
                todo = [r for r in rows if r.id not in known and r.id not in seen]
                seen.update(r.id for r in todo)
                if todo and await self._details(client, sem, todo, oldest, jobs):
                    break  # newest first, so nothing after this is in range
                if streak.done:
                    break
        return jobs
