import json
from pathlib import Path

from ats_mesh.config import COMPANIES_FILE
from ats_mesh.models import Company, Raw


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """json.loads quietly keeps only the last of two identical keys, so adding a
    company twice would look like it worked. Fail loudly instead."""
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise SystemExit(f"companies.json: {key!r} is listed twice in one block")
        seen[key] = value
    return seen


def load_companies(path: Path = COMPANIES_FILE) -> list[Company]:
    """companies.json is {"ats": {ats name: {company name: access info}}}.

    Add "enabled": false inside a company's access block to skip it. A company name
    is its identity in the database, so it can only be used once overall, and
    renaming one makes its jobs look new."""
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates)
    companies: list[Company] = []
    owner: dict[str, str] = {}
    for ats, group in data["ats"].items():
        for name, access in group.items():
            if name in owner:
                raise SystemExit(
                    f"companies.json: {name!r} is under {owner[name]!r} and {ats!r}"
                )
            owner[name] = ats
            options: Raw = dict(access)
            if options.pop("enabled", True):
                companies.append({"name": name, "ats": ats, "access": options})
    return companies
