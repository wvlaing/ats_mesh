# ~/src/ats_mesh/helpers/filters.py

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from ats_mesh.config import FILTERS_FILE, MAX_AGE_DAYS
from ats_mesh.helpers.time_utils import EASTERN

# --------------------------------------------------------------------- data
# (extend these lists freely)

US_STATE_CODES = set(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "  # noqa: SIM905
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)
# "georgia" is left out on purpose: as a bare word it is as likely the country.
US_STATE_NAMES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "district of columbia", "florida", "hawaii",
    "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
]  # fmt: skip

CANADA_PROVINCE_CODES = {"ON", "BC", "QC", "AB", "NS", "NB", "MB", "SK", "NL", "PE"}

NON_US_COUNTRIES = [
    "afghanistan", "albania", "algeria", "argentina", "armenia", "australia",
    "austria", "bahrain", "bangladesh", "belgium", "bolivia", "bosnia", "brazil",
    "bulgaria", "cambodia", "canada", "chile", "china", "colombia", "costa rica",
    "croatia", "cyprus", "czech republic", "czechia", "denmark",
    "dominican republic", "ecuador", "egypt", "el salvador", "estonia", "finland",
    "france", "germany", "ghana", "greece", "guatemala", "hong kong", "hungary",
    "iceland", "india", "indonesia", "ireland", "israel", "italy", "japan",
    "jordan", "kazakhstan", "kenya", "korea", "kuwait", "latvia", "lebanon",
    "lithuania", "luxembourg", "malaysia", "malta", "mexico", "morocco",
    "netherlands", "new zealand", "nigeria", "norway", "pakistan", "panama",
    "peru", "philippines", "poland", "portugal", "qatar", "romania",
    "saudi arabia", "serbia", "singapore", "slovakia", "slovenia", "south africa",
    "spain", "sri lanka", "sweden", "switzerland", "taiwan", "thailand", "turkey",
    "türkiye", "ukraine", "united arab emirates", "uae", "united kingdom", "uk",
    "great britain", "england", "scotland", "wales", "northern ireland",
    "uruguay", "venezuela", "vietnam", "jamaica", "trinidad", "uzbekistan",
    "mongolia", "ethiopia", "democratic republic of congo", "congo",
    "cote d'ivoire", "côte d'ivoire", "ivory coast", "tanzania", "uganda",
    "senegal", "rwanda", "tunisia", "bahamas", 
]  # fmt: skip

NON_US_OTHER = [
    # Regions
    "emea", "apac", "latam", "europe", "asia", "latin america", "middle east",
    "africa", "oceania",
    # Canadian Provinces
    "ontario", "british columbia", "quebec", "québec", "alberta", "manitoba",
    "saskatchewan", "nova scotia", "new brunswick",
    # Cities outside of U.S.
    "london", "dublin", "paris", "berlin", "munich", "hamburg", "frankfurt",
    "amsterdam", "rotterdam", "brussels", "madrid", "barcelona", "lisbon", "porto",
    "rome", "milan", "zurich", "geneva", "bern", "vienna", "prague", "warsaw",
    "krakow", "wroclaw", "gdansk", "budapest", "bucharest", "cluj", "sofia",
    "athens", "istanbul", "stockholm", "gothenburg", "malmö", "copenhagen",
    "aarhus", "oslo", "helsinki", "tallinn", "riga", "vilnius", "kyiv", "belgrade",
    "zagreb", "brno", "lyon", "düsseldorf", "dusseldorf", "cologne", "stuttgart",
    "belfast", "edinburgh", "glasgow", "cardiff", "leeds", "bristol",
    "tel aviv", "jerusalem", "dubai", "abu dhabi", "karnataka", "riyadh", "doha", "cairo",
    "lagos", "nairobi", "cape town", "johannesburg", "mumbai", "bangalore",
    "bengaluru", "hyderabad", "pune", "chennai", "delhi", "new delhi", "gurgaon",
    "gurugram", "noida", "kolkata", "ahmedabad", "kuala lumpur", "jakarta",
    "manila", "bangkok", "ho chi minh", "hanoi", "tokyo", "osaka", "seoul",
    "beijing", "shanghai", "shenzhen", "taipei", "sydney", "melbourne",
    "brisbane", "perth", "auckland", "wellington", "toronto", "vancouver",
    "montreal", "montréal", "ottawa", "calgary", "edmonton", "waterloo",
    "mississauga", "mexico city", "guadalajara", "monterrey", "sao paulo",
    "são paulo", "rio de janeiro", "buenos aires", "santiago", "bogota", "bogotá",
    "lima", "medellin",
    "tbilisi", "abidjan", "kinshasa", "colombo", "egham", "surrey", "hesse",
    "herzliya", "petah tikva", "ramat-gan", "causeway bay", "wanchai", "makati",
    "pasay", "nagoya", "fukuoka", "yokohama", "chiyoda", "munchen", "münchen",
    "wien", "praha", "kraków", "warszawa", "zürich", "reykjavik", "reykjavík",
    "solna", "soborg", "lysaker", "zaventem", "brussel", "espoo", "novi sad",
    "lucerne", "cork", "besiktas", "beirut", "accra", "addis ababa", "karachi",
    "dhaka", "almaty", "tashkent", "amman", "casablanca", "santo domingo",
    "guatemala city", "heredia", "escazu", "cdmx", "mohali", "vadodara",
    "hsinchu", "penang", "ulaanbaatar", "sheffield", "basingstoke", "staines",
    "sao jose dos campos", "navi mumbai", "ncr",
]  # fmt: skip

