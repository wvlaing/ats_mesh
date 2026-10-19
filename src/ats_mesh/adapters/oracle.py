from collections.abc import Set

import httpx

from ats_mesh import net
from ats_mesh.adapters.base import Adapter
from ats_mesh.models import Company, Job, Raw

API_PATH = "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
EXPAND = "requisitionList.secondaryLocations"
PAGE_SIZE = 25  # what the site asks for; the server's maximum is untested


def place(entry: str | Raw) -> str | None:
    """A secondary location may be a string or a dict with a name (unconfirmed)."""
    if isinstance(entry, dict):
        return entry.get("Name") or entry.get("LocationName")
    return entry


class Oracle(Adapter):
    def __init__(self, company: Company) -> None:
        super().__init__(company)
        self.host: str = self.access["host"].strip().removeprefix("https://").rstrip("/")
        self.site: str = self.access["site"]
        self.job_base = f"https://{self.host}/hcmUI/CandidateExperience/en/sites/{self.site}/job"

    def _url(self, offset: int) -> str:
        """Built by hand (not via params=) so the finder string goes out exactly the
        way the website sends it. See example_companies.json for the options."""
        finder = (
            f"findReqs;siteNumber={self.site},limit={PAGE_SIZE},"
            f"sortBy=POSTING_DATES_DESC,offset={offset}"
        )
        if location_id := self.access.get("location_id"):
            finder += f",locationId={location_id}"
        if days := self.access.get("posted_within_days"):
            finder += f",lastSelectedFacet=POSTING_DATES,selectedPostingDatesFacet={days}"
        return f"https://{self.host}{API_PATH}?onlyData=true&expand={EXPAND}&finder={finder}"

    async def _page(self, client: httpx.AsyncClient, offset: int) -> Raw:
        """One page: the payload is a single item holding the total and the jobs."""
        items = (await net.get(client, self._url(offset))).json().get("items") or []
        return items[0] if items else {}

    async def _postings(self, client: httpx.AsyncClient, offset: int) -> list[Raw]:
        return (await self._page(client, offset)).get("requisitionList") or []

    async def fetch_jobs(self, client: httpx.AsyncClient, known: Set[str]) -> list[Job]:
        first = await self._page(client, 0)
        postings: list[Raw] = first.get("requisitionList") or []
        step = len(postings)  # step by what came back in case the server caps the limit
        if not step:
            return []
        rest = await net.gather_lists(
            self._postings(client, offset)
            for offset in range(step, first.get("TotalJobsCount", 0), step)
        )
        return [self._parse(raw) for raw in postings + rest]

    def _parse(self, raw: Raw) -> Job:
        places = [raw.get("PrimaryLocation")]
        places += [place(s) for s in raw.get("secondaryLocations") or []]
        return self.job(
            raw["Id"],
            raw["Title"],
            f"{self.job_base}/{raw['Id']}",
            places,
            raw.get("PostedDate"),  # already a plain date
        )
