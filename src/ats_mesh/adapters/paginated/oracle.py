# ~/src/ats_mesh/adapters/paginated/oracle.py

import asyncio

from ats_mesh.helpers.http_utils import get_with_retry
from ats_mesh.models import JobBasic

API_PATH = "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
EXPAND = "requisitionList.secondaryLocations"
PAGE_SIZE = 25  # what the site asks for; the server's maximum is untested


def place(entry):
    """A secondary location may be a string or a dict with a name (unconfirmed)."""
    if isinstance(entry, dict):
        return entry.get("Name") or entry.get("LocationName")
    return entry


class Oracle:
    def __init__(self, company):
        self.company = company
        access = company["access"]
        self.host = access["host"].strip().removeprefix("https://").rstrip("/")
        self.site = access["site"]
        self.location_id = access.get("location_id")
        self.posted_within_days = access.get("posted_within_days")
        self.job_base = (
            f"https://{self.host}/hcmUI/CandidateExperience/en/sites/{self.site}/job"
        )

    def _url(self, offset):
        """
        Built by hand (not via params=) so the finder string goes out exactly the way the website sends it. Look at the example companies.json to get a better idea, but it's a bit more complicatd than most
        """

        finder = (
            f"findReqs;siteNumber={self.site},limit={PAGE_SIZE},"
            f"sortBy=POSTING_DATES_DESC,offset={offset}"
        )
        if self.location_id:
            finder += f",locationId={self.location_id}"
        if self.posted_within_days:
            finder += (
                ",lastSelectedFacet=POSTING_DATES"
                f",selectedPostingDatesFacet={self.posted_within_days}"
            )
        return f"https://{self.host}{API_PATH}?onlyData=true&expand={EXPAND}&finder={finder}"

    async def _page(self, client, offset):
        """One page: the payload is a single item holding the total and the jobs."""
        r = await get_with_retry(client, self._url(offset))
        items = r.json().get("items") or []
        return items[0] if items else {}

    async def fetch_list(self, client):
        first = await self._page(client, 0)
        postings = first.get("requisitionList") or []
        step = len(postings)  # step by what came back in case the server caps the limit
        if not step:
            return postings
        rest = await asyncio.gather(
            *(
                self._page(client, o)
                for o in range(step, first.get("TotalJobsCount", 0), step)
            )
        )
        return postings + [j for p in rest for j in p.get("requisitionList") or []]

    def parse(self, raw):
        job_id = str(raw["Id"])
        places = [raw.get("PrimaryLocation")]
        places += [place(s) for s in raw.get("secondaryLocations") or []]
        return JobBasic(
            ats=self.company["ats"],
            company_id=self.company["company_id"],
            company_name=self.company["name"],
            ats_job_id=job_id,
            title=raw["Title"].strip(),
            url=f"{self.job_base}/{job_id}",
            locations=[p for p in places if p],
            posted=raw.get("PostedDate"),  # already a plain date
        )

    async def fetch_jobs(self, client):
        return [self.parse(r) for r in await self.fetch_list(client)]
