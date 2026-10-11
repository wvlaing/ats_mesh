# ~/src/ats_mesh/helpers/time_utils.py

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from ats_mesh.config import MAX_AGE_DAYS

EASTERN = ZoneInfo("America/New_York")
BUFFER_DAYS = 7  # extra week on top of the max age, always


def now_utc():
    """Current time as an ISO string in UTC."""
    return datetime.now(UTC).isoformat()


def to_utc(value):
    """ISO timestamp with any offset -> ISO string in UTC, or None."""
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(UTC).isoformat()


def fmt_eastern(value):
    """UTC ISO string -> '2026-09-03 1330 EDT' (Eastern, DST-aware)."""
    if not value:
        return None
    dt = datetime.fromisoformat(value).astimezone(EASTERN)
    return dt.strftime("%Y-%m-%d %H%M %Z")


def fmt_date(value):
    """UTC ISO string -> '2026-09-03' (the Eastern calendar date, no time)."""
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(EASTERN).strftime("%Y-%m-%d")


def date_to_utc(value):
    """'2026-09-03' (a date with no time) -> UTC ISO string for midnight Eastern
    that day. Independent of the machine's own timezone."""
    if not value:
        return None
    day = datetime.fromisoformat(value).date()
    local = datetime(day.year, day.month, day.day, tzinfo=EASTERN)
    return local.astimezone(UTC).isoformat()


def cutoff_date():
    """Oldest posted date worth keeping: the max age plus a week of buffer."""
    return date.today() - timedelta(days=MAX_AGE_DAYS + BUFFER_DAYS)  # noqa: DTZ011