# 3-letter country codes (Upper-case only)
COUNTRY_CODES3 = (  # noqa: SIM905
    "IND CAN GBR DEU FRA ESP ITA NLD AUS JPN CHN KOR SGP MYS THA IRL ISR POL CHE "
    "SWE BRA MEX IDN PHL TWN VNM KSA NOR DNK FIN BEL AUT PRT CZE HUN ROU TUR ZAF "
    "HKG NZL COL CHL ARG JOR CRI GBP UAE ARE SAU"
).split()

NON_US_PLACES = NON_US_COUNTRIES + NON_US_OTHER


# ------------------------------------------------------------------- config


@dataclass
class Config:
    us_only: bool = True
    # Exact location strings (or one place inside a location) to always delete,
    # e.g. "Tbilisi, Georgia". Case/spacing doesn't matter.
    remove_locations: list[str] = field(default_factory=list)
    # Not used yet. Fill in filters.json to drop jobs with these words in the title.
    exclude_title_words: list[str] = field(default_factory=list)

    @property
    def manual(self):
        return {_norm(x) for x in self.remove_locations}


def load_config():
    if not FILTERS_FILE.exists():
        return Config()
    data = json.loads(FILTERS_FILE.read_text(encoding="utf-8"))
    return Config(
        us_only=bool(data.get("us_only", True)),
        remove_locations=list(data.get("remove_locations") or []),
        exclude_title_words=list(data.get("exclude_title_words") or []),
    )


# -------------------------------------------------------------------- dates


def age_days(rec):
    """Days since the job was posted, or since we first saw it if it has no date.
    `rec` is a record from the raw database, so the dates were fixed the first
    time the job was pulled and keep aging on every later run."""
    for field in ("posted_at", "first_seen_at"):  # noqa: F402
        value = rec.get(field)
        if value:
            try:
                return (
                    datetime.now(EASTERN).date() - date.fromisoformat(value[:10])
                ).days
            except ValueError:
                pass
    return None


def is_too_old(rec):
    age = age_days(rec)
    return age is not None and age > MAX_AGE_DAYS


def date_filter(job, cfg):
    return f"older than {MAX_AGE_DAYS} days" if is_too_old(job) else None


# ---------------------------------------------------------------- locations

US, NON_US, NEUTRAL, UNKNOWN = "us", "non_us", "neutral", "unknown"


def _norm(s):
    return " ".join(str(s).casefold().split())


