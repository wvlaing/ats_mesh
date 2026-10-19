from collections.abc import Set

import httpx

from ats_mesh import net
from ats_mesh.adapters.base import Adapter
from ats_mesh.models import Job

URL = "https://www.atlassian.com/endpoint/careers/listings"


def keep(places: list[str]) -> bool:
    """US jobs, plus plain 'Remote - Remote' ones, unless they also list India."""
    if any("United States" in p for p in places):
        return True
    return "Remote - Remote" in places and not any("India" in p for p in places)


class Atlassian(Adapter):
    """One GET returns a plain list of every job (iCIMS behind the scenes)."""

    async def fetch_jobs(self, client: httpx.AsyncClient, known: Set[str]) -> list[Job]:
        r = await net.get(client, self.access.get("portal", URL))
        jobs: list[Job] = []
        for raw in r.json():
            places = [" ".join(p.split()) for p in raw.get("locations") or []]  # their spacing is messy
            if not keep(places):
                continue
            post = raw["portalJobPost"]
            jobs.append(
                self.job(
                    raw["id"],
                    raw["title"],
                    post["portalUrl"],
                    places,
                    (post.get("updatedDate") or "")[:10] or None,  # edit date, closest they give
                )
            )
        return jobs
