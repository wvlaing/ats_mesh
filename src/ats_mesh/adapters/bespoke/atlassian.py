# ~/src/ats_mesh/adapters/bespoke/atlassian.py

from ats_mesh.helpers.http_utils import get_with_retry
from ats_mesh.models import JobBasic

URL = "https://www.atlassian.com/endpoint/careers/listings"


def keep(places):
    """US jobs, plus plain 'Remote - Remote' ones, unless they also list India."""
    if any("United States" in p for p in places):
        return True
    return "Remote - Remote" in places and not any("India" in p for p in places)


class Atlassian:
    """One GET returns a plain list of every job (iCIMS behind the scenes)."""

    def __init__(self, company):
        self.company = company

    async def fetch_list(self, client):
        r = await get_with_retry(client, URL)
        return r.json()

    def parse(self, raw):
        places = [
            " ".join(p.split()) for p in raw.get("locations") or []
        ]  # collapses their messy spacing
        return JobBasic(
            ats=self.company["ats"],
            company_id=self.company["company_id"],
            company_name=self.company["name"],
            ats_job_id=str(raw["id"]),
            title=raw["title"].strip(),
            url=raw["portalJobPost"]["portalUrl"],
            locations=list(dict.fromkeys(places)),
            posted=(raw["portalJobPost"].get("updatedDate") or "")[:10]
            or None,  # edit date, closest thing they give
        )

    async def fetch_jobs(self, client):
        jobs = [self.parse(r) for r in await self.fetch_list(client)]
        return [j for j in jobs if keep(j.locations)]
