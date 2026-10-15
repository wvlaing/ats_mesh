# ~/src/ats_mesh/main.py

import asyncio
import json

import httpx

from ats_mesh import db
from ats_mesh.adapters import ADAPTERS
from ats_mesh.config import (
    RAW_FILE,
    WRITE_RAW_JSON,
    XLSX_FILE,
)
from ats_mesh.helpers.company_utils import load_companies
from ats_mesh.helpers.export_xlsx import sync
from ats_mesh.helpers.filter_utils import apply_filters, load_config

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


async def fetch_company(client, company, known):
    """Never raises, so one failing company can't sink the rest. `known` is the set
    of job ids already in the database for this company."""
    adapter_cls = ADAPTERS.get(company["ats"])
    if adapter_cls is None:
        print(f"{company['name']}: no adapter for {company['ats']!r}, skipping")
        return []
    try:
        jobs = await adapter_cls(company).fetch_jobs(client, known)
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
        print(f"{company['name']}: failed ({e!r})")
        return []
    new = {j.ats_job_id for j in jobs} - known
    if new:
        print(f"{company['name']}: {len(new)} new")
    return jobs


async def pull(known_by_company):
    companies = load_companies()
    async with httpx.AsyncClient(
        headers=HEADERS, timeout=30, follow_redirects=True
    ) as client:
        results = await asyncio.gather(
            *(
                fetch_company(client, c, known_by_company.get(c["name"], frozenset()))
                for c in companies
            )
        )
    return [job for jobs in results for job in jobs]


def main() -> None:
    con = db.connect()
    known = db.known_ids(con)
    jobs = asyncio.run(pull(known))
    db.add_jobs(con, jobs)
    new_keys = {
        (j.company_name, j.ats_job_id)
        for j in jobs
        if j.ats_job_id not in known.get(j.company_name, ())
    }
    print(f"\n{len(new_keys)} new jobs since last search")

    # Filter everything ever pulled, so editing filters.json applies to old jobs too.
    rows = db.all_jobs(con)
    apply_filters(rows, load_config())
    db.save_reasons(con, rows)
    con.commit()

    kept = [r for r in rows if not r["reason"]]
    new_kept = sum((r["company_name"], r["ats_job_id"]) in new_keys for r in kept)
    print(f"{new_kept} of them pass your filters")

    kept = [r for r in rows if not r["reason"]]
    print(f"{len(kept)} jobs left after filtering")

    sync(XLSX_FILE, kept, [r for r in rows if r["reason"]])

    if WRITE_RAW_JSON:  # every job ever pulled, with the filter that dropped it
        raw = json.dumps(db.all_jobs(con), indent=2, ensure_ascii=False)
        RAW_FILE.write_text(raw, encoding="utf-8")


if __name__ == "__main__":
    main()