def _words(terms):
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
_CODE3_RE = re.compile(
    r"(?<![A-Za-z])(?:" + "|".join(COUNTRY_CODES3) + r")(?![A-Za-z])"
)
_NEUTRAL_RE = re.compile(
    r"^(?:[\s\-–—,/()]*(?:remote|hybrid|on-?site|in[- ]?office|flexible))+[\s\-–—,/()]*$",
    re.IGNORECASE,
)
_SPLIT_RE = re.compile(r"\s*[;|\n]\s*|\s+or\s+", re.IGNORECASE)


def _has_us(text):
    return bool(_US_WORD_RE.search(text) or _US_STATE_RE.search(text))


def _is_country(text):
    return bool(_COUNTRY_RE.search(text) or _CODE3_RE.search(text))


def _is_non_us(text):
    return (
        _is_country(text)
        or bool(_PLACE_RE.search(text))
        or text.strip() in CANADA_PROVINCE_CODES
    )


def _kind(text, cfg):
    """One location -> US / NON_US / NEUTRAL / UNKNOWN."""
    if _norm(text) in cfg.manual:
        return NON_US
    if _has_us(text):
        return US
    if cfg.us_only and _is_non_us(text):
        return NON_US
    if _NEUTRAL_RE.match(text):
        return NEUTRAL
    return UNKNOWN


def locations_in(text, cfg):
    """Split a location string into the individual locations inside it.

    Returns [(location, kind), ...].  Two steps:
      1. split on  ;  |  newline  " or "                -> pieces
      2. a piece with commas is a LIST, and every place in it is judged on its own
         ("Chicago, Atlanta, Canada" -> Chicago, Atlanta, Canada), except when it
         ends in a US state/country ("Austin, TX", "Austin, Texas, United States"),
         which is one US place.
    """
    text = re.sub(r",\s*republic of", " republic of", text, flags=re.IGNORECASE)
    if _norm(text) in cfg.manual:
        return [(text.strip(), NON_US)]

    found = []
    for piece in _SPLIT_RE.split(text):
        piece = piece.strip()
        if not piece:
            continue
        if _norm(piece) in cfg.manual:
            found.append((piece, NON_US))
            continue
        tokens = [t.strip() for t in piece.split(",") if t.strip()]
        if len(tokens) > 1:
            last = re.sub(r"\s*\(.*?\)\s*$", "", tokens[-1])  # "NY (HQ)" -> "NY"
            if _has_us(last) or last in US_STATE_CODES:
                found.append((piece, US))
                continue
            found.extend((t, _kind(t, cfg)) for t in tokens)
        else:
            found.append((piece, _kind(piece, cfg)))
    return found


def location_filter(job, cfg):
    locs = [pair for text in job["locations"] for pair in locations_in(text, cfg)]
    if not locs:
        return None  # no location given: keep

    kinds = {k for _, k in locs}
    # Drop only if we KNOW every location is outside the US. A US place or
    # anything we can't place means it might be in the US, so keep it.
    if NON_US in kinds and not kinds & {US, UNKNOWN}:
        return "not in the US"

    kept = [t for t, k in locs if k != NON_US]
    if len(kept) < len(locs):  # trim the non-US places
        job["locations"] = kept
    return None


# ------------------------------------------------------------------- titles


def title_filter(job, cfg):
    """Placeholder for title filtering. Does nothing until filters.json has
    `exclude_title_words`."""
    title = (job.get("title") or "").casefold()
    if any(w.casefold() in title for w in cfg.exclude_title_words if w.strip()):
        return "unwanted title"
    return None


# ------------------------------------------------------------- the pipeline

# Run in this order. To add a filter: write  f(job, cfg) -> reason | None  and
# add it here. The label is what shows up in the run summary.
FILTERS = [
    ("older than 30 days", date_filter),
    ("not in the US", location_filter),
    ("unwanted title", title_filter),
]


def apply_filters(rows, cfg):
    """Sets row["reason"] on every row (None = kept). Returns {label: number dropped}."""
    dropped = {label: 0 for label, _ in FILTERS}
    for row in rows:
        row["reason"] = None
        for label, f in FILTERS:
            if f(row, cfg):
                row["reason"] = label
                dropped[label] += 1
                break
    return dropped
