import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from ats_mesh.config import FILTERS_FILE, MAX_AGE_DAYS
from ats_mesh.dates import today
from ats_mesh.models import Job, Raw
from ats_mesh.places import (
    COUNTRY_CODES3,
    NON_US_COUNTRIES,
    NON_US_PLACES,
    US_STATE_CODES,
    US_STATE_NAMES,
)

CANADA_PROVINCE_CODES = {"ON", "BC", "QC", "AB", "NS", "NB", "MB", "SK", "NL", "PE"}

# Keys a company's block in filters.json may use (anything else is flagged).
COMPANY_KEYS = {"us_only", "remove_locations", "exclude_title_words", "allow_title_words"}


def _norm(s: str) -> str:
    return " ".join(s.casefold().split())


# ------------------------------------------------------------------- config


@dataclass(frozen=True, slots=True)
class Rules:
    """What one company's jobs are judged by."""

    us_only: bool = True
    # Exact locations (normalized) to always drop, e.g. "tbilisi, georgia".
    remove_locations: frozenset[str] = frozenset()
    # Casefolded words; a job with any of them in its title is dropped.
    title_words: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Filters:
    default: Rules
    by_company: dict[str, Rules]  # keyed by normalized company name

    def for_company(self, name: str) -> Rules:
        return self.by_company.get(_norm(name), self.default)


def _rules(
    us_only: bool, locations: Iterable[str], words: Iterable[str]
) -> Rules:
    return Rules(
        us_only=us_only,
        remove_locations=frozenset(_norm(x) for x in locations),
        title_words=tuple(w.casefold() for w in words if w.strip()),
    )


def load_filters() -> Filters:
    """filters.json has "global_filters" (applies to every job) and
    "company_filters" (one block per company name, layered on top of the global
    ones): us_only overrides, remove_locations and exclude_title_words add to the
    global lists, and allow_title_words exempts global title words."""
    if not FILTERS_FILE.exists():
        return Filters(Rules(), {})
    data: Raw = json.loads(FILTERS_FILE.read_text(encoding="utf-8"))
    glob: Raw = data.get("global_filters") or {}
    us_only = bool(glob.get("us_only", True))
    locations: list[str] = glob.get("remove_locations") or []
    words: list[str] = glob.get("exclude_title_words") or []

    by_company: dict[str, Rules] = {}
    for name, block in (data.get("company_filters") or {}).items():
        block = block or {}
        for key in block.keys() - COMPANY_KEYS:
            print(f"filters.json: {name!r} has an unknown key {key!r}, ignored")
        allowed = {_norm(w) for w in block.get("allow_title_words", [])}
        by_company[_norm(name)] = _rules(
            bool(block.get("us_only", us_only)),
            [*locations, *block.get("remove_locations", [])],
            [
                *(w for w in words if _norm(w) not in allowed),
                *block.get("exclude_title_words", []),
            ],
        )
    return Filters(_rules(us_only, locations, words), by_company)


# ---------------------------------------------------------------- locations


class Kind(StrEnum):
    US = "us"
    NON_US = "non_us"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


def _words(terms: Iterable[str]) -> re.Pattern[str]:
    alt = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<![^\W\d_])(?:{alt})(?![^\W\d_])", re.IGNORECASE)


_US_STATE_RE = _words(US_STATE_NAMES)
_US_WORD_RE = re.compile(
    r"\bUSA?\b|(?<![A-Za-z])U\.S\.(?:A\.?)?|\bunited states(?: of america)?\b",
    re.IGNORECASE,
)
_PLACE_RE = _words(NON_US_PLACES)
_COUNTRY_RE = _words(NON_US_COUNTRIES)
# 3-letter codes are upper-case only, so they can't collide with ordinary words.
_CODE3_RE = re.compile(r"(?<![A-Za-z])(?:" + "|".join(COUNTRY_CODES3) + r")(?![A-Za-z])")
# \u2013 and \u2014 are the en and em dash.
_NEUTRAL_RE = re.compile(
    r"^(?:[\s\-\u2013\u2014,/()]*(?:remote|hybrid|on-?site|in[- ]?office|flexible))+"
    r"[\s\-\u2013\u2014,/()]*$",
    re.IGNORECASE,
)
_SPLIT_RE = re.compile(r"\s*[;|\n]\s*|\s+or\s+", re.IGNORECASE)


