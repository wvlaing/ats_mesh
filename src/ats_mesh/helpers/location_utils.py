# ~/src/ats_mesh/helpers/location_utils.py

import re


def split_locations(value):
    """'New York, NY (HQ); Remote (Canada)' -> ['New York, NY (HQ)', 'Remote (Canada)']"""
    if not value:
        return []
    parts = (p.strip() for p in re.split(r"[;|]", value))
    return list(
        dict.fromkeys(p for p in parts if p)
    )  # drops blanks and duplicates, keeps order
