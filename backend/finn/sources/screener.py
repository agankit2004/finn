"""Find a company's exchange filings through its public screener.in page.

screener.in only supplies LINKS. Every document FINN reads is the original filing on bseindia.com
(or the company's site), so the evidence stays primary. FINN never uses screener's own numbers,
tables or one-line summaries.

One page per company gives:
  - the 5 most recent exchange filings (title, exact time, BSE PDF): a fallback feed for when
    the BSE/NSE APIs refuse us;
  - per-quarter "source" links that redirect to that quarter's results filing on BSE;
  - concall transcripts and annual reports.
"""
from __future__ import annotations

import logging
import re
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from bs4 import BeautifulSoup, NavigableString

from .http import SourceError, get, make_client, redirect_target

log = logging.getLogger("finn.screener")
BASE = "https://www.screener.in"

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _parse_month_year(text: str) -> datetime | None:
    m = re.search(r"([A-Za-z]{3})[a-z]*\s+(\d{4})", text or "")
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    return datetime(int(m.group(2)), _MONTHS[m.group(1).lower()], 1)


def page(symbol: str) -> str:
    """The company page (consolidated view first: its quarter links point at the same filings)."""
    with make_client(headers={"Accept": "text/html"}) as c:
        for path in (f"/company/{symbol}/consolidated/", f"/company/{symbol}/"):
            try:
                return get(c, BASE + path, retries=2).text
            except SourceError as e:
                log.info("screener %s: %s", path, e)
    raise SourceError("screener.in page unavailable")


def _block(root, cls: str):
    return root.find("div", class_=lambda c: c and "documents" in c and cls in c) if cls else None


def _heading_block(root, starts: str):
    for block in root.find_all("div"):
        h = block.find(["h3", "h4"], recursive=False)
        if h and h.get_text(" ", strip=True).lower().startswith(starts):
            return block
    return None


def parse(html: str) -> dict:
    """Everything FINN uses from one screener page. Pure function, so it's tested on a saved page."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find(id="documents") or soup
    out: dict = {"recent": [], "annual_reports": [], "transcripts": [], "quarters": []}

    ann = _heading_block(root, "announcements")
    for li in ann.find_all("li") if ann else []:
        a = li.find("a", href=True)
        t = li.find("time")
        if not a or not t or not t.get("datetime"):
            continue
        # The link text is the filing's own title; the <div> after it is screener's summary, which we skip.
        title = " ".join("".join(s for s in a.children if isinstance(s, NavigableString)).split())
        filed = datetime.fromisoformat(t["datetime"]).astimezone(timezone.utc).replace(tzinfo=None)
        out["recent"].append({"title": title, "url": a["href"], "filed_at_utc": filed})

    ar = _block(root, "annual-reports") or _heading_block(root, "annual report")
    for a in ar.find_all("a", href=True) if ar else []:
        title = a.get_text(" ", strip=True)
        year = re.search(r"(20\d{2})", title)
        out["annual_reports"].append({"title": title or "Annual report", "url": a["href"],
                                      "year": int(year.group(1)) if year else None})

    cc = _block(root, "concalls")
    for li in cc.find_all("li") if cc else []:
        when = _parse_month_year(li.get_text(" ", strip=True))
        for a in li.find_all("a", href=True):
            label = (a.get_text(" ", strip=True) + " " + (a.get("title") or "")).lower()
            if "transcript" in label and a["href"].startswith("http"):
                out["transcripts"].append({"title": f"Concall transcript {when:%b %Y}" if when else "Concall transcript",
                                           "url": a["href"], "date": when})

    q = soup.find(id="quarters")
    for a in q.find_all("a", href=True) if q else []:
        m = re.search(r"/company/source/quarter/\d+/(\d{1,2})/(\d{4})/", a["href"])
        if m:
            mon, yr = int(m.group(1)), int(m.group(2))
            out["quarters"].append({"path": a["href"], "period_end": date(yr, mon, monthrange(yr, mon)[1])})
    out["quarters"].sort(key=lambda d: d["period_end"], reverse=True)

    for k in out:  # de-duplicate while keeping order (one transcript per call month)
        seen, uniq = set(), []
        for d in out[k]:
            key = d["title"] if k == "transcripts" and d.get("date") else (d.get("url") or d.get("path"))
            if key not in seen:
                seen.add(key)
                uniq.append(d)
        out[k] = uniq
    return out


def discover(symbol: str, html: str | None = None) -> dict:
    return parse(html or page(symbol))


def results_filing_urls(quarters: list[dict], limit: int) -> list[dict]:
    """Follow screener's per-quarter source links to the results filings on BSE (newest first)."""
    out = []
    with make_client(headers={"Accept": "text/html"}) as c:
        for qd in quarters[:limit]:
            try:
                url = redirect_target(c, BASE + qd["path"])
            except SourceError as e:
                log.info("quarter link %s: %s", qd["path"], e)
                continue
            if url and url.startswith("http") and "screener.in" not in url:
                out.append({"title": f"Results for the quarter ended {qd['period_end']:%d %b %Y}", "url": url,
                            # Filing date isn't on the page; results come out within ~45 days of quarter end.
                            "filed_at": datetime.combine(qd["period_end"] + timedelta(days=45), datetime.min.time()),
                            "period_end": qd["period_end"]})
    return out
