from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from ats_mesh.config import CUTOFF_DAYS

EASTERN = ZoneInfo(key="America/New_York")


def today() -> date:
    return datetime.now(tz=EASTERN).date()


def days_ago(days: int) -> str:
    return (today() - timedelta(days=days)).isoformat()


def cutoff() -> str:
    """Oldest posted date worth keeping, as YYYY-MM-DD (compares correctly as text)."""
    return days_ago(CUTOFF_DAYS)


def timestamp() -> str:
    """Now, as '2026-09-03 1330 EDT'."""
    return datetime.now(tz=EASTERN).strftime(format="%Y-%m-%d %H%M %Z")


def eastern_date(value: str | None) -> str | None:
    """ISO timestamp with any offset -> its Eastern calendar date, or None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(EASTERN).date().isoformat()
    except ValueError:
        return None  # one odd date shouldn't sink the whole pull


def epoch_ms_date(ms: float | None) -> str | None:
    """Epoch milliseconds -> UTC calendar date, or None."""
    if not isinstance(ms, int | float) or ms <= 0:
        return None
    return datetime.fromtimestamp(timestamp=ms / 1000, tz=UTC).date().isoformat()
