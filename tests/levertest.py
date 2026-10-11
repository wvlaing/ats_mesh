import json
from pathlib import Path

import httpx

BASE_URL = "https://api.lever.co/v0/postings/saviynt"
DESKTOP = Path.home() / "Desktop"
OUTPUT = DESKTOP / "dump.json"


with httpx.Client(timeout=30) as client:
    response = client.get(BASE_URL)
    response.raise_for_status()

    OUTPUT.write_text(
        json.dumps(response.json(), indent=2),
        encoding="utf-8",
    )
