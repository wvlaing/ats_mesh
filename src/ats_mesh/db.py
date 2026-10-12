# ~/src/ats_mesh/db.py

import json
import shutil
import sqlite3

from ats_mesh.config import DB_PATH
from ats_mesh.helpers.time_utils import fmt_eastern, now_utc

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    company_name TEXT    NOT NULL,
    ats_job_id   TEXT    NOT NULL,
    ats          TEXT,
    title        TEXT,
    url          TEXT,
    locations    TEXT,                  -- JSON list, as the ATS gave it
    posted       TEXT,                  -- YYYY-MM-DD, fixed the first time we see the job
    first_seen   TEXT,                  -- '2026-09-03 1330 EDT'
    reason       TEXT,                  -- which filter dropped it; NULL = kept
    shown        INTEGER NOT NULL DEFAULT 0,  -- 1 while the job is in the sheet
    PRIMARY KEY (company_name, ats_job_id)
)
"""


def migrate_company_id(con):
    """Older databases keyed jobs on (company_id, ats_job_id). Rebuild the table keyed
    on (company_name, ats_job_id) instead, keeping every row. A copy of the database
    is saved next to it first, as jobs.db.bak."""
    columns = [row[1] for row in con.execute("PRAGMA table_info(jobs)")]
    if "company_id" not in columns:
        return
    con.commit()
    shutil.copy2(DB_PATH, DB_PATH.with_name(DB_PATH.name + ".bak"))
    con.executescript(
        "BEGIN;"
        "ALTER TABLE jobs RENAME TO jobs_old;"
        + SCHEMA
        + ";INSERT OR IGNORE INTO jobs (company_name, ats_job_id, ats, title, url,"
        " locations, posted, first_seen, reason, shown)"
        " SELECT company_name, ats_job_id, ats, title, url, locations, posted,"
        " first_seen, reason, shown FROM jobs_old;"
        "DROP TABLE jobs_old;"
        "COMMIT;"
    )


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute(SCHEMA)  # does nothing if the table exists, even an old-shaped one
    migrate_company_id(con)
    return con


def known_ids(con):
    """{company name: set of ats_job_ids ever pulled}, filtered out or not. Adapters
    use it to skip jobs they've already got instead of re-fetching them."""
    known = {}
    for name, job_id in con.execute("SELECT company_name, ats_job_id FROM jobs"):
        known.setdefault(name, set()).add(job_id)
    return known


def add_jobs(con, jobs):
    """Insert jobs we've never seen; rows we have are left alone. That keeps posted
    and first_seen fixed, so a job keeps aging even though the site keeps saying
    'Posted 30+ Days Ago'. Returns how many were new."""
    seen = fmt_eastern(now_utc())
    before = con.total_changes
    con.executemany(
        "INSERT OR IGNORE INTO jobs (company_name, ats_job_id, ats, title,"
        " url, locations, posted, first_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                j.company_name,
                j.ats_job_id,
                j.ats,
                j.title,
                j.url,
                json.dumps(j.locations, ensure_ascii=False),
                j.posted,
                seen,
            )
            for j in jobs
        ],
    )
    con.commit()
    return con.total_changes - before


def all_jobs(con):
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM jobs")]
    con.row_factory = None
    for r in rows:
        r["locations"] = json.loads(r["locations"])
    return rows


def save_reasons(con, rows):
    con.executemany(
        "UPDATE jobs SET reason = ? WHERE company_name = ? AND ats_job_id = ?",
        [(r["reason"], r["company_name"], r["ats_job_id"]) for r in rows],
    )


def set_shown(con, rows, value):
    con.executemany(
        "UPDATE jobs SET shown = ? WHERE company_name = ? AND ats_job_id = ?",
        [(value, r["company_name"], r["ats_job_id"]) for r in rows],
    )
