from collections.abc import Set

import httpx

from ats_mesh import net
from ats_mesh.adapters.base import Adapter, split_locations
from ats_mesh.dates import eastern_date
from ats_mesh.models import Job

BASE_URL = "https://boards-api.greenhouse.io/v1/boards"


class Greenhouse(Adapter):
    async def fetch_jobs(self, client: httpx.AsyncClient, known: Set[str]) -> list[Job]:
        """The job list only (no content=true, so no descriptions). Follows 'next'
        Link headers if present."""
        jobs: list[Job] = []
        url: str | None = f"{BASE_URL}/{self.access['board_token']}/jobs"
        while url:
            r = await net.get(client, url)
            jobs += [
                self.job(
                    raw["id"],
                    raw["title"],
                    raw.get("absolute_url"),
                    split_locations((raw.get("location") or {}).get("name")),
                    eastern_date(raw.get("first_published")),
                )
                for raw in r.json()["jobs"]
            ]
            url = r.links.get("next", {}).get("url")
        return jobs
