# ~/src/ats_mesh/adapters/bespoke/docusign.py

import asyncio
import math

from ats_mesh.helpers.http_utils import get_with_retry
from ats_mesh.helpers.location_utils import split_locations
from ats_mesh.helpers.time_utils import fmt_date, to_utc
from ats_mesh.models import JobBasic

URL = "https://careers.docusign.com/api/jobs"
PARAMS = {
    "limit": 100,
    "sortBy": "relevance",
    "descending": "false",
    "internal": "false",
}  # limit is a guess


class Docusign:
    """Paged GET returns {"jobs": [{"data": {...}}], "totalCount": N}."""

    def __init__(self, company):
        self.company = company

    async def _page(self, client, page):
        r = await get_with_retry(client, URL, params={**PARAMS, "page": page})
        return r.json()

    async def fetch_list(self, client):
        first = await self._page(client, 1)
        jobs = first.get("jobs") or []
        if not jobs:
            return jobs
        pages = math.ceil(
            first.get("totalCount", 0) / len(jobs)
        )  # by what came back, in case the server caps the limit
        rest = await asyncio.gather(
            *(self._page(client, p) for p in range(2, pages + 1))
        )
        return jobs + [j for p in rest for j in p.get("jobs") or []]

    def parse(self, raw):
        d = raw["data"]
        return JobBasic(
            ats=self.company["ats"],
            company_id=self.company["company_id"],
            company_name=self.company["name"],
            ats_job_id=str(d["req_id"]),
            title=d["title"].strip(),
            url=d.get("canonical_url") or d.get("apply_url"),
            locations=split_locations(d.get("full_location")),
            posted=fmt_date(to_utc(d.get("posted_date"))),
        )

    async def fetch_jobs(self, client):
        return [self.parse(r) for r in await self.fetch_list(client)]
