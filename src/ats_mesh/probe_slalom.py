"""Throwaway: run from src/ with the project venv. Looks for qtvc in Slalom's pages."""

import asyncio
import re

import httpx

from ats_mesh.adapters.bespoke import slalom as s

PAGES = [s.SEARCH_PAGE, s.SEARCH_PAGE + "/?listFilterMode=1"]


async def main() -> None:
    async with httpx.AsyncClient(
        headers=s.HEADERS, timeout=30, follow_redirects=True, http2=True
    ) as c:
        for url in PAGES:
            r = await c.get(url, headers=s.PAGE_HEADERS)
            t = r.text
            print(f"\n{url}\n  status {r.status_code}, {len(t)} chars")
            print("  my hardcoded qtvc in page:", s.PARAMS["qtvc"] in t)
            for m in list(re.finditer(r"qtvc", t))[:3]:
                print(
                    "  ...",
                    t[max(0, m.start() - 150) : m.end() + 150].replace("\n", " "),
                )
            for m in list(re.finditer(r"_portalList", t))[:2]:
                print(
                    "  ...",
                    t[max(0, m.start() - 100) : m.end() + 200].replace("\n", " "),
                )


asyncio.run(main())
