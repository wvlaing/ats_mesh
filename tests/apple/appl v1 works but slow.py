import json
import math
import random
import re
import time
from datetime import UTC, datetime, timezone
from pathlib import Path

import httpx

BASE = "https://jobs.apple.com"
SEARCH_URL = f"{BASE}/api/v1/search"
CSRF_URL = f"{BASE}/api/v1/CSRFToken"
TEXAS = "postLocation-state995"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Origin": BASE,
    "Referer": f"{BASE}/en-us/search",
}


def payload(page):
    return {
        "query": "",
        "filters": {"locations": [TEXAS]},
        "page": page,
        "locale": "en-us",
        "sort": "",
        "format": {"longDate": "MMMM D, YYYY", "mediumDate": "MMM D, YYYY"},
    }


def new_session():
    client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)
    r = client.get(CSRF_URL)
    r.raise_for_status()
    return client, r.headers["X-Apple-CSRF-Token"]


def get_page(state, page, attempts=6):
    for attempt in range(1, attempts + 1):
        results, data = [], {}
        try:
            r = state["client"].post(
                SEARCH_URL,
                json=payload(page),
                headers={"X-Apple-CSRF-Token": state["token"]},
            )
            r.raise_for_status()
            state["token"] = r.headers.get("X-Apple-CSRF-Token") or state["token"]
            body = r.json()
            data = (body.get("res", body) if isinstance(body, dict) else {}) or {}
            results = data.get("searchResults") or []
        except (httpx.HTTPError, ValueError) as e:
            print(f"Page {page}: request error {e!r}")
        if results:
            return data, results
        print(f"Page {page}: empty (try {attempt}/{attempts}), starting a new session")
        time.sleep(2 * attempt + random.random())
        try:
            state["client"].close()
            state["client"], state["token"] = new_session()
        except httpx.HTTPError as e:
            print(f"Page {page}: new session failed {e!r}")
    return {}, []


def strip_html(text):
    return re.sub(r"<.*?>", "", text or "").strip()


def normalize(j):
    pos_id = j.get("positionId") or j.get("reqId") or j.get("id")
    slug = j.get("transformedPostingTitle") or ""
    url = f"{BASE}/en-us/details/{pos_id}" + (f"/{slug}" if slug else "")
    locations = [l.get("name") for l in (j.get("locations") or []) if l.get("name")]
    return {
        "id": pos_id,
        "req_id": j.get("reqId"),
        "title": j.get("postingTitle"),
        "company": "Apple",
        "team": (j.get("team") or {}).get("teamName"),
        "locations": locations,
        "home_office": j.get("homeOffice"),
        "posted": j.get("postingDate"),
        "summary": strip_html(j.get("jobSummary")),
        "url": url,
    }


def main():
    jobs = {}
    state = {}
    state["client"], state["token"] = new_session()

    def add(results):
        for raw in results:
            job = normalize(raw)
            jobs[job["id"] or job["url"]] = job

    data, results = get_page(state, 1)
    if not results:
        raise SystemExit("Page 1 returned nothing, giving up")
    total = data.get("totalRecords") or len(results)
    max_page = math.ceil(total / len(results))
    add(results)
    print(f"Page 1/{max_page}: {len(results)} ({len(jobs)}/{total})")

    missing = []
    for page in range(2, max_page + 1):
        data, results = get_page(state, page)
        if results:
            add(results)
            print(f"Page {page}/{max_page}: {len(results)} ({len(jobs)}/{total})")
        else:
            missing.append(page)
        time.sleep(0.7 + random.random() * 0.6)

    for round_no in range(1, 4):
        if not missing:
            break
        print(f"\nRetry pass {round_no}, missing pages: {missing}")
        time.sleep(5)
        for page in list(missing):
            data, results = get_page(state, page)
            if results:
                add(results)
                missing.remove(page)
                print(f"Page {page}/{max_page}: {len(results)} ({len(jobs)}/{total})")
            time.sleep(2 + random.random())

    state["client"].close()

    if len(jobs) < total:
        print(f"WARNING: got {len(jobs)} of {total}, missing pages: {missing}")

    desktop = Path.home() / "Desktop"
    today = datetime.now(UTC).astimezone()
    out = (
        desktop if desktop.exists() else Path.home()
    ) / f"apple_jobs_texas_{today:%Y-%m-%d}.json"
    out.write_text(
        json.dumps(
            {
                "source": BASE,
                "location": "Texas",
                "scraped_at": datetime.now(UTC).isoformat(),
                "count": len(jobs),
                "jobs": list(jobs.values()),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved {len(jobs)} Texas jobs to {out}")


if __name__ == "__main__":
    main()
