import asyncio
import json
import math
import random
import re
from collections import Counter
from datetime import UTC, datetime, timezone
from pathlib import Path

import httpx

try:
    import h2

    HTTP2 = True
except ImportError:
    HTTP2 = False

TEXAS_ONLY = True
CONCURRENCY = 3
SORT = "newest"

BASE = "https://jobs.apple.com"
SEARCH_URL = f"{BASE}/api/v1/search"
CSRF_URL = f"{BASE}/api/v1/CSRFToken"
LOCATION = "postLocation-state995" if TEXAS_ONLY else "postLocation-USA"
LABEL = "texas" if TEXAS_ONLY else "us"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Browserlocale": "en-us",
    "Locale": "en_US",
    "Origin": BASE,
    "Referer": f"{BASE}/en-us/search?sort={SORT}",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Priority": "u=1, i",
    "Sec-Ch-Ua": '"Chromium";v="154", "Google Chrome";v="154", "Not A(Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

LADDER = [
    "same_token",
    "new_token",
    "new_session",
    "new_session",
    "new_session",
    "new_session",
]

stats = Counter()
ip_ok = Counter()
ip_empty = Counter()


def payload(page):
    return {
        "query": "",
        "filters": {"locations": [LOCATION]},
        "page": page,
        "locale": "en-us",
        "sort": SORT,
        "format": {"longDate": "MMMM D, YYYY", "mediumDate": "MMM D, YYYY"},
    }


def server_ip(r):
    try:
        return r.extensions["network_stream"].get_extra_info("server_addr")[0]
    except Exception:
        return "?"


async def get_token(client):
    r = await client.get(CSRF_URL)
    r.raise_for_status()
    return r.headers["X-Apple-CSRF-Token"]


async def open_session():
    client = httpx.AsyncClient(
        headers=HEADERS, timeout=30, follow_redirects=True, http2=HTTP2
    )
    try:
        return client, await get_token(client)
    except Exception:
        await client.aclose()
        raise


async def search(client, token, page):
    try:
        r = await client.post(
            SEARCH_URL, json=payload(page), headers={"X-Apple-CSRF-Token": token}
        )
        r.raise_for_status()
        body = r.json()
    except (httpx.HTTPError, ValueError) as e:
        print(f"  page {page}: request error {e!r}")
        return {}, [], "?"
    data = (body.get("res", body) if isinstance(body, dict) else {}) or {}
    return data, data.get("searchResults") or [], server_ip(r)


async def fetch_page(page):
    client = None
    try:
        client, token = await open_session()
        data, results, ip = await search(client, token, page)
        if results:
            stats["first_try_ok"] += 1
            ip_ok[ip] += 1
            return data, results
        ip_empty[ip] += 1

        for attempt, step in enumerate(LADDER, 1):
            print(
                f"page {page}: empty from {ip}, retry {attempt}/{len(LADDER)} ({step})"
            )
            await asyncio.sleep(0.5 * attempt + random.random())
            try:
                if step == "new_token":
                    token = await get_token(client)
                elif step == "new_session":
                    await client.aclose()
                    client, token = await open_session()
            except httpx.HTTPError as e:
                print(f"  page {page}: {step} failed {e!r}")
                continue
            data, results, ip = await search(client, token, page)
            if results:
                stats[f"{step}_ok"] += 1
                ip_ok[ip] += 1
                return data, results
            ip_empty[ip] += 1

        stats["gave_up"] += 1
        return {}, []
    except httpx.HTTPError as e:
        print(f"page {page}: session error {e!r}")
        return {}, []
    finally:
        if client is not None:
            await client.aclose()


async def crawl_pages(pages):
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(page):
        async with sem:
            await asyncio.sleep(random.uniform(0.2, 0.6))
            _data, results = await fetch_page(page)
            return page, results

    return await asyncio.gather(*(one(p) for p in pages))


def strip_html(text):
    return re.sub(r"<.*?>", "", text or "").strip()


def normalize(j):
    pos_id = j.get("positionId") or j.get("reqId") or j.get("id")
    slug = j.get("transformedPostingTitle") or ""
    url = f"{BASE}/en-us/details/{pos_id}" + (f"/{slug}" if slug else "")
    locs = j.get("locations") or []
    return {
        "id": pos_id,
        "req_id": j.get("reqId"),
        "title": j.get("postingTitle"),
        "company": "Apple",
        "team": (j.get("team") or {}).get("teamName"),
        "locations": [loc["name"] for loc in locs if loc.get("name")],
        "location_ids": [
            loc["postLocationId"] for loc in locs if loc.get("postLocationId")
        ],
        "multi_location": j.get("isMultiLocation"),
        "home_office": j.get("homeOffice"),
        "posted": j.get("postingDate"),
        "posted_gmt": j.get("postDateInGMT"),
        "summary": strip_html(j.get("jobSummary")),
        "url": url,
    }


async def main():
    jobs = {}

    def add(results):
        for raw in results:
            job = normalize(raw)
            jobs[job["id"] or job["url"]] = job

    print(f"location={LOCATION} sort={SORT} concurrency={CONCURRENCY} http2={HTTP2}")
    data, results = await fetch_page(1)
    if not results:
        raise SystemExit("Page 1 returned nothing, giving up")
    total = data.get("totalRecords") or len(results)
    per_page = len(results)
    max_page = math.ceil(total / per_page)
    add(results)
    print(f"total {total}, {max_page} pages of {per_page}")

    pending = list(range(2, max_page + 1))
    for round_no in range(4):
        if not pending:
            break
        if round_no:
            print(f"\nretry round {round_no}, missing pages: {pending}")
            await asyncio.sleep(5)
        still = []
        for page, results in await crawl_pages(pending):
            if results:
                add(results)
            else:
                still.append(page)
        pending = still
        print(f"{len(jobs)}/{total} unique so far")

    for _ in range(2):
        data, results = await fetch_page(1)
        if results:
            add(results)
        new_total = data.get("totalRecords") or total
        if new_total != total:
            print(f"total changed {total} -> {new_total}")
        total = new_total
        if len(jobs) >= total:
            break
        max_page = math.ceil(total / per_page)
        print(f"{len(jobs)}/{total}, sweeping all pages again")
        for _page, results in await crawl_pages(range(2, max_page + 1)):
            if results:
                add(results)

    if len(jobs) < total:
        print(f"WARNING: got {len(jobs)} of {total}")

    print("\nwhich retry step first worked:")
    for key, count in stats.most_common():
        print(f"  {key}: {count}")
    print("server ip (ok / empty):")
    for ip in sorted(set(ip_ok) | set(ip_empty)):
        print(f"  {ip}: {ip_ok[ip]} / {ip_empty[ip]}")

    ordered = sorted(jobs.values(), key=lambda j: j["posted_gmt"] or "", reverse=True)
    today = datetime.now(UTC).astimezone()
    desktop = Path.home() / "Desktop"
    out = (desktop if desktop.exists() else Path.home()) / (
        f"apple_jobs_{LABEL}_{today:%Y-%m-%d}.json"
    )
    out.write_text(
        json.dumps(
            {
                "source": BASE,
                "location": "Texas" if TEXAS_ONLY else "United States",
                "sort": SORT,
                "scraped_at": datetime.now(UTC).isoformat(),
                "count": len(ordered),
                "jobs": ordered,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved {len(ordered)} jobs to {out}")


if __name__ == "__main__":
    asyncio.run(main())
