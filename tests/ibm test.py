import json
import re
from pathlib import Path

import httpx

API_URL = "https://www-api.ibm.com/search/api/v2"
COUNTRY = "United States"
REPORT = Path.home() / "Desktop" / "ibm_probe.txt"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
    ),
}
DATEISH = re.compile(
    r"\b20\d{2}-\d{2}-\d{2}\b|\b1[5-9]\d{11}\b|\b\d{2}-[A-Z][a-z]{2}-\d{4}\b"
)
VARIANTS = {
    "all _source": {"_source": ["*"]},
    "date-ish _source": {
        "_source": [
            "title",
            "dcdate",
            "*date*",
            "*Date*",
            "*time*",
            "*posted*",
            "field_*",
        ]
    },
    "docvalue_fields dcdate": {"_source": ["title"], "docvalue_fields": ["dcdate"]},
    "fields dcdate": {"_source": ["title"], "fields": ["dcdate", "*date*"]},
}
OFFSETS = [0, 300]

lines = []


def out(text=""):
    print(text)
    lines.append(text)


def body(offset, extra):
    return {
        "appId": "careers",
        "scopes": ["careers2"],
        "query": {"bool": {"must": []}},
        "post_filter": {"bool": {"must": [{"term": {"field_keyword_05": COUNTRY}}]}},
        "size": 5,
        "from": offset,
        "sort": [{"dcdate": "desc"}, {"_score": "desc"}],
        "lang": "zz",
        "localeSelector": {},
        "sm": {"query": "", "lang": "zz"},
        **extra,
    }


def main():
    with httpx.Client(timeout=30, headers=HEADERS) as client:
        for name, extra in VARIANTS.items():
            for offset in OFFSETS:
                out(f"\n[{name}] offset {offset}")
                r = client.post(API_URL, json=body(offset, extra))
                if r.status_code != 200:
                    out(f"  status {r.status_code}: {r.text[:200]!r}")
                    break
                hits = r.json()["hits"]["hits"]
                if not hits:
                    out("  no hits")
                    continue
                first = hits[0]
                out(f"  hit keys: {sorted(first)}")
                out(f"  _source keys: {sorted(first.get('_source', {}))}")
                out(f"  sort values: {[h.get('sort') for h in hits]}")
                if "fields" in first:
                    out(f"  fields: {[h.get('fields') for h in hits]}")
                trimmed = [{k: v for k, v in h.items() if k != "_id"} for h in hits]
                for h in trimmed:
                    h.get("_source", {}).pop("description", None)
                found = DATEISH.findall(json.dumps(trimmed))
                out(f"  date-like values (description ignored): {found[:6] or 'none'}")

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nSaved {REPORT}")


main()