def _has_us(text: str) -> bool:
    return bool(_US_WORD_RE.search(text) or _US_STATE_RE.search(text))


def _is_non_us(text: str) -> bool:
    return bool(
        _COUNTRY_RE.search(text)
        or _CODE3_RE.search(text)
        or _PLACE_RE.search(text)
        or text.strip() in CANADA_PROVINCE_CODES
    )


def _kind(text: str, rules: Rules) -> Kind:
    """One location -> US / NON_US / NEUTRAL / UNKNOWN."""
    if _norm(text) in rules.remove_locations:
        return Kind.NON_US
    if _has_us(text):
        return Kind.US
    if rules.us_only and _is_non_us(text):
        return Kind.NON_US
    if _NEUTRAL_RE.match(text):
        return Kind.NEUTRAL
    return Kind.UNKNOWN


def locations_in(text: str, rules: Rules) -> list[tuple[str, Kind]]:
    """Split a location string into the individual locations inside it.

    Two steps:
      1. split on  ;  |  newline  " or "                -> pieces
      2. a piece with commas is a LIST, and every place in it is judged on its own
         ("Chicago, Atlanta, Canada" -> Chicago, Atlanta, Canada), except when it
         ends in a US state/country ("Austin, TX", "Austin, Texas, United States"),
         which is one US place.
    """
    text = re.sub(r",\s*republic of", " republic of", text, flags=re.IGNORECASE)
    if _norm(text) in rules.remove_locations:
        return [(text.strip(), Kind.NON_US)]

    found: list[tuple[str, Kind]] = []
    for piece in (p.strip() for p in _SPLIT_RE.split(text)):
        if not piece:
            continue
        if _norm(piece) in rules.remove_locations:
            found.append((piece, Kind.NON_US))
            continue
        tokens = [t.strip() for t in piece.split(",") if t.strip()]
        if len(tokens) > 1:
            last = re.sub(r"\s*\(.*?\)\s*$", "", tokens[-1])  # "NY (HQ)" -> "NY"
            if _has_us(last) or last in US_STATE_CODES:
                found.append((piece, Kind.US))
                continue
            found.extend((t, _kind(t, rules)) for t in tokens)
        else:
            found.append((piece, _kind(piece, rules)))
    return found


def trim_locations(locations: list[str], rules: Rules) -> list[str] | None:
    """The locations worth keeping, or None if the job should be dropped.

    Dropped only if we KNOW every location is outside the US. A US place, or
    anything we can't place, means it might be in the US, so the job stays (with
    the known non-US places trimmed off)."""
    found = [pair for text in locations for pair in locations_in(text, rules)]
    if not found:
        return locations  # no location given: keep
    kinds = {kind for _, kind in found}
    if Kind.NON_US in kinds and not kinds & {Kind.US, Kind.UNKNOWN}:
        return None
    kept = [text for text, kind in found if kind is not Kind.NON_US]
    return kept if len(kept) < len(found) else locations


# ------------------------------------------------------------------ pipeline


def age_days(job: Job) -> int | None:
    """Days since the job was posted, or since we first saw it if it has no date."""
    try:
        return (today() - date.fromisoformat((job.posted or job.first_seen)[:10])).days
    except ValueError:
        return None


def drop_reason(job: Job, rules: Rules) -> str | None:
    """Why this job should be dropped, or None to keep it. Trims non-US places
    off the locations of a job that stays."""
    age = age_days(job)
    if age is not None and age > MAX_AGE_DAYS:
        return f"older than {MAX_AGE_DAYS} days"
    kept = trim_locations(job.locations, rules)
    if kept is None:
        return "not in the US"
    job.locations = kept
    if any(word in job.title.casefold() for word in rules.title_words):
        return "unwanted title"
    return None


def apply_filters(jobs: list[Job], filters: Filters) -> None:
    """Sets job.reason on every job (None = kept). Each job is judged by the global
    filters plus its own company's block, if it has one."""
    present = {_norm(j.company_name) for j in jobs}
    for name in filters.by_company.keys() - present:
        print(f"filters.json: no jobs from company {name!r} (check company_filters)")
    for job in jobs:
        job.reason = drop_reason(job, filters.for_company(job.company_name))
