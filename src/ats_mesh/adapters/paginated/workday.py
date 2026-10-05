# ~/src/ats_mesh/adapters/paginated/workday.py

import asyncio
import re
from datetime import datetime, timedelta

import httpx

from ats_mesh.helpers.http_utils import post_with_retry
from ats_mesh.helpers.location_utils import split_locations
from ats_mesh.helpers.time_utils import EASTERN
from ats_mesh.models import JobBasic

LIMIT = 20  # Typical workday page limit
US = "bc33aa3152ec42d4995f4791a106ed09"  # Country id for the United States (not always available)


def posted_date(text):
    """
    Converts 'Posted # Days Ago' text into a date.

    EX. 'Posted 5 Days Ago' -> the date 5 days back.
        'Posted 30+ Days Ago' counts as 30.

    """
    if not text:
        return None
    text = text.lower()
    if "today" in text:
        days = 0
    elif "yesterday" in text:
        days = 1
    elif m := re.search(r"\d+", text):
        days = int(m.group())
    else:
        return None
    return (datetime.now(EASTERN).date() - timedelta(days=days)).isoformat()


class Workday:
    def __init__(self, company):
        self.company = company
        access = company["access"]
        self.portal = access["portal"]
        # US only by default, set "facets" in companies.json to override with something else
        self.facets = access.get("facets", {"locationCountry": [US]})
        host, rest = self.portal.split("/wday/cxs/")
        self.job_base = f"{host}/{rest.split('/')[1]}"  # https://host/SITE

    async def _page(self, client, offset):
        r = await post_with_retry(
            client,
            self.portal,
            json={
                "appliedFacets": self.facets,
                "limit": LIMIT,
                "offset": offset,
                "searchText": "",
            },
        )
        return r.json()

    async def fetch_list(self, client):
        try:
            first = await self._page(client, 0)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 400 or not self.facets:
                raise
            self.facets = {}  # If US only fails, trys again without country filter ({} = no filter)
            first = await self._page(client, 0)
        rest = await asyncio.gather(
            *(self._page(client, o) for o in range(LIMIT, first["total"], LIMIT))
        )
        return first["jobPostings"] + [j for p in rest for j in p["jobPostings"]]

    def parse(self, raw):
        path = raw["externalPath"]
        return JobBasic(
            ats=self.company["ats"],
            company_id=self.company["company_id"],
            company_name=self.company["name"],
            ats_job_id=(raw.get("bulletFields") or [path])[0],
            title=raw["title"].strip(),
            url=f"{self.job_base}{path}",
            locations=split_locations(raw.get("locationsText")),
            posted=posted_date(raw.get("postedOn")),
        )

    async def fetch_jobs(self, client):
        return [
            self.parse(r)
            for r in await self.fetch_list(client)
            if r.get("externalPath")
        ]
