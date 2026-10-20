from collections.abc import Set
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from ats_mesh import net
from ats_mesh.adapters.base import Adapter
from ats_mesh.dates import cutoff, epoch_ms_date
from ats_mesh.models import Job, Raw
from ats_mesh.net import FETCH_ERRORS, Streak

API_URL = "https://www-api.ibm.com/search/api/v2"
COUNTRY = "United States"  # "" = no country filter
PAGE_SIZE = 30  # what the site asks for; the server's maximum is untested
# 17 = Hybrid/Remote, 19 = location
SOURCE: list[str] = ["title", "url", "field_keyword_17", "field_keyword_19"]


def job_id(raw: Raw) -> str:
    """The jobId from the link (the number IBM shows), else the _id hash."""
    url = raw["_source"].get("url")
    return str(parse_qs(urlparse(url or "").query).get("jobId", [raw["_id"]])[0])


def posted_date(raw: Raw) -> str | None:
    """The search sorts on dcdate, and each hit's first sort value is that date in
    epoch milliseconds, so the date comes with the list and needs no detail page."""
    sort = raw.get("sort") or []
    return epoch_ms_date(sort[0] if sort else None)


class IBM(Adapter):
    """POST search, 30 a page, newest first (dcdate desc). Stops when a few pages in
    a row hold nothing new (see Streak) or a job is older than the cutoff."""

    def _body(self, offset: int) -> Raw:
        """Elasticsearch-style search, without facet aggregations."""
        country = self.access.get("country", COUNTRY)
        must: list[dict[str, dict[str, Any]]] = (
            [{"term": {"field_keyword_05": country}}] if country else []
        )
        return {
            "appId": "careers",
            "scopes": ["careers2"],
            "query": {"bool": {"must": []}},
            "post_filter": {"bool": {"must": must}},
            "size": PAGE_SIZE,
            "from": offset,
            "sort": [{"dcdate": "desc"}, {"_score": "desc"}],
            "lang": "zz",
            "localeSelector": {},
            "sm": {"query": "", "lang": "zz"},
            "_source": SOURCE,
        }

    async def _page(self, client: httpx.AsyncClient, offset: int) -> Raw:
        r: httpx.Response = await net.post(client, API_URL, json=self._body(offset))
        return r.json()["hits"]

    async def fetch_jobs(self, client: httpx.AsyncClient, known: Set[str]) -> list[Job]:
        oldest: str = cutoff()
        streak = Streak(known)
        jobs: list[Job] = []
        offset, total = 0, 1
        while offset < total:
            try:
                hits = await self._page(client, offset)
            except FETCH_ERRORS:
                if offset == 0:
                    raise  # nothing to work with, let the run report it
                break  # keep what we have, the rest comes next run
            postings: list[Raw] = hits["hits"]
            if not postings:
                break
            total = hits["total"]["value"]
            offset += len(postings)  # step by what came back

            streak.add(job_id(raw) for raw in postings)
            too_old = False
            for raw in postings:
                posted: str | None = posted_date(raw)
                if posted and posted < oldest:
                    too_old = True
                    continue
                src = raw["_source"]
                jobs.append(
                    self.job(
                        job_id(raw),
                        src["title"],
                        src.get("url"),
                        [src.get("field_keyword_19")],
                        posted,
                    )
                )
            if too_old or streak.done:
                break  # newest first, so nothing after this is in range
        return jobs
