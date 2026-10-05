# ~/src/ats_mesh/adapters/standard/smartrecruiters.py

import asyncio

from ats_mesh.helpers.http_utils import get_with_retry
from ats_mesh.helpers.location_utils import split_locations
from ats_mesh.helpers.time_utils import fmt_date, to_utc
from ats_mesh.models import JobBasic

BASE_URL = "https://api.smartrecruiters.com/v1/companies"
PAGE_SIZE = 100  # API maximum per page


class SmartRecruiters:
    def __init__(self, company):
        self.company = company
        self.token = company["access"]["company_identifier"]
        self.base_url = f"{BASE_URL}/{self.token}/postings"

    async def _page(self, client, offset):
        r = await get_with_retry(
            client, self.base_url, params={"limit": PAGE_SIZE, "offset": offset}
        )
        return r.json()

    async def fetch_list(self, client):
        first = await self._page(client, 0)
        rest = await asyncio.gather(
            *(
                self._page(client, o)
                for o in range(PAGE_SIZE, first.get("totalFound", 0), PAGE_SIZE)
            )
        )
        return (first.get("content") or []) + [
            j for p in rest for j in p.get("content") or []
        ]

    def parse(self, raw):
        loc = raw.get("location") or {}
        parts = (loc.get("city"), loc.get("region"), loc.get("country"))
        place = loc.get("fullLocation") or ", ".join(p for p in parts if p)
        return JobBasic(
            ats=self.company["ats"],
            company_id=self.company["company_id"],
            company_name=self.company["name"],
            ats_job_id=str(raw["id"]),
            title=raw["name"].strip(),
            url=f"https://jobs.smartrecruiters.com/{self.token}/{raw['id']}",
            locations=split_locations(place),
            posted=fmt_date(to_utc(raw.get("releasedDate"))),
        )

    async def fetch_jobs(self, client):
        return [self.parse(r) for r in await self.fetch_list(client)]
