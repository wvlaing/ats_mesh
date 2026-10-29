import asyncio
from collections.abc import Set
from contextlib import closing

import httpx

from ats_mesh import db, export
from ats_mesh.adapters import ADAPTERS
from ats_mesh.adapters.base import Adapter
from ats_mesh.companies import load_companies
from ats_mesh.config import XLSX_FILE
from ats_mesh.filters import apply_filters, load_filters
from ats_mesh.models import Company, Job
from ats_mesh.net import FETCH_ERRORS

HEADERS: dict[str, str] = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


async def fetch_company(
    client: httpx.AsyncClient, company: Company, known: Set[str]
) -> list[Job]:
    """The company's jobs we haven't seen before. Never raises, so one failing
    company can't sink the rest."""
    name: str = company["name"]
    adapter: type[Adapter] | None = ADAPTERS.get(company["ats"])
    if adapter is None:
        print(f"{name}: no adapter for {company['ats']!r}, skipping")
        return []
    try:
        jobs: list[Job] = await adapter(company).fetch_jobs(client, known)
    except FETCH_ERRORS as e:
        print(f"{name}: failed ({e!r})")
        return []
    new = list({j.ats_job_id: j for j in jobs}.values())
    fresh = [j for j in new if j.ats_job_id not in known]
    if fresh:
        print(f"{name}: {len(fresh)} new")
    return new


async def pull(known: dict[str, set[str]]) -> list[Job]:
    async with httpx.AsyncClient(
        headers=HEADERS, timeout=30, follow_redirects=True
    ) as client:
        results: list[list[Job]] = await asyncio.gather(
            *(
                fetch_company(client, company=c, known=known.get(c["name"], set()))
                for c in load_companies()
            )
        )
    return [job for jobs in results for job in jobs]


def main() -> None:
    with closing(thing=db.connect()) as con:
        new: list[Job] = asyncio.run(main=pull(db.known_ids(con)))
        db.add_jobs(con, jobs=new)
        print(f"\n{len(new)} new jobs since last search")

        # Filter everything ever pulled, so editing filters.json applies to old jobs too.
        jobs: list[Job] = db.load_jobs(con)
        apply_filters(jobs, load_filters())
        db.save_reasons(con, jobs)

    kept: list[Job] = [j for j in jobs if not j.reason]
    new_keys: set[tuple[str, str]] = {j.key for j in new}
    print(f"{sum(j.key in new_keys for j in kept)} of them pass your filters")
    print(f"{len(kept)} jobs left after filtering")

    export.sync(path=XLSX_FILE, added=kept, removed=[j for j in jobs if j.reason])


if __name__ == "__main__":
    main()
