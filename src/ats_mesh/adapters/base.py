import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Set

import httpx

from ats_mesh.models import Company, Job


def split_locations(value: str | None) -> list[str]:
    """'New York, NY (HQ); Remote (Canada)' -> ['New York, NY (HQ)', 'Remote (Canada)']"""
    return [p.strip() for p in re.split(r"[;|]", value or "") if p.strip()]


class Adapter(ABC):
    """One way of reading one kind of careers site.

    Subclasses implement fetch_jobs and build every Job through `self.job`. `known`
    holds the job ids already in the database for this company. Adapters that read
    newest-first use it to stop early; the rest can ignore it, since main drops
    known jobs afterwards.
    """

    def __init__(self, company: Company) -> None:
        self.company = company
        self.access = company["access"]

    def job(
        self,
        job_id: object,
        title: str,
        url: str | None,
        locations: Iterable[str | None] = (),
        posted: str | None = None,
    ) -> Job:
        return Job(
            ats=self.company["ats"],
            company_name=self.company["name"],
            ats_job_id=str(job_id),
            title=title.strip(),
            url=url,
            locations=list(
                dict.fromkeys(p for p in locations if p)
            ),  # dedupe, keep order
            posted=posted,
        )

    @abstractmethod
    async def fetch_jobs(
        self, client: httpx.AsyncClient, known: Set[str]
    ) -> list[Job]: ...
