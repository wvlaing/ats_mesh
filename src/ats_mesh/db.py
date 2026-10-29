import json
import sqlite3
from collections import defaultdict

from ats_mesh.config import DB_PATH
from ats_mesh.dates import timestamp
from ats_mesh.models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    company_name TEXT NOT NULL,
    ats_job_id   TEXT NOT NULL,
    ats          TEXT,
    title        TEXT,
    url          TEXT,
    locations    TEXT,   -- JSON list, as the ATS gave it
    posted       TEXT,   -- YYYY-MM-DD, fixed the first time we see the job
    first_seen   TEXT,   -- '2026-09-03 1330 EDT'
    reason       TEXT,   -- which filter dropped it; NULL = kept
    PRIMARY KEY (company_name, ats_job_id)
)
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con: sqlite3.Connection = sqlite3.connect(database=DB_PATH)
    con.execute(SCHEMA)  # does nothing if the table already exists
    return con


def known_ids(con: sqlite3.Connection) -> dict[str, set[str]]:
    """{company name: ats_job_ids ever pulled}, filtered out or not. Adapters use
    it to skip jobs they've already got instead of re-fetching them."""
    known: defaultdict[str, set[str]] = defaultdict(set)
    for name, job_id in con.execute("SELECT company_name, ats_job_id FROM jobs"):
        known[name].add(job_id)
    return known


def add_jobs(con: sqlite3.Connection, jobs: list[Job]) -> None:
    """Insert jobs we've never seen; rows we have are left alone. That keeps posted
    and first_seen fixed, so a job keeps aging even though the site keeps saying
    'Posted 30+ Days Ago'."""
    seen = timestamp()
    con.executemany(
        "INSERT INTO jobs (company_name, ats_job_id, ats, title, url, locations, posted, first_seen)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(company_name, ats_job_id) DO UPDATE SET posted = excluded.posted"
        " WHERE excluded.posted > jobs.posted",
        [
            (
                j.company_name,
                j.ats_job_id,
                j.ats,
                j.title,
                j.url,
                json.dumps(obj=j.locations, ensure_ascii=False),
                j.posted,
                seen,
            )
            for j in jobs
        ],
    )
    con.commit()


def load_jobs(con: sqlite3.Connection) -> list[Job]:
    rows: sqlite3.Cursor = con.execute(
        "SELECT ats, company_name, ats_job_id, title, url, locations, posted,"
        " first_seen FROM jobs"
    )
    return [
        Job(ats, company, job_id, title, url, json.loads(locations), posted, seen)
        for ats, company, job_id, title, url, locations, posted, seen in rows
    ]


def save_reasons(con: sqlite3.Connection, jobs: list[Job]) -> None:
    con.executemany(
        "UPDATE jobs SET reason = ? WHERE company_name = ? AND ats_job_id = ?",
        [(j.reason, j.company_name, j.ats_job_id) for j in jobs],
    )
    con.commit()
