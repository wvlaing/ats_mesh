# ~/src/ats_mesh/adapters/standard/ashby.py

from ats_mesh.helpers.http_utils import get_with_retry
from ats_mesh.helpers.time_utils import fmt_date, to_utc
from ats_mesh.models import JobBasic

BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"


class Ashby:
    def __init__(self, company):
        self.company = company
        self.base_url = f"{BASE_URL}/{company['access']['board_name']}"

    async def fetch_list(self, client):
        r = await get_with_retry(client, self.base_url)
        return r.json()["jobs"]

    def parse(self, raw):
        places = [raw.get("location")] + [
            s["location"] for s in raw.get("secondaryLocations") or []
        ]
        return JobBasic(
            ats=self.company["ats"],
            company_id=self.company["company_id"],
            company_name=self.company["name"],
            ats_job_id=str(raw["id"]),
            title=raw["title"].strip(),
            url=raw.get("jobUrl"),
            locations=[p for p in places if p],
            posted=fmt_date(to_utc(raw.get("publishedAt"))),
        )

    async def fetch_jobs(self, client):
        return [
            self.parse(r)
            for r in await self.fetch_list(client)
            if r.get("isListed", True)
        ]
