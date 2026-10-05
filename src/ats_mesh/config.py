# ~/src/ats_mesh/config.py

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "jobs.db"
COMPANIES_FILE = PROJECT_ROOT / "companies.json"
FILTERS_FILE = PROJECT_ROOT / "filters.json"
JOBS_FILE = Path.home() / "Desktop" / "jobs.json"
XLSX_FILE = Path.home() / "Desktop" / "jobs.xlsx"

# Older jobs are dropped off report Age = days since posted (or oldest confirmed date)
MAX_AGE_DAYS = 30

RAW_FILE = Path.home() / "Desktop" / "jobs_raw.json"

# True = also write RAW_FILE: every job in the database, filtered out or not.
WRITE_RAW_JSON = False
