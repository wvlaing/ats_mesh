# ~/src/ats_mesh/main.py

import asyncio
import json

import httpx

from ats_mesh import db
from ats_mesh.adapters import ADAPTERS
from ats_mesh.config import (
    COMPANIES_FILE,
    JOBS_FILE,
    RAW_FILE,
    WRITE_RAW_JSON,
    XLSX_FILE,
)
from ats_mesh.helpers.export_xlsx import sync
from ats_mesh.helpers.filter_utils import apply_filters, load_config

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


async def fetch_company(client, company):
    """Never raises, so one failing company can't sink the rest."""
    adapter_cls = ADAPTERS.get(company["ats"])
    if adapter_cls is None:
        print(f"{company['name']}: no adapter for {company['ats']!r}, skipping")
        return []
    try:
        jobs = await adapter_cls(company).fetch_jobs(client)
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
        print(f"{company['name']}: failed ({e!r})")
        return []
    print(f"{company['name']}: {len(jobs)} jobs")
    return jobs


async def pull():
    companies = json.loads(COMPANIES_FILE.read_text(encoding="utf-8"))
    companies = [c for c in companies if c.get("enabled", True)]
    async with httpx.AsyncClient(
        headers=HEADERS, timeout=30, follow_redirects=True
    ) as client:
        results = await asyncio.gather(*(fetch_company(client, c) for c in companies))
    return [job for jobs in results for job in jobs]


def main() -> None:
    jobs = asyncio.run(pull())
    con = db.connect()
    print(f"\nPulled {len(jobs)} jobs, {db.add_jobs(con, jobs)} never seen before")

    # Filter everything ever pulled, so editing filters.json applies to old jobs too.
    rows = db.all_jobs(con)
    for label, count in apply_filters(rows, load_config()).items():
        print(f"Filtered out {count}: {label}")
    db.save_reasons(con, rows)

    kept = [r for r in rows if not r["reason"]]
    print(f"{len(kept)} jobs left after filtering")

    # shown = already in the sheet. New survivors go in, jobs that aged out come out.
    db.save_reasons(con, rows)
    con.commit()

    kept = [r for r in rows if not r["reason"]]
    print(f"{len(kept)} jobs left after filtering")

    sync(XLSX_FILE, kept, [r for r in rows if r["reason"]])

    if WRITE_RAW_JSON:  # every job ever pulled, with the filter that dropped it
        raw = json.dumps(db.all_jobs(con), indent=2, ensure_ascii=False)
        RAW_FILE.write_text(raw, encoding="utf-8")


if __name__ == "__main__":
    main()
