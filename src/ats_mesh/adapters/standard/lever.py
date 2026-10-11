# ~/src/ats_mesh/adapters/standard/lever.py
from datetime import UTC, datetime

from ats_mesh.helpers.http_utils import get_with_retry
from ats_mesh.models import JobBasic

BASE_URL = "https://api.lever.co/v0/postings"


class Lever:
    def __init__(self, company):
        self.company = company
        self.base_url = f"{BASE_URL}/{company['access']['client_name']}"

    async def fetch_list(self, client):
        r = await get_with_retry(client, self.base_url)
        return r.json()  # bare list, not {"jobs": [...]}

    def parse(self, raw):
        cats = raw.get("categories") or {}
        places = [cats.get("location")] + list(cats.get("allLocations") or [])
        places = list(dict.fromkeys(p for p in places if p))  # dedupe, keep order

        created_ms = raw.get("createdAt")
        created_dt = (
            datetime.fromtimestamp(created_ms / 1000, tz=UTC) if created_ms else None
        )

        return JobBasic(
            ats=self.company["ats"],
            company_id=self.company["company_id"],
            company_name=self.company["name"],
            ats_job_id=str(raw["id"]),
            title=raw["text"].strip(),
            url=raw.get("hostedUrl"),
            locations=places,
            posted=created_dt.date().isoformat() if created_dt else None,
        )

    async def fetch_jobs(self, client):
        return [
            self.parse(r)
            for r in await self.fetch_list(client)
            if r.get("isListed", True)
        ]
