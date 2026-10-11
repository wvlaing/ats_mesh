import asyncio
import html as htmllib
import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx

BASE = "https://careers.ey.com"
URL = f"{BASE}/search/"
PARAMS = {
    "q": "",
    "q2": "",
    "alertId": "",
    "locationsearch": "",
    "title": "",
    "location": "US",
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
    ),
}
PAGE_SIZE = 25
CONCURRENCY = 6
MAX_PAGES = 40
DESKTOP = Path.home() / "Desktop"
REPORT = DESKTOP / "ey_report.txt"
JOBS_JSON = DESKTOP / "ey_jobs.json"

META_RE = re.compile(
    r'<meta\s+itemprop="(addressLocality|addressRegion|postalCode|addressCountry|datePosted)"'
    r'\s+content="([^"]*)"',
    re.IGNORECASE,
)
ID_RE = re.compile(r"/(\d+)/?$")

lines = []


def out(text=""):
    print(text)
    lines.append(text)


def clean(s):
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def parse_rows(page):
    rows = []
    for chunk in page.split('<tr class="data-row">')[1:]:
        href = re.search(
            r'class="jobTitle-link"[^>]*href="([^"]+)"', chunk
        ) or re.search(r'href="([^"]+)"[^>]*class="jobTitle-link"', chunk)
        title = re.search(r'class="jobTitle-link"[^>]*>([^<]+)<', chunk)
        loc = re.search(r'class="jobLocation">(.*?)</span>', chunk, re.DOTALL)
        loc_text = clean(loc.group(1)) if loc else ""
        more = re.search(r"\+(\d+) more", loc_text)
        href_val = htmllib.unescape(href.group(1)) if href else ""
        job_id = ID_RE.search(href_val)
        rows.append(
            {
                "id": job_id.group(1) if job_id else None,
                "href": href_val,
                "title": clean(title.group(1)) if title else "",
                "list_location": loc_text,
                "more": int(more.group(1)) if more else 0,
            }
        )
    return rows


def parse_posted(value):
    """'Sun Sep 13 00:00:00 UTC 2026' -> '2026-09-13'"""
    try:
        return datetime.strptime(value, "%a %b %d %H:%M:%S UTC %Y").date().isoformat()
    except ValueError:
        return None


def parse_detail(page):
    places, cur, posted = [], {}, None
    for key, val in META_RE.findall(page):
        key = key.lower()
        if key == "dateposted":
            posted = parse_posted(val)
            continue
        if key in cur:  # a repeated key means the next location started
            places.append(cur)
            cur = {}
        cur[key] = htmllib.unescape(val).strip()
    if cur:
        places.append(cur)
    return places, posted


def place_str(p):
    parts = [p.get("addresslocality"), p.get("addressregion"), p.get("addresscountry")]
    return ", ".join(x for x in parts if x)


async def get_page(client, url, params=None):
    for attempt in range(3):
        try:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.text
        except httpx.HTTPError:
            await asyncio.sleep(1 + attempt)
    return None


async def fetch_list(client):
    rows = []
    for p in range(MAX_PAGES):
        page = await get_page(client, URL, {**PARAMS, "startrow": p * PAGE_SIZE})
        if page is None:
            out(f"list page {p} failed after retries")
            break
        got = parse_rows(page)
        if not got:
            break
        for r in got:
            r["pos"] = len(rows)  # order the server served it in
            r["page"] = p
            rows.append(r)
    return rows


async def ids_for(client, extra, pages=2):
    ids = []
    for p in range(pages):
        page = await get_page(
            client, URL, {**PARAMS, **extra, "startrow": p * PAGE_SIZE}
        )
        ids.extend(r["id"] for r in parse_rows(page or ""))
    return ids


async def fetch_detail(client, sem, row):
    async with sem:
        page = await get_page(client, BASE + row["href"])
    if page is None:
        return {**row, "ok": False, "places": [], "posted": None}
    places, posted = parse_detail(page)
    return {**row, "ok": True, "places": places, "posted": posted}


