import re
from collections.abc import Set

import httpx

from ats_mesh import net
from ats_mesh.adapters.base import Adapter, split_locations
from ats_mesh.dates import days_ago
from ats_mesh.models import Company, Job, Raw

LIMIT = 20  # Typical workday page limit
US = "bc33aa3152ec42d4995f4791a106ed09"  # Country id for the United States (not always available)


def posted_date(text: str | None) -> str | None:
    """'Posted 5 Days Ago' -> the date 5 days back. 'Posted 30+ Days Ago' counts as 30."""
    if not text:
        return None
    text = text.lower()
    if "today" in text:
        return days_ago(0)
    if "yesterday" in text:
        return days_ago(1)
    if m := re.search(r"\d+", text):
        return days_ago(int(m.group()))
    return None


class Workday(Adapter):
    def __init__(self, company: Company) -> None:
        super().__init__(company)
        self.portal: str = self.access["portal"]
        # US only by default, set "facets" in companies.json to override with something else
        self.facets: Raw = self.access.get("facets", {"locationCountry": [US]})
        host, rest = self.portal.split("/wday/cxs/")
        self.job_base = f"{host}/{rest.split('/')[1]}"  # https://host/SITE

    async def _page(self, client: httpx.AsyncClient, offset: int) -> Raw:
        r = await net.post(
            client,
            self.portal,
            json={
                "appliedFacets": self.facets,
                "limit": LIMIT,
                "offset": offset,
                "searchText": "",
            },
        )
        return r.json()

    async def _postings(self, client: httpx.AsyncClient, offset: int) -> list[Raw]:
        return (await self._page(client, offset))["jobPostings"]

    async def fetch_jobs(self, client: httpx.AsyncClient, known: Set[str]) -> list[Job]:
        try:
            first = await self._page(client, 0)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 400 or not self.facets:
                raise
            self.facets = {}  # US only failed: try again with no country filter
            first = await self._page(client, 0)
        rest = await net.gather_lists(
            self._postings(client, offset) for offset in range(LIMIT, first["total"], LIMIT)
        )
        return [self._parse(raw) for raw in first["jobPostings"] + rest if raw.get("externalPath")]

    def _parse(self, raw: Raw) -> Job:
        path = raw["externalPath"]
        fields = raw.get("bulletFields") or []  # [job id, location, ...]
        # Without locationsText, every field after the id is a location, kept whole
        # ('Boston, 888 Boylston, Corp' is one place with commas in it).
        places = split_locations(raw.get("locationsText")) or [
            f.strip() for f in fields[1:] if f and f.strip()
        ]
        return self.job(
            fields[0] if fields else path,
            raw["title"],
            f"{self.job_base}{path}",
            places,
            posted_date(raw.get("postedOn")),
        )
