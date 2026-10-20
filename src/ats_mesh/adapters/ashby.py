from collections.abc import Set

import httpx

from ats_mesh import net
from ats_mesh.adapters.base import Adapter
from ats_mesh.dates import eastern_date
from ats_mesh.models import Job

BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"


class Ashby(Adapter):
    async def fetch_jobs(self, client: httpx.AsyncClient, known: Set[str]) -> list[Job]:
        r: httpx.Response = await net.get(
            client, f"{BASE_URL}/{self.access['board_name']}"
        )
        return [
            self.job(
                raw["id"],
                raw["title"],
                raw.get("jobUrl"),
                [
                    raw.get("location"),
                    *(s["location"] for s in raw.get("secondaryLocations") or []),
                ],
                eastern_date(raw.get("publishedAt")),
            )
            for raw in r.json()["jobs"]
            if raw.get("isListed", True)
        ]
