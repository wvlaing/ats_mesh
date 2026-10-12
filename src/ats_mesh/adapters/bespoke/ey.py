# ~/src/ats_mesh/adapters/bespoke/ey.py

import asyncio
import html as htmllib
import re
from datetime import UTC, datetime

from ats_mesh.helpers.http_utils import Streak, get_with_retry
from ats_mesh.helpers.time_utils import cutoff_date
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
CONCURRENCY = 6  # detail pages in flight at once
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
    """Return the detail page's posted date as YYYY-MM-DD, or None."""
    try:
        parsed = datetime.strptime(value, "%a %b %d %H:%M:%S UTC %Y")  # noqa: DTZ007
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC).date().isoformat()


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
    newest first) has only the title and id. The detail page is the only place with
    the posted date and every location, so each job we look at costs one GET.

    To keep that small the list is walked page by page and details are fetched only
    for ids not in `known`. The walk stops when either a few pages in a row hold
    nothing new (see Streak) or a detail shows a job older than the cutoff (max age
    plus a week), since everything after it is older still. Jobs past the cutoff
    are dropped, not stored.

    Speed: the next list page is requested while the current one's details are
    still coming in. On each page the first unknown job is fetched alone, because
    if it is already past the cutoff the rest of the page is too and nothing else
    is fetched. Otherwise the rest of the page goes out at once, CONCURRENCY at a
    time (a semaphore, so one slow page doesn't hold up the others)."""

    def __init__(self, company):
        self.company = company

    async def _list_page(self, client, page):
        r = await get_with_retry(
            client, URL, params={**PARAMS, "startrow": page * PAGE_SIZE}
        )
        return r.text

    async def _detail(self, client, sem, row):
        async with sem:
            try:
                r = await get_with_retry(
                    client,
                    BASE + row["path"],
                    retries=DETAIL_RETRIES,
                    timeout=DETAIL_TIMEOUT,
                )
            except Exception:
                return None  # not returned, so it isn't known and gets retried next run
        return row, *parse_detail(r.text)

    def parse(self, row, places, posted):
        return JobBasic(
            ats=self.company["ats"],
            company_name=self.company["name"],
            ats_job_id=row["id"],
            title=row["title"],
            url=BASE + row["path"],
            locations=places,
            posted=posted,
        )

    async def _details(self, client, sem, todo, oldest, jobs):
        """Looks up `todo` (newest first) and appends the ones inside the cutoff to
        `jobs`. Returns True once a job past the cutoff turns up."""
        got = [await self._detail(client, sem, todo[0])]
        if not (got[0] and got[0][2] and got[0][2] < oldest):
            rest = (self._detail(client, sem, r) for r in todo[1:])
            got += await asyncio.gather(*rest)
        too_old = False
        for d in got:
            if not d:
                continue
            row, places, posted = d
            if posted and posted < oldest:
                too_old = True
            else:
                jobs.append(self.parse(row, places, posted))
        return too_old

    async def fetch_jobs(self, client, known=frozenset()):
        oldest = cutoff_date().isoformat()  # ISO dates compare correctly as text
        streak = Streak(known)
        sem = asyncio.Semaphore(CONCURRENCY)
        seen, jobs = set(), []
        pending = asyncio.create_task(self._list_page(client, 0))
        try:
            for p in range(MAX_PAGES):
                try:
                    rows = parse_rows(await pending)
                except Exception:
                    if p == 0:
                        raise  # nothing to work with, let the run report it
                    break  # keep what we have, the rest comes next run
                if not rows:
                    break
                pending = asyncio.create_task(self._list_page(client, p + 1))
                streak.add([r["id"] for r in rows])

                skip = known | seen
                todo = [r for r in rows if r["id"] not in skip]
                seen.update(r["id"] for r in todo)
                if todo and await self._details(client, sem, todo, oldest, jobs):
                    break  # newest first, so nothing after this is in range
                if streak.done:
                    break
        finally:
            pending.cancel()  # the page requested ahead, if the walk ended early
            await asyncio.gather(pending, return_exceptions=True)
        return jobs
