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
CONCURRENCY = 6  # detail pages in flight at once, also the size of each chunk
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
    for ids not in `known`, a few at a time. The walk stops when either a few pages
    in a row hold nothing new (see Streak) or a detail shows a job older than the
    cutoff (max age plus a week), since everything after it is older still. Jobs
    past the cutoff are dropped, not stored."""

    def __init__(self, company):
        self.company = company

    async def _list_page(self, client, page):
        r = await get_with_retry(
            client, URL, params={**PARAMS, "startrow": page * PAGE_SIZE}
        )
        return r.text

    async def _detail(self, client, row):
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
        oldest = cutoff_date().isoformat()  # ISO dates compare correctly as text
        streak = Streak(known)
        seen, jobs = set(), []
        for p in range(MAX_PAGES):
            try:
                rows = parse_rows(await self._list_page(client, p))
            except Exception:
                if p == 0:
                    raise  # nothing to work with, let the run report it
                break  # keep what we have, the rest comes next run
            if not rows:
                break
            streak.add([r["id"] for r in rows])

            todo = [r for r in rows if r["id"] not in known and r["id"] not in seen]
            seen.update(r["id"] for r in todo)
            for i in range(0, len(todo), CONCURRENCY):
                got = await asyncio.gather(
                    *(self._detail(client, r) for r in todo[i : i + CONCURRENCY])
                )
                too_old = False
                for d in got:
                    if not d:
                        continue
                    row, places, posted = d
                    if posted and posted < oldest:
                        too_old = True
                    else:
                        jobs.append(self.parse(row, places, posted))
                if too_old:
                    return jobs  # newest first, so nothing after this is in range

            if streak.done:
                break
        return jobs
