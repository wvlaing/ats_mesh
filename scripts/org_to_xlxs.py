import json
from pathlib import Path

import openpyxl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESKTOP = Path.home() / "Desktop"
COMPANIES_JSON = PROJECT_ROOT / "settings" / "companies.json"


def read_json(file: Path) -> list[dict]:
    with open(file, "r") as data:
        company_data = json.load(data)

        return company_data


def org_values(company_data: list[dict]) -> list[tuple[int, str, str]] | None:
    rows = []
    for company in company_data:
        org_id = company["company_id"]
        org_name = company["name"]
        org_ats = company["ats"]

        rows.append((org_id, org_name, org_ats))

    return rows


def main() -> None:
    company_data = read_json(COMPANIES_JSON)
    rows = org_values(company_data)

    if rows is not None:
        wb = openpyxl.Workbook()
        ws = wb.active

        ws.append(["company_id", "name", "ats"])

        for row in rows:
            ws.append(row)

        wb.save(DESKTOP / "companies.xlsx")


if __name__ == "__main__":
    main()
