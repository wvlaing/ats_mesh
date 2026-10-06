# ~/src/ats_mesh/adapters/bespoke/ibm.py

import asyncio
from urllib.parse import parse_qs, urlparse

from ats_mesh.helpers.http_utils import post_with_retry
from ats_mesh.models import JobBasic

API_URL = "https://www-api.ibm.com/search/api/v2"
COUNTRY = "United States"  # "" = no country filter
PAGE_SIZE = 30  # what the site asks for; the server's maximum is untested
SOURCE = [
    "title",
    "url",
    "field_keyword_17",
    "field_keyword_19",
]  # 17 = Hybrid/Remote, 19 = location


class IBM:
    def __init__(self, company):
        self.company = company

    def _body(self, offset):
        """Elasticsearch-style search. The site's facet counts (aggs) are left out, we only want the jobs."""
        must = [{"term": {"field_keyword_05": COUNTRY}}] if COUNTRY else []
        return {
            "appId": "careers",
            "scopes": ["careers2"],
            "query": {"bool": {"must": []}},
            "post_filter": {"bool": {"must": must}},
            "size": PAGE_SIZE,
            "from": offset,  # unconfirmed: the page 2 request wasn't captured
            "sort": [{"_score": "desc"}, {"pageviews": "desc"}],
            "lang": "zz",
            "localeSelector": {},
            "sm": {"query": "", "lang": "zz"},
            "_source": SOURCE,
        }

    async def _page(self, client, offset):
        r = await post_with_retry(client, API_URL, json=self._body(offset))
        return r.json()["hits"]

    async def fetch_list(self, client):
        first = await self._page(client, 0)
        postings = first["hits"]
        step = len(postings)  # step by what came back in case the server caps the size
        if not step:
            return postings
        rest = await asyncio.gather(
            *(self._page(client, o) for o in range(step, first["total"]["value"], step))
        )
        return postings + [j for p in rest for j in p["hits"]]

    def parse(self, raw):
        src = raw["_source"]
        url = src.get("url")
        # jobId in the link is the number IBM shows, the long _id hash is the fallback
        job_id = parse_qs(urlparse(url or "").query).get("jobId", [raw["_id"]])[0]
        place = src.get("field_keyword_19")
        return JobBasic(
            ats=self.company["ats"],
            company_id=self.company["company_id"],
            company_name=self.company["name"],
            ats_job_id=str(job_id),
            title=src["title"].strip(),
            url=url,
            locations=[place] if place else [],
            posted=None,  # the search results carry no date
        )

    async def fetch_jobs(self, client):
        return [self.parse(r) for r in await self.fetch_list(client)]
