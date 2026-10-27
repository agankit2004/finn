"""Discover annual-report and concall-transcript links from a company's screener.in page.

We read ONE public page per research build, only to find links. The PDFs themselves are
fetched from where they are hosted (usually BSE or the company's own site). The financial
tables on screener are NOT used as evidence; FINN extracts numbers from the filings themselves.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

from .http import SourceError, get, make_client

log = logging.getLogger("finn.screener")

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _parse_month_year(text: str) -> datetime | None:
    m = re.search(r"([A-Za-z]{3})[a-z]*\s+(\d{4})", text or "")
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    return datetime(int(m.group(2)), _MONTHS[m.group(1).lower()], 1)


def discover(symbol: str) -> dict:
    """Return {"annual_reports": [{title, url, year}], "transcripts": [{title, url, date}]}."""
    html = None
    with make_client(headers={"Accept": "text/html"}) as c:
        for path in (f"/company/{symbol}/consolidated/", f"/company/{symbol}/"):
            try:
                html = get(c, "https://www.screener.in" + path, retries=2).text
                break
            except SourceError as e:
                log.info("screener %s: %s", path, e)
    if not html:
        raise SourceError("screener.in page unavailable")
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find(id="documents") or soup
    out = {"annual_reports": [], "transcripts": []}

    for block in root.find_all("div"):
        h = block.find(["h3", "h4"], recursive=False)
        if not h:
            continue
        heading = h.get_text(" ", strip=True).lower()
        if heading.startswith("annual report"):
            for a in block.find_all("a", href=True):
                title = a.get_text(" ", strip=True)
                year = re.search(r"(20\d{2})", title)
                out["annual_reports"].append(
                    {"title": title or "Annual report", "url": a["href"], "year": int(year.group(1)) if year else None}
                )
        elif heading.startswith("concall"):
            for li in block.find_all("li"):
                when = _parse_month_year(li.get_text(" ", strip=True))
                for a in li.find_all("a", href=True):
                    label = a.get_text(" ", strip=True).lower()
                    if "transcript" in label and a["href"].startswith("http"):
                        out["transcripts"].append(
                            {"title": f"Concall transcript {when:%b %Y}" if when else "Concall transcript",
                             "url": a["href"], "date": when}
                        )
    # De-duplicate while keeping order.
    for k in out:
        seen, uniq = set(), []
        for d in out[k]:
            if d["url"] not in seen:
                seen.add(d["url"])
                uniq.append(d)
        out[k] = uniq
    return out
