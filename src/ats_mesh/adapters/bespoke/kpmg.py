# ~/src/ats_mesh/adapters/bespoke/kpmg.py

import asyncio
import html as htmllib
import re
import time
from datetime import UTC, datetime

from ats_mesh.helpers.http_utils import Streak, get_with_retry
from ats_mesh.models import JobBasic

BASE = "https://www.kpmguscareers.com"
URL = (
    f"{BASE}/wp-content/themes/understrap-child-main/page-templates/google/get-jobs.php"
)
PARAMS = {
    "ajax": "1",
    "career-level-parents": "",
    "career-level": (
        "Early Career|Administrative/Technical Support|Associate"
        "|Senior Associate|Manager|"
    ),
    "order": "posted",  # newest first
}
FIRST_RUN_PAGES = 3  # empty `known`: take only the newest pages as a baseline
MAX_PAGES = 120  # safety stop for normal runs, the Streak ends them much sooner

ITEM_SPLIT = 'class="search--item'
JOB_ID_RE = re.compile(r'href="(/jobdetail/\?jobId=(\d+))[^"]*"')
TITLE_RE = re.compile(r'class="h4 mb-4">([^<]+)<')
# "Tax | Dallas, TX; New York, NY". The "3 Locations" div has no pipe, so it is skipped.
META_RE = re.compile(r'class="text-xs text-dark-grey">\s*([^<|]*?)\s*\|\s*([^<]*?)\s*<')


def clean(s):
    return " ".join(htmllib.unescape(s).split())


def parse_rows(jobs_html):
    rows = []
    for chunk in jobs_html.split(ITEM_SPLIT)[1:]:
        href = JOB_ID_RE.search(chunk)
        title = TITLE_RE.search(chunk)
        if not (href and title):
            continue
        meta = META_RE.search(chunk)
        places = [clean(p) for p in meta.group(2).split(";")] if meta else []
        rows.append(
            {
                "id": href.group(2),
                "path": htmllib.unescape(href.group(1)),
                "title": clean(title.group(1)),
                "places": list(dict.fromkeys(p for p in places if p)),
            }
        )
    return rows


class Kpmg:
    """KPMG US careers, a PHP endpoint that returns JSON with the job cards as an
    HTML string (postings.jobs). Paging is spage=1, 2, ... newest first. The list
    has the title, id and every location, so there are no detail requests.

    The site has no usable posted date (the detail page's datePosted is the 1st
    of the current month for every job). So `posted` is the first-seen date: the
    day this adapter first returned the id. That only means something if the
    baseline is clean, so:

    - First run (`known` empty): fetch only FIRST_RUN_PAGES pages and set
      `posted` to None, because those jobs could be any age. Older jobs deeper
      in the list are never stored, which is fine since only new ones matter.
    - Later runs: walk from page 1 and stop when a few pages in a row hold
      nothing new (see Streak), a page is empty, or a page repeats. New ids get
      today's date as `posted`.

    The next page is requested while the current one is being parsed."""

    def __init__(self, company):
        self.company = company

    async def _list_page(self, client, page):
        r = await get_with_retry(
            client,
            URL,
            params={**PARAMS, "spage": page, "_": int(time.time() * 1000)},
        )
        return (r.json().get("postings") or {}).get("jobs") or ""

    def parse(self, row, posted):
        return JobBasic(
            ats=self.company["ats"],
            company_name=self.company["name"],
            ats_job_id=row["id"],
            title=row["title"],
            url=BASE + row["path"],
            locations=row["places"],
            posted=posted,
        )

    async def fetch_jobs(self, client, known=frozenset()):
        baseline = not known
        last_page = FIRST_RUN_PAGES if baseline else MAX_PAGES
        posted = None if baseline else datetime.now(UTC).date().isoformat()
        streak = Streak(known)
        listed, jobs = set(), []
        pending = asyncio.create_task(self._list_page(client, 1))
        try:
            for p in range(1, last_page + 1):
                try:
                    rows = parse_rows(await pending)
                except Exception:
                    if p == 1:
                        raise  # nothing to work with, let the run report it
                    break  # keep what we have, the rest comes next run
                fresh = [r for r in rows if r["id"] not in listed]
                if not fresh:
                    break  # empty page, or the same page served again
                if p < last_page:
                    pending = asyncio.create_task(self._list_page(client, p + 1))
                listed.update(r["id"] for r in fresh)
                streak.add([r["id"] for r in rows])
                jobs += [self.parse(r, posted) for r in fresh if r["id"] not in known]
                if streak.done:
                    break
        finally:
            pending.cancel()  # the page requested ahead, if the walk ended early
            await asyncio.gather(pending, return_exceptions=True)
        return jobs
