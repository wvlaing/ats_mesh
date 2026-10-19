from collections.abc import Set

import httpx

from ats_mesh import net
from ats_mesh.adapters.base import Adapter, split_locations
from ats_mesh.dates import eastern_date
from ats_mesh.models import Job, Raw

BASE_URL = "https://api.smartrecruiters.com/v1/companies"
PAGE_SIZE = 100  # API maximum per page


class SmartRecruiters(Adapter):
    async def _page(self, client: httpx.AsyncClient, offset: int) -> Raw:
        url = f"{BASE_URL}/{self.access['company_identifier']}/postings"
        r = await net.get(client, url, params={"limit": PAGE_SIZE, "offset": offset})
        return r.json()

    async def fetch_jobs(self, client: httpx.AsyncClient, known: Set[str]) -> list[Job]:
        token = self.access["company_identifier"]
        first = await self._page(client, 0)
        rest = await net.gather_lists(
            self._content(client, offset)
            for offset in range(PAGE_SIZE, first.get("totalFound", 0), PAGE_SIZE)
        )
        postings: list[Raw] = (first.get("content") or []) + rest
        return [self._parse(raw, token) for raw in postings]

    async def _content(self, client: httpx.AsyncClient, offset: int) -> list[Raw]:
        return (await self._page(client, offset)).get("content") or []

    def _parse(self, raw: Raw, token: str) -> Job:
        loc = raw.get("location") or {}
        parts = (loc.get("city"), loc.get("region"), loc.get("country"))
        place = loc.get("fullLocation") or ", ".join(p for p in parts if p)
        return self.job(
            raw["id"],
            raw["name"],
            f"https://jobs.smartrecruiters.com/{token}/{raw['id']}",
            split_locations(place),
            eastern_date(raw.get("releasedDate")),
        )
