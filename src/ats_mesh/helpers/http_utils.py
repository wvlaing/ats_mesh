# ~/src/ats_mesh/helpers/http_utils.py

import asyncio

RETRY_STATUS = {429, 500, 502, 503, 504}

EXTRA = 2  # known-only pages to look at after the first one, before stopping


async def request_with_retry(client, method, url, *, retries=4, **kwargs):
    """Request that backs off and retries on 429/5xx, then raises on any error."""
    attempt = 0
    while True:
        r = await client.request(method, url, **kwargs)
        if r.status_code in RETRY_STATUS and attempt < retries:
            attempt += 1
            await asyncio.sleep(2**attempt)
            continue
        r.raise_for_status()
        return r


async def get_with_retry(client, url, **kwargs):
    return await request_with_retry(client, "GET", url, **kwargs)


async def post_with_retry(client, url, **kwargs):
    return await request_with_retry(client, "POST", url, **kwargs)


class Streak:
    """Feed it each page's ids in order. .done goes True after 1 + EXTRA
    pages in a row with nothing new."""

    def __init__(self, known, extra=EXTRA):
        self.known, self.extra, self.run = known, extra, 0

    def add(self, ids):
        if not ids:
            return  # an empty or failed page says nothing, don't count it
        self.run = 0 if any(i not in self.known for i in ids) else self.run + 1

    @property
    def done(self):
        return self.run > self.extra
