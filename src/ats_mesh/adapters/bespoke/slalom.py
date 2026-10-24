import re
from collections.abc import Set
from contextlib import aclosing

import httpx

from ats_mesh import net
from ats_mesh.adapters.base import Adapter
from ats_mesh.models import Job, Raw

BASE = "https://jobs.slalom.com"
URL = f"{BASE}/13/_portalList"
DETAIL_URL = (
    "https://jobs.slalom.com/13/jobdetail?jobId={}"  # TODO: confirm a real link
)
PAGE_SIZE = 12  # the site's own page size, offset steps by this
QTVC_RE = re.compile(r'"qtvc":"([0-9a-f]+)"')
MAX_PAGES = 200  # safety stop, the list ends on an empty page well before this

SEARCH_PAGE = f"{BASE}/en_US/careersmarketplace/SearchJobs/?listFilterMode=1"

# What Chrome sends for the list request. The site also wants the session cookie
# (ScustomPortal-13) that SEARCH_PAGE sets, so that page is loaded first.
HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Priority": "u=1, i",
    "Referer": SEARCH_PAGE,
    "Sec-Ch-Ua": '"Google Chrome";v="155", "Chromium";v="155", "Not(A:Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# Copied from the site's own request, with the US filter (8095[0] = 132902) in
# `filters`. `qtvc` is left out: the site makes a new one for every session and
# prints it in the search page, so it is read from there (see fetch_jobs).
# The same page load as a browser navigation, not as a background request.
PAGE_HEADERS: dict[str, str] = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": BASE + "/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}

PARAMS: dict[str, str | int] = {
    "uuid": "108bd479-0cf7-4166-9e3b-c9ea7cc0ff5c",
    "hasToIncludePaginationOptions": "false",
    "allowListSorting": "true",
    "fetchJobIdInPeopleLists": "true",
    "listType": "JobList",
    "filters": '{"269":"","4779":"","jobSort":"","jobSortDirection":"","action":"search","listFilterMode":"true","search":"","8095[0]":"132902","timeZone":"America/New_York"}',
    "sort": "postedDate",
    "sortDirection": "DESC",
    "token": "",
    "allowFilteringFromUrlParams": "true",
    "layout": "custom",
    "dynamicValueConfigs": "[]",
    "shouldAddBase64FileFields": "false",
    "searchMode": "ResultsAndCount",
    "pageUrlParams": "{}",
    "links": '{"jobDetailUrlCode":{"targetPageId":null,"targetPageUuid":null,"pageParameters":[],"isSecureUrl":true,"detailJobTypeId":1},"detailPage":{"targetPageId":null,"targetPageUuid":"491b42a2-2ccb-4efc-881d-53a51202954a","pageParameters":[{"key":"jobId","value":"valueFromResult"}],"isSecureUrl":false,"detailJobTypeId":null},"applyPage":{"targetPageId":null,"targetPageUuid":"f7639404-4852-4d75-923c-bf9f198bc76d","pageParameters":[{"key":"jobId","value":"valueFromResult"}],"isSecureUrl":false,"detailJobTypeId":null}}',
    "formId": "tpt_jobSortableForm",
}
LOCATIONS = "schemaField_3_91_3"  # multi-select of cities, e.g. "Phoenix, AZ"


class Slalom(Adapter):
    """Slalom's own careers portal. A GET returns {"results": [...]}, one object per
    job with every field as {"stringValue", "jsonValue", ...}. The list has the title,
    posted date and all locations, so there are no detail requests. It is read
    through to the first empty or repeated page rather than trusting a count.

    The list refuses ("This list is private") without the session's own `qtvc`
    token, which sits in the search page's HTML next to the session cookie."""

    qtvc = ""

    async def _rows(self, client: httpx.AsyncClient, page: int) -> list[Raw]:
        params = {
            **PARAMS,
            "qtvc": self.qtvc,
            "offset": page * PAGE_SIZE,
            "recordsPerPage": PAGE_SIZE,
        }
        r: httpx.Response = await net.get(client, URL, params=params)
        return r.json().get("results") or []

    async def fetch_jobs(self, client: httpx.AsyncClient, known: Set[str]) -> list[Job]:
        # Its own client: browser headers, and the session cookie the search page sets.
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=30, follow_redirects=True, http2=True
        ) as session:
            page: httpx.Response = await session.get(SEARCH_PAGE, headers=PAGE_HEADERS)
            page.raise_for_status()
            if not (token := QTVC_RE.search(page.text)):
                raise ValueError("no qtvc token in the search page")
            self.qtvc = token.group(1)
            return await self._read(session)

    async def _read(self, client: httpx.AsyncClient) -> list[Job]:
        seen: set[int] = set()
        jobs: list[Job] = []
        async with aclosing(
            net.walk(lambda page: self._rows(client, page), limit=MAX_PAGES)
        ) as pages:
            async for rows in pages:
                fresh: list[Raw] = [r for r in rows if r["id"] not in seen]
                if not fresh:
                    break  # empty page, or the same page served again
                seen.update(r["id"] for r in fresh)
                jobs += [self._parse(r) for r in fresh]
        return jobs

    def _parse(self, raw: Raw) -> Job:
        f: Raw = raw["fields"]
        places: list[str] = [
            o["value"]["name"] for o in f[LOCATIONS]["jsonValue"]["value"]
        ]
        return self.job(
            raw["id"],
            f["name"]["stringValue"],
            DETAIL_URL.format(raw["id"]),
            places,
            f["postedDate"]["stringValue"] or None,
        )