def order_report(ok):
    dated = [j for j in ok if j["posted"]]
    dates = [j["posted"] for j in dated]
    if len(dates) < 2:
        out("not enough dates to judge order")
        return
    ups = [(a, b) for a, b in zip(dated, dated[1:]) if b["posted"] > a["posted"]]
    downs = sum(1 for a, b in zip(dates, dates[1:]) if b < a)
    ties = sum(1 for a, b in zip(dates, dates[1:]) if b == a)
    out(
        f"adjacent pairs: {downs} older-after-newer, {len(ups)} newer-after-older, {ties} same day"
    )
    if not ups:
        verdict = "NEWEST FIRST throughout"
    elif not downs:
        verdict = "OLDEST FIRST throughout"
    else:
        verdict = "MIXED, not sorted by posted date"
    out(f"verdict by posted date: {verdict}")
    out(f"first row posted {dates[0]}, last row posted {dates[-1]}")
    out(f"newest {max(dates)}, oldest {min(dates)}")
    for a, b in ups[:6]:
        out(
            f"    break at pos {a['pos']} -> {b['pos']}: {a['posted']} then {b['posted']}"
        )

    out("\nposted date range per page (pos order):")
    by_page = {}
    for j in dated:
        by_page.setdefault(j["page"], []).append(j["posted"])
    for p, ds in sorted(by_page.items()):
        out(f"    page {p:>2}: {max(ds)} to {min(ds)}")


async def main():
    t0 = time.time()
    limits = httpx.Limits(max_connections=CONCURRENCY)
    async with httpx.AsyncClient(
        timeout=30, headers=HEADERS, follow_redirects=True, limits=limits
    ) as client:
        rows = await fetch_list(client)
        out(f"list: {len(rows)} rows, {len({r['id'] for r in rows})} unique ids")

        # does the default order match the site's own sort links?
        default_ids = [r["id"] for r in rows[: 2 * PAGE_SIZE]]
        desc_ids = await ids_for(
            client, {"sortColumn": "referencedate", "sortDirection": "desc"}
        )
        asc_ids = await ids_for(
            client, {"sortColumn": "referencedate", "sortDirection": "asc"}
        )
        out(
            f"default order == explicit referencedate desc (first 50): {default_ids == desc_ids}"
        )
        out(f"explicit asc differs from desc: {asc_ids != desc_ids}")
        out(
            f"asc first id {asc_ids[0] if asc_ids else None}, desc first id {desc_ids[0] if desc_ids else None}"
        )

        # raw location block of the first job, to confirm the meta structure
        page = await get_page(client, BASE + rows[0]["href"])
        i = page.find('itemprop="addressRegion"')
        out("\nraw block around first addressRegion:")
        out("  " + " ".join(page[max(0, i - 600) : i + 500].split()))

        sem = asyncio.Semaphore(CONCURRENCY)
        jobs = await asyncio.gather(*(fetch_detail(client, sem, r) for r in rows))

    ok = [j for j in jobs if j["ok"]]
    out(f"\ndetail pages ok: {len(ok)} of {len(jobs)}, took {time.time() - t0:.0f}s")

    has_loc = sum(1 for j in ok if any(p.get("addresslocality") for p in j["places"]))
    has_date = [j["posted"] for j in ok if j["posted"]]
    out(f"jobs with addressLocality (city): {has_loc}")
    out(f"jobs with a posted date: {len(has_date)}")
    out(f"jobs with zero parsed locations: {sum(1 for j in ok if not j['places'])}")

    mismatch = [j for j in ok if j["places"] and len(j["places"]) != j["more"] + 1]
    out(f"jobs where detail location count != list '+N more' + 1: {len(mismatch)}")
    for j in mismatch[:5]:
        out(f"    {j['id']}: list says {j['more'] + 1}, detail has {len(j['places'])}")

    countries = Counter(p.get("addresscountry") for j in ok for p in j["places"])
    out(f"country counts across all locations: {dict(countries.most_common(8))}")

    out("\nORDER CHECK")
    order_report(ok)

    us = [j for j in ok if any(p.get("addresscountry") == "US" for p in j["places"])]
    out(f"\nkeep (any US location): {len(us)}   drop: {len(ok) - len(us)}")
    sizes = Counter(len(j["places"]) for j in us)
    out(f"locations per kept job, top sizes: {dict(sizes.most_common(6))}")
    out(f"max locations on one job: {max((len(j['places']) for j in us), default=0)}")

    out("\nsample parsed jobs:")
    for j in us[:5]:
        out(f"  pos {j['pos']} | {j['id']} | {j['title']} | posted={j['posted']}")
        for p in j["places"][:4]:
            out(f"      {place_str(p)}")

    saved = [
        {
            "pos": j["pos"],
            "id": j["id"],
            "title": j["title"],
            "url": BASE + j["href"],
            "posted": j["posted"],
            "locations": [place_str(p) for p in j["places"]],
        }
        for j in us
    ]
    JOBS_JSON.write_text(json.dumps(saved, indent=1), encoding="utf-8")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nSaved {REPORT} and {JOBS_JSON}")


asyncio.run(main())
