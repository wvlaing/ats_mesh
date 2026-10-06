# ~/src/ats_mesh/adapters/bespoke/apple.py

import asyncio
import importlib.util
import math
import random

import httpx

from ats_mesh.helpers.time_utils import fmt_date, to_utc
from ats_mesh.models import JobBasic

TEXAS_ONLY = True  # False = every US job (about 4,500, so roughly 225 pages)
CONCURRENCY = 3  # pages in flight at once, 3 didn't make Apple's empty pages worse
SORT = "newest"  # newest first, so jobs posted mid-crawl land on page 1

BASE = "https://jobs.apple.com"
SEARCH_URL = f"{BASE}/api/v1/search"
CSRF_URL = f"{BASE}/api/v1/CSRFToken"
LOCATION = "postLocation-state995" if TEXAS_ONLY else "postLocation-USA"
HTTP2 = importlib.util.find_spec("h2") is not None  # the site speaks h2, optional here

# The headers the site itself sends (Chrome 154 on macOS).
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Browserlocale": "en-us",
    "Locale": "en_US",
    "Origin": BASE,
    "Referer": f"{BASE}/en-us/search?sort={SORT}",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Priority": "u=1, i",
    "Sec-Ch-Ua": '"Chromium";v="154", "Google Chrome";v="154", "Not A(Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# What one page does when Apple answers 200 with no results. In testing an immediate
# retry on the same session fixed about 7 in 8, a fresh token the rest, and a brand
# new session was never needed, so it stays as the last resort.
STEPS = ["session", "retry", "retry", "token", "session", "session"]


def row_key(raw):
    return raw.get("positionId") or raw.get("id")


def add(rows, results):
    for raw in results:
        if key := row_key(raw):
            rows[key] = raw  # one row per posting, so repeats across pages vanish


def places(raw):
    """[{'name': 'Austin', 'countryName': 'United States of America'}] ->
    ['Austin, United States']. The country is added so the us_only filter can
    see these are US places (Apple leaves stateProvince empty)."""
    found = []
    for loc in raw.get("locations") or []:
        name = (loc.get("name") or "").strip()
        country = (loc.get("countryName") or "").strip().replace(" of America", "")
        if name and country and country.casefold() not in name.casefold():
            name = f"{name}, {country}"
        if name:
            found.append(name)
    return list(dict.fromkeys(found))


def posted(raw):
    try:
        return fmt_date(to_utc(raw.get("postDateInGMT")))
    except ValueError:
        return None  # one odd date shouldn't sink the whole pull


class Apple:
    """POST /api/v1/search, 20 jobs a page. Roughly 1 request in 5 comes back 200
    with an empty page, so every page runs its own short session (like the site,
    which fetches a CSRF token for each search) and retries on empties. That is
    why the shared client from main.py goes unused here."""

    def __init__(self, company):
        self.company = company

    @staticmethod
    def _payload(page):
        return {
            "query": "",
            "filters": {"locations": [LOCATION]},
            "page": page,
            "locale": "en-us",
            "sort": SORT,
            "format": {"longDate": "MMMM D, YYYY", "mediumDate": "MMM D, YYYY"},
        }

    async def _token(self, client):
        r = await client.get(CSRF_URL)
        r.raise_for_status()
        return r.headers["X-Apple-CSRF-Token"]

    async def _session(self):
        client = httpx.AsyncClient(
            headers=HEADERS, timeout=30, follow_redirects=True, http2=HTTP2
        )
        try:
            return client, await self._token(client)
        except Exception:
            await client.aclose()
            raise

    async def _search(self, client, token, page):
        r = await client.post(
            SEARCH_URL,
            json=self._payload(page),
            headers={"X-Apple-CSRF-Token": token},
        )
        r.raise_for_status()
        body = r.json()
        res = body.get("res") if isinstance(body, dict) else None
        return res if isinstance(res, dict) else {}

    async def _page(self, page):
        """One page, or {} if every try came back empty."""
        client = token = None
        try:
            for attempt, step in enumerate(STEPS):
                if attempt:
                    await asyncio.sleep(0.5 * attempt + random.random())
                if client is None:
                    step = "session"  # the last session attempt failed outright
                try:
                    if step == "session":
                        if client is not None:
                            await client.aclose()
                            client = None
                        client, token = await self._session()
                    elif step == "token":
                        token = await self._token(client)
                    res = await self._search(client, token, page)
                except (httpx.HTTPError, ValueError):
                    res = {}
                if res.get("searchResults"):
                    return res
            return {}
        finally:
            if client is not None:
                await client.aclose()

    async def _crawl(self, pages, rows):
        """Fetches pages a few at a time into rows. Returns the pages that gave up."""
        sem = asyncio.Semaphore(CONCURRENCY)

        async def one(page):
            async with sem:
                await asyncio.sleep(random.uniform(0.2, 0.6))
                res = await self._page(page)
                return page, res.get("searchResults") or []

        failed = []
        for page, results in await asyncio.gather(*(one(p) for p in pages)):
            if results:
                add(rows, results)
            else:
                failed.append(page)
        return failed

    async def fetch_list(self):
        first = await self._page(1)
        results = first.get("searchResults") or []
        if not results:
            raise ValueError("page 1 came back empty after every retry")
        per_page = len(results)
        total = first.get("totalRecords") or per_page
        rows = {}
        add(rows, results)

        missing = await self._crawl(range(2, math.ceil(total / per_page) + 1), rows)
        if missing:  # one more go at the pages that gave up, after a pause
            await asyncio.sleep(5)
            missing = await self._crawl(missing, rows)

        # Newest first, so anything posted while we were paging is on page 1. If the
        # total moved, every page after it shifted while we read it: sweep once more.
        latest = await self._page(1)
        add(rows, latest.get("searchResults") or [])
        new_total = latest.get("totalRecords") or total
        if new_total != total:
            missing = await self._crawl(
                range(2, math.ceil(new_total / per_page) + 1), rows
            )
        if missing:
            print(f"Apple: pages {sorted(missing)} never came back, retry next run")
        return list(rows.values())

    def parse(self, raw):
        job_id = str(row_key(raw))
        slug = raw.get("transformedPostingTitle")
        return JobBasic(
            ats=self.company["ats"],
            company_id=self.company["company_id"],
            company_name=self.company["name"],
            ats_job_id=job_id,
            title=(raw.get("postingTitle") or "").strip(),
            url=f"{BASE}/en-us/details/{job_id}" + (f"/{slug}" if slug else ""),
            locations=places(raw),
            posted=posted(raw),
        )

    async def fetch_jobs(self, _client):
        return [self.parse(r) for r in await self.fetch_list()]
