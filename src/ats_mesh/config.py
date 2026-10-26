from pathlib import Path
from typing import Literal

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
DB_PATH: Path = PROJECT_ROOT / "data" / "jobs.db"
COMPANIES_FILE: Path = PROJECT_ROOT / "settings" / "companies.json"
FILTERS_FILE: Path = PROJECT_ROOT / "settings" / "filters.json"
XLSX_FILE: Path = Path.home() / "Desktop" / "jobs.xlsx"

# Jobs older than this are dropped from the sheet. Age is days since posted, or
# since we first saw the job when the site gives no date.
# Adapters that read newest-first stop paging once they pass this age (a week of
# buffer on top of MAX_AGE_DAYS).

MAX_AGE_DAYS = 7
BUFFER = 7
CUTOFF_DAYS = BUFFER + MAX_AGE_DAYS
