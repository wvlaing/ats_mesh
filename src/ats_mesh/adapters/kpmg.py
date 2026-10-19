import html
import re
import time
from collections.abc import Set
from contextlib import aclosing
from typing import NamedTuple

import httpx

from ats_mesh import net
from ats_mesh.adapters.base import Adapter
from ats_mesh.net import Streak
from ats_mesh.models import Job

BASE = "https://www.kpmguscareers.com"
URL = f"{BASE}/wp-content/themes/understrap-child-main/page-templates/google/get-jobs.php"
PARAMS = {
    "ajax": "1",
    "career-level-parents": "",
    "career-level": (
        "Early Career|Administrative/Technical Support|Associate|Senior Associate|Manager|"
    ),
    "order": "posted",  # newest first
}
MAX_PAGES = 120  # safety stop, the list ends on an empty page well before this

ITEM_SPLIT = 'class="search--item'
JOB_ID_RE = re.compile(r'href="(/jobdetail/\?jobId=(\d+))[^"]*"')
TITLE_RE = re.compile(r'class="h4 mb-4">([^<]+)<')
# "Tax | Dallas, TX; New York, NY". The "3 Locations" div has no pipe, so it is skipped.
META_RE = re.compile(r'class="text-xs text-dark-grey">\s*([^<|]*?)\s*\|\s*([^<]*?)\s*<')


class Listing(NamedTuple):
    id: str
    path: str
    title: str
    places: list[str]


def clean(s: str) -> str:
    return " ".join(html.unescape(s).split())


def parse_rows(jobs_html: str) -> list[Listing]:
    rows: list[Listing] = []
    for chunk in jobs_html.split(ITEM_SPLIT)[1:]:
        href = JOB_ID_RE.search(chunk)
        title = TITLE_RE.search(chunk)
        if not (href and title):
            continue
        meta = META_RE.search(chunk)
        places = [clean(p) for p in meta.group(2).split(";")] if meta else []
        rows.append(Listing(href.group(2), html.unescape(href.group(1)), clean(title.group(1)), places))
    return rows


class Kpmg(Adapter):
    """KPMG US careers: a PHP endpoint returning JSON with the job cards as an HTML
    string (postings.jobs), paged with spage=1, 2, ... and sorted newest first. The
    list has the title, id and every location, so there are no detail requests. It has
    no posted date, so `posted` is None and a job ages from the day we first saw it.

    The walk stops when a few pages in a row hold nothing new (see Streak), when a
    page is empty, or when a page repeats (some servers answer past the end with
    the last page again)."""

    async def _rows(self, client: httpx.AsyncClient, page: int) -> list[Listing]:
        r = await net.get(client, URL, params={**PARAMS, "spage": page, "_": int(time.time() * 1000)})
        return parse_rows((r.json().get("postings") or {}).get("jobs") or "")

    async def fetch_jobs(self, client: httpx.AsyncClient, known: Set[str]) -> list[Job]:
        streak = Streak(known)
        listed: set[str] = set()
        jobs: list[Job] = []
        async with aclosing(
            net.walk(lambda page: self._rows(client, page), start=1, limit=MAX_PAGES)
        ) as pages:
            async for rows in pages:
                fresh = [r for r in rows if r.id not in listed]
                if not fresh:
                    break  # empty page, or the same page served again
                listed.update(r.id for r in fresh)
                streak.add(r.id for r in rows)
                jobs += [self.job(r.id, r.title, BASE + r.path, r.places) for r in fresh]
                if streak.done:
                    break
        return jobs
