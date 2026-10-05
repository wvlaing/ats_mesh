# ~/src/ats_mesh/adapters/standard/greenhouse.py

from ats_mesh.helpers.http_utils import get_with_retry
from ats_mesh.helpers.location_utils import split_locations
from ats_mesh.helpers.time_utils import fmt_date, to_utc
from ats_mesh.models import JobBasic

BASE_URL = "https://boards-api.greenhouse.io/v1/boards"


class Greenhouse:
    def __init__(self, company):
        self.company = company
        self.token = company["access"]["board_token"]
        self.base_url = f"{BASE_URL}/{self.token}"

    async def fetch_list(self, client):
        """Fetch the job list only (no content=true, so no descriptions).

        Follows 'next' Link headers if present.
        """
        jobs = []
        url = f"{self.base_url}/jobs"
        while url:
            r = await get_with_retry(client, url)
            jobs.extend(r.json()["jobs"])
            url = r.links.get("next", {}).get("url")
        return jobs

    def parse(self, raw):
        return JobBasic(
            ats=self.company["ats"],
            company_id=self.company["company_id"],
            company_name=self.company["name"],
            ats_job_id=str(raw["id"]),
            title=raw["title"].strip(),
            url=raw.get("absolute_url"),
            locations=split_locations((raw.get("location") or {}).get("name")),
            posted=fmt_date(to_utc(raw.get("first_published"))),
        )

    async def fetch_jobs(self, client):
        return [self.parse(r) for r in await self.fetch_list(client)]
