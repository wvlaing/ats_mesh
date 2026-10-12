# ~/src/ats_mesh/adapters/bespoke/ibm.py

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from ats_mesh.helpers.http_utils import Streak, post_with_retry
from ats_mesh.helpers.time_utils import cutoff_date
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


def job_id(raw):
    """Return the jobId from the link, the number IBM shows, else the _id hash."""
    url = raw["_source"].get("url")
    return str(parse_qs(urlparse(url or "").query).get("jobId", [raw["_id"]])[0])


def posted_date(raw):
    """Return the posted date as YYYY-MM-DD, or None.

    The search sorts on dcdate, and each hit's first sort value is that date in
    epoch milliseconds, so the date comes with the list and needs no detail page.
    """
    sort = raw.get("sort") or []
    ms = sort[0] if sort else None
    if not isinstance(ms, int | float) or ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC).date().isoformat()


class IBM:
    """POST search, 30 a page, sorted newest first (dcdate desc). The list is
    walked in order and stops when a few pages in a row hold nothing new (see
    Streak) or a job is older than the cutoff (max age plus a week). Only jobs not
    in `known` and inside the cutoff are returned."""

    def __init__(self, company):
        self.company = company

    def _body(self, offset):
        """Elasticsearch-style search; retrieves jobs without facet aggregations."""
        must = [{"term": {"field_keyword_05": COUNTRY}}] if COUNTRY else []

        return {
            "appId": "careers",
            "scopes": ["careers2"],
            "query": {"bool": {"must": []}},
            "post_filter": {"bool": {"must": must}},
            "size": PAGE_SIZE,
            "from": offset,
            "sort": [
                {"dcdate": "desc"},
                {"_score": "desc"},
            ],
            "lang": "zz",
            "localeSelector": {},
            "sm": {"query": "", "lang": "zz"},
            "_source": SOURCE,
        }

    async def _page(self, client, offset):
        r = await post_with_retry(client, API_URL, json=self._body(offset))
        return r.json()["hits"]

    def parse(self, raw, posted):
        src = raw["_source"]
        place = src.get("field_keyword_19")
        return JobBasic(
            ats=self.company["ats"],
            company_name=self.company["name"],
            ats_job_id=job_id(raw),
            title=src["title"].strip(),
            url=src.get("url"),
            locations=[place] if place else [],
            posted=posted,
        )

    async def fetch_jobs(self, client, known=frozenset()):
        oldest = cutoff_date().isoformat()  # ISO dates compare correctly as text
        streak = Streak(known)
        seen, jobs = set(), []
        offset, total = 0, None
        while total is None or offset < total:
            try:
                hits = await self._page(client, offset)
            except Exception:
                if offset == 0:
                    raise  # nothing to work with, let the run report it
                break  # keep what we have, the rest comes next run
            postings = hits["hits"]
            if not postings:
                break
            total = hits["total"]["value"]
            offset += len(postings)  # step by what came back

            ids = [job_id(r) for r in postings]
            streak.add(ids)
            too_old = False
            for raw, jid in zip(postings, ids, strict=True):
                posted = posted_date(raw)
                if posted and posted < oldest:
                    too_old = True
                elif jid not in known and jid not in seen:
                    seen.add(jid)
                    jobs.append(self.parse(raw, posted))

            if too_old or streak.done:
                break  # newest first, so nothing after this is in range
        return jobs
