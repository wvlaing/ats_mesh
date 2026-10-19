from dataclasses import dataclass, field
from typing import Any, TypedDict

type Raw = dict[str, Any]  # a decoded JSON object from a careers site


class Company(TypedDict):
    """One enabled entry from companies.json."""

    name: str
    ats: str
    access: Raw


@dataclass(slots=True)
class Job:
    """One posting. Identity is (company_name, ats_job_id), see `key`.

    `first_seen` and `reason` are filled in by the database, not by adapters.
    """

    ats: str
    company_name: str
    ats_job_id: str
    title: str
    url: str | None = None
    locations: list[str] = field(default_factory=list)
    posted: str | None = None  # YYYY-MM-DD, None when the site gives no date
    first_seen: str = ""  # '2026-09-03 1330 EDT'
    reason: str | None = None  # which filter dropped it, None = kept

    @property
    def key(self) -> tuple[str, str]:
        return (self.company_name, self.ats_job_id)
