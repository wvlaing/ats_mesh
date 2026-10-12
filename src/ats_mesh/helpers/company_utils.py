# ~/src/ats_mesh/helpers/company_utils.py

import json

from ats_mesh.config import COMPANIES_FILE


def _no_duplicates(pairs):
    """json.loads quietly keeps only the last of two identical keys, so adding a
    company twice would look like it worked. Fail loudly instead."""
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise SystemExit(f"companies.json: {key!r} is listed twice in one block")
        seen[key] = value
    return seen


def load_companies(path=COMPANIES_FILE):
    """companies.json is {"ats": {ats name: {company name: access info}}}.

    Returns a flat list of {"name", "ats", "access"}, one per enabled company.
    Add "enabled": false inside a company's access block to skip it. A company
    name is its identity in the database, so it can only be used once overall, and
    renaming one makes its jobs look new."""
    text = path.read_text(encoding="utf-8")
    data = json.loads(text, object_pairs_hook=_no_duplicates)
    companies, names = [], {}
    for ats, group in data["ats"].items():
        for name, access in group.items():
            if name in names:
                raise SystemExit(
                    f"companies.json: {name!r} is under {names[name]!r} and {ats!r}"
                )
            names[name] = ats
            access = dict(access)
            if access.pop("enabled", True):
                companies.append({"name": name, "ats": ats, "access": access})
    return companies
