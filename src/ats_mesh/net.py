import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable, Set
from typing import TypedDict, Unpack

import httpx

from ats_mesh.models import Raw

RETRY_STATUS: set[int] = {429, 500, 502, 503, 504}

# What a bad response from a careers site looks like. Used to keep one failing
# company from sinking the run, and to end a page walk early.
FETCH_ERRORS = (httpx.HTTPError, KeyError, TypeError, ValueError)

EXTRA_PAGES = 2  # known-only pages to look at after the first one, before stopping


class RequestOptions(TypedDict, total=False):
    params: dict[str, str | int]
    json: Raw
    timeout: float


async def request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retries: int = 4,
    **options: Unpack[RequestOptions],
) -> httpx.Response:
    """Request that backs off and retries on 429/5xx, then raises on any error."""
    for attempt in range(1, retries + 2):
        r = await client.request(method, url, **options)
        if r.status_code in RETRY_STATUS and attempt <= retries:
            await asyncio.sleep(2**attempt)
            continue
        r.raise_for_status()
        return r
    raise AssertionError("unreachable")


async def get(
    client: httpx.AsyncClient,
    url: str,
    *,
    retries: int = 4,
    **options: Unpack[RequestOptions],
) -> httpx.Response:
    return await request(client, "GET", url, retries=retries, **options)


async def post(
    client: httpx.AsyncClient,
    url: str,
    *,
    retries: int = 4,
    **options: Unpack[RequestOptions],
) -> httpx.Response:
    return await request(client, "POST", url, retries=retries, **options)


async def gather_lists[T](calls: Iterable[Awaitable[list[T]]]) -> list[T]:
    """Run the awaitables together and join the lists they return, in order."""
    return [item for page in await asyncio.gather(*calls) for item in page]


async def walk[T](
    fetch: Callable[[int], Awaitable[T]], *, start: int = 0, limit: int
) -> AsyncGenerator[T]:
    """Yield fetch(start), fetch(start + 1), ... for up to `limit` pages.

    The next page is requested while the caller works on the current one. An error
    on the first page is raised, so the run reports it. An error on a later page
    just ends the walk: the caller keeps what it has and the rest comes next run.
    Use it as `async with aclosing(walk(...)) as pages`, so a page requested
    ahead is cancelled when the caller stops early.
    """
    pending = asyncio.create_task(fetch(start))  # ty: ignore[invalid-argument-type]
    try:
        for page in range(start, start + limit):
            try:
                result = await pending
            except FETCH_ERRORS:
                if page == start:
                    raise
                return
            pending = asyncio.create_task(coro=fetch(page + 1))  # ty: ignore[invalid-argument-type]
            yield result
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


class Streak:
    """Feed it each page's ids in order. `done` goes True after 1 + EXTRA_PAGES
    pages in a row with nothing new."""

    def __init__(self, known: Set[str], extra: int = EXTRA_PAGES) -> None:
        self.known = known
        self.extra: int = extra
        self.run = 0

    def add(self, ids: Iterable[str]) -> None:
        ids: list[str] = list(ids)
        if not ids:
            return  # an empty or failed page says nothing, don't count it
        self.run = 0 if any(i not in self.known for i in ids) else self.run + 1

    @property
    def done(self) -> bool:
        return self.run > self.extra
