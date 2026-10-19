from collections.abc import Set

import httpx

from ats_mesh import net
from ats_mesh.adapters.base import Adapter
from ats_mesh.dates import epoch_ms_date
from ats_mesh.models import Job

BASE_URL = "https://api.lever.co/v0/postings"


class Lever(Adapter):
    async def fetch_jobs(self, client: httpx.AsyncClient, known: Set[str]) -> list[Job]:
        r = await net.get(client, f"{BASE_URL}/{self.access['client_name']}")
        jobs: list[Job] = []
        for raw in r.json():  # a bare list, not {"jobs": [...]}
            if not raw.get("isListed", True):
                continue
            cats = raw.get("categories") or {}
            jobs.append(
                self.job(
                    raw["id"],
                    raw["text"],
                    raw.get("hostedUrl"),
                    [cats.get("location"), *(cats.get("allLocations") or [])],
                    epoch_ms_date(raw.get("createdAt")),
                )
            )
        return jobs
