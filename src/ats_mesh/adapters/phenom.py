import asyncio
import json
import re
from collections.abc import Set

import httpx

from ats_mesh import net
from ats_mesh.adapters.base import Adapter
from ats_mesh.models import Company, Job, Raw

PAGE_SIZE = 10  # what the site asks for; a bigger size (try 100) is untested
PARALLEL = 8  # page requests in flight at once
# The facet counts the site asks for alongside the jobs, copied from its own request.
FIELDS = [
    "category",
    "raasJobRequisitionType",
    "country",
    "state",
    "city",
    "type",
    "RemoteType",
]


def js_object(page: str, marker: str) -> Raw:
    """The {...} that follows `marker` in the page's inline script."""
    start = page.index("{", page.index(marker))
    return json.JSONDecoder().raw_decode(page, start)[0]


class Phenom(Adapter):
    """Phenom search pages carry their own settings and a CSRF token in the HTML.
    The jobs come from POST {site}/widgets, which the page itself calls for every
    search and page turn."""

    def __init__(self, company: Company) -> None:
        super().__init__(company)
        self.portal: str = self.access["portal"]  # the site's search-results page
        # None by default, set "facets" in companies.json to filter, e.g.
        # {"country": ["United States of America"]}
        self.facets: Raw = self.access.get("facets", {})
        self.limit = asyncio.Semaphore(PARALLEL)

    async def _open(self, client: httpx.AsyncClient) -> None:
        """Load the search page for its settings, token and session cookie."""
        r = await net.get(client, self.portal, headers={"Accept": "text/html"})
        self.app: Raw = js_object(r.text, "var phApp = phApp ||")
        self.headers = {
            "x-csrf-token": js_object(r.text, "phApp.sessionParams =")["csrfToken"],
            "Origin": self.app["rootDomain"],
            "Referer": self.portal,
        }

    async def _page(self, client: httpx.AsyncClient, offset: int) -> Raw:
        app = self.app
        body: Raw = {
            "sortBy": "",
            "subsearch": "",
            "from": offset,
            "jobs": True,
            "counts": True,
            "all_fields": FIELDS,
            "pageName": app["pageName"],
            "size": PAGE_SIZE,
            "clearAll": False,
            "jdsource": "facets",
            "isSliderEnable": False,
            "pageId": app["pageId"],
            "siteType": app["siteType"],
            "keywords": "",
            "global": True,
            "selected_fields": self.facets,
            "lang": app["locale"],
            "deviceType": app["deviceType"],
            "country": app["country"],
            "refNum": app["refNum"],
            "ddoKey": "refineSearch",
        }
        async with self.limit:
            r = await net.post(
                client, app["widgetApiEndpoint"], json=body, headers=self.headers
            )
        result: Raw = r.json()["refineSearch"]
        if "data" not in result:  # {"tokenAvailable": false} = the token was refused
            raise ValueError(f"Phenom refused the search: {result}")
        return result

    async def fetch_jobs(self, client: httpx.AsyncClient, known: Set[str]) -> list[Job]:
        await self._open(client)
        first = await self._page(client, 0)
        jobs: list[Raw] = first["data"]["jobs"]
        step = len(jobs)  # step by what came back, in case the site caps the size
        if step:
            rest = await net.gather_lists(
                self._jobs(client, offset)
                for offset in range(step, first["totalHits"], step)
            )
            jobs += rest
        return [self._parse(raw) for raw in jobs]

    async def _jobs(self, client: httpx.AsyncClient, offset: int) -> list[Raw]:
        return (await self._page(client, offset))["data"]["jobs"]

    def _parse(self, raw: Raw) -> Job:
        title: str = raw["title"]
        slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")
        # postedDate is midnight UTC, so its first ten characters are the date.
        # dateCreated is when the requisition was made, often months earlier.
        return self.job(
            raw.get("jobId") or raw["reqId"],
            title,
            f"{self.app['baseUrl']}job/{raw['jobSeqNo']}/{slug}",
            raw.get("multi_location") or [raw.get("location")],
            (raw.get("postedDate") or "")[:10] or None,
        )
