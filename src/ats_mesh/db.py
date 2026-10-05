# ~/src/ats_mesh/db.py

import json
import sqlite3

from ats_mesh.config import DB_PATH
from ats_mesh.helpers.time_utils import fmt_eastern, now_utc

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    company_id   INTEGER NOT NULL,
    ats_job_id   TEXT    NOT NULL,
    ats          TEXT,
    company_name TEXT,
    title        TEXT,
    url          TEXT,
    locations    TEXT,                  -- JSON list, as the ATS gave it
    posted       TEXT,                  -- YYYY-MM-DD, fixed the first time we see the job
    first_seen   TEXT,                  -- '2026-09-03 1330 EDT'
    reason       TEXT,                  -- which filter dropped it; NULL = kept
    shown        INTEGER NOT NULL DEFAULT 0,  -- 1 while the job is in the sheet
    PRIMARY KEY (company_id, ats_job_id)
)
"""


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute(SCHEMA)
    return con


def add_jobs(con, jobs):
    """Insert jobs we've never seen; rows we have are left alone. That keeps posted
    and first_seen fixed, so a job keeps aging even though the site keeps saying
    'Posted 30+ Days Ago'. Returns how many were new."""
    seen = fmt_eastern(now_utc())
    before = con.total_changes
    con.executemany(
        "INSERT OR IGNORE INTO jobs (company_id, ats_job_id, ats, company_name, title,"
        " url, locations, posted, first_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                j.company_id,
                j.ats_job_id,
                j.ats,
                j.company_name,
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
        "UPDATE jobs SET reason = ? WHERE company_id = ? AND ats_job_id = ?",
        [(r["reason"], r["company_id"], r["ats_job_id"]) for r in rows],
    )


def set_shown(con, rows, value):
    con.executemany(
        "UPDATE jobs SET shown = ? WHERE company_id = ? AND ats_job_id = ?",
        [(value, r["company_id"], r["ats_job_id"]) for r in rows],
    )
