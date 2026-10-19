import math
from collections.abc import Set

import httpx

from ats_mesh import net
from ats_mesh.adapters.base import Adapter, split_locations
from ats_mesh.dates import eastern_date
from ats_mesh.models import Job, Raw

URL = "https://careers.docusign.com/api/jobs"
LIMIT = 100  # a guess at the server's maximum


class Docusign(Adapter):
    """Paged GET returning {"jobs": [{"data": {...}}], "totalCount": N}. It sorts by
    relevance, not date, so a page of known jobs says nothing about the pages after
    it: every page is always read."""

    async def _page(self, client: httpx.AsyncClient, page: int) -> Raw:
        params = {
            "page": page,
            "limit": LIMIT,
            "sortBy": "relevance",
            "descending": "false",
            "internal": "false",
        }
        r = await net.get(client, self.access.get("portal", URL), params=params)
        return r.json()

    async def _jobs(self, client: httpx.AsyncClient, page: int) -> list[Raw]:
        return (await self._page(client, page)).get("jobs") or []

    async def fetch_jobs(self, client: httpx.AsyncClient, known: Set[str]) -> list[Job]:
        first = await self._page(client, 1)
        raws: list[Raw] = first.get("jobs") or []
        if not raws:
            return []
        # Count pages by what came back, in case the server caps the limit.
        pages = math.ceil(first.get("totalCount", 0) / len(raws))
        raws += await net.gather_lists(
            self._jobs(client, page) for page in range(2, pages + 1)
        )
        return [self._parse(raw["data"]) for raw in raws]

    def _parse(self, d: Raw) -> Job:
        return self.job(
            d["req_id"],
            d["title"],
            d.get("meta_data", {}).get("canonical_url"),
            split_locations(d.get("full_location")),
            eastern_date(d.get("posted_date")),
        )
