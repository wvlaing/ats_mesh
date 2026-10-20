import asyncio
import math
import random
from collections.abc import Iterable, Set

import httpx

from ats_mesh.adapters.base import Adapter
from ats_mesh.dates import eastern_date
from ats_mesh.models import Job, Raw
from ats_mesh.net import Streak

TEXAS_ONLY = True  # False = every US job (about 4,500, so roughly 225 pages)
CONCURRENCY = 3  # pages in flight at once, 3 didn't make Apple's empty pages worse
SORT = "newest"  # newest first, so jobs posted mid-crawl land on page 1

BASE = "https://jobs.apple.com"
SEARCH_URL = f"{BASE}/api/v1/search"
CSRF_URL = f"{BASE}/api/v1/CSRFToken"
LOCATION = "postLocation-state995" if TEXAS_ONLY else "postLocation-USA"

# The headers the site itself sends (Chrome 154 on macOS).
HEADERS: dict[str, str] = {
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


def row_id(raw: Raw) -> str:
    return str(raw.get("positionId") or raw.get("id") or "")


def places(raw: Raw) -> list[str]:
    """[{'name': 'Austin', 'countryName': 'United States of America'}] ->
    ['Austin, United States']. The country is added so the us_only filter can see
    these are US places (Apple leaves stateProvince empty)."""
    found: list[str] = []
    for loc in raw.get("locations") or []:
        name: str = (loc.get("name") or "").strip()
        country: str = (loc.get("countryName") or "").strip().replace(" of America", "")
        if name and country and country.casefold() not in name.casefold():
            name = f"{name}, {country}"
        if name:
            found.append(name)
    return found


class Apple(Adapter):
    """POST /api/v1/search, 20 jobs a page, newest first. Roughly 1 request in 5
    comes back 200 with an empty page, so every page runs its own short session (like
    the site, which fetches a CSRF token for each search) and retries on empties. That
    is why the shared client from main.py goes unused here.

    Pages are fetched a few at a time, in order. The crawl stops once a few pages in
    a row hold nothing outside `known` (see Streak). An empty page never counts toward
    that, since it says nothing about what is on it."""

    @staticmethod
    def _payload(page: int) -> Raw:
        return {
            "query": "",
            "filters": {"locations": [LOCATION]},
            "page": page,
            "locale": "en-us",
            "sort": SORT,
            "format": {"longDate": "MMMM D, YYYY", "mediumDate": "MMM D, YYYY"},
        }

    @staticmethod
    async def _token(client: httpx.AsyncClient) -> str:
        r: httpx.Response = await client.get(CSRF_URL)
        r.raise_for_status()
        return r.headers["X-Apple-CSRF-Token"]

    async def _session(self) -> tuple[httpx.AsyncClient, str]:
        client = httpx.AsyncClient(
            headers=HEADERS, timeout=30, follow_redirects=True, http2=True
        )
        try:
            return client, await self._token(client)
        except Exception:
            await client.aclose()
            raise

    async def _search(self, client: httpx.AsyncClient, token: str, page: int) -> Raw:
        r: httpx.Response = await client.post(
            SEARCH_URL, json=self._payload(page), headers={"X-Apple-CSRF-Token": token}
        )
        r.raise_for_status()
        body = r.json()
        res = body.get("res") if isinstance(body, dict) else None
        return res if isinstance(res, dict) else {}

    async def _page(self, page: int) -> Raw:
        """One page, or {} if every try came back empty."""
        client: httpx.AsyncClient | None = None
        token = ""
        try:
            for attempt, step in enumerate(STEPS):
                if attempt:
                    await asyncio.sleep(0.5 * attempt + random.random())
                try:
                    if client is None or step == "session":
                        if client is not None:
                            await client.aclose()
                            client = None
                        client, token = await self._session()
                    elif step == "token":
                        token = await self._token(client)
                    res = await self._search(client, token, page)
                except httpx.HTTPError, ValueError:
                    res = {}
                if res.get("searchResults"):
                    return res
            return {}
        finally:
            if client is not None:
                await client.aclose()

    @staticmethod
    def _add(
        rows: dict[str, Raw], results: Iterable[Raw], streak: Streak | None = None
    ) -> None:
        """One row per posting, so repeats across pages vanish."""
        results = list(results)
        for raw in results:
            if key := row_id(raw):
                rows[key] = raw
        if streak:
            streak.add(row_id(raw) for raw in results if row_id(raw))

    async def _crawl(
        self, pages: Iterable[int], rows: dict[str, Raw], streak: Streak | None = None
    ) -> list[int]:
        """Fetches pages a few at a time into rows, one batch after the next so the
        streak sees them in order. With a streak it stops once enough pages in a row
        held nothing new. Returns the pages that gave up."""
        todo: list[int] = list(pages)
        sem = asyncio.Semaphore(CONCURRENCY)

        async def one(page: int) -> tuple[int, list[Raw]]:
            async with sem:
                await asyncio.sleep(random.uniform(0.2, 0.6))
                return page, (await self._page(page)).get("searchResults") or []

        failed: list[int] = []
        for i in range(0, len(todo), CONCURRENCY):
            for page, results in await asyncio.gather(
                *(one(p) for p in todo[i : i + CONCURRENCY])
            ):
                if results:
                    self._add(rows, results, streak)
                else:
                    failed.append(page)
            if streak and streak.done:
                break
        return failed

    async def fetch_jobs(self, client: httpx.AsyncClient, known: Set[str]) -> list[Job]:
        first = await self._page(1)
        results: list[Raw] = first.get("searchResults") or []
        if not results:
            raise ValueError("page 1 came back empty after every retry")
        per_page: int = len(results)
        pages: int = math.ceil((first.get("totalRecords") or per_page) / per_page)

        rows: dict[str, Raw] = {}
        streak = Streak(known)
        self._add(rows, results, streak)
        missing: list[int] = (
            [] if streak.done else await self._crawl(range(2, pages + 1), rows, streak)
        )
        if missing:  # one more go at the pages that gave up, after a pause
            await asyncio.sleep(5)
            missing = await self._crawl(missing, rows)
        # Newest first, so anything posted while we were paging is on page 1.
        self._add(rows, (await self._page(1)).get("searchResults") or [])
        if missing:
            print(f"Apple: pages {sorted(missing)} never came back, retry next run")
        return [self._parse(raw) for raw in rows.values()]

    def _parse(self, raw: Raw) -> Job:
        job_id: str = row_id(raw)
        slug = raw.get("transformedPostingTitle")
        return self.job(
            job_id,
            raw.get("postingTitle") or "",
            f"{BASE}/en-us/details/{job_id}" + (f"/{slug}" if slug else ""),
            places(raw),
            eastern_date(raw.get("postDateInGMT")),
        )
