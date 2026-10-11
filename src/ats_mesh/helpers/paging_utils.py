# ~/src/ats_mesh/helpers/http_utils.py

import asyncio

RETRY_STATUS = {429, 500, 502, 503, 504}


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
