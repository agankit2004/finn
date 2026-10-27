"""Corporate announcements from BSE (primary) and NSE (fallback).

Neither exchange offers a free official API. These are the JSON endpoints behind their public
websites: unofficial, subject to change, and NSE in particular blocks many datacenter IPs.
We query one company and date range per request, slowly, and store everything we fetch.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .http import SourceError, get, make_client

log = logging.getLogger("finn.announcements")
IST = timezone(timedelta(hours=5, minutes=30))

BSE_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_ATTACH_LIVE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
BSE_ATTACH_HIS = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/"
BSE_HEADERS = {"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}

NSE_HOME = "https://www.nseindia.com/"
NSE_API = "https://www.nseindia.com/api/corporate-announcements"


@dataclass
class RawAnnouncement:
    exchange: str
    source_id: str
    filed_at_utc: datetime
    subject: str
    headline: str | None
    category: str | None
    subcategory: str | None
    attachment_url: str | None
    raw: dict = field(default_factory=dict)


def _ist_to_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=IST).astimezone(timezone.utc).replace(tzinfo=None)


def _parse_bse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.split(".")[0]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return _ist_to_utc(datetime.strptime(s, fmt))
        except ValueError:
            continue
    return None


def fetch_bse(bse_code: str, start: date, end: date, max_pages: int = 6) -> list[RawAnnouncement]:
    out: list[RawAnnouncement] = []
    with make_client(headers=BSE_HEADERS) as c:
        for page in range(1, max_pages + 1):
            params = {
                "pageno": page, "strCat": "-1", "strPrevDate": f"{start:%Y%m%d}", "strScrip": bse_code,
                "strSearch": "P", "strToDate": f"{end:%Y%m%d}", "strType": "C", "subcategory": "-1",
            }
            r = get(c, BSE_API, params=params)
            try:
                data = r.json()
            except ValueError as e:
                raise SourceError("BSE returned non-JSON (format change or block page)") from e
            rows = data.get("Table") or []
            for row in rows:
                filed = _parse_bse_dt(row.get("NEWS_DT") or row.get("DT_TM") or row.get("News_submission_dt"))
                if not filed:
                    continue
                att = (row.get("ATTACHMENTNAME") or "").strip()
                url = None
                if att:
                    url = (BSE_ATTACH_HIS if str(row.get("PDFFLAG")) == "2" else BSE_ATTACH_LIVE) + att
                out.append(
                    RawAnnouncement(
                        exchange="BSE",
                        source_id=str(row.get("NEWSID")),
                        filed_at_utc=filed,
                        subject=(row.get("NEWSSUB") or "").strip(),
                        headline=(row.get("HEADLINE") or row.get("MORE") or "").strip() or None,
                        category=(row.get("CATEGORYNAME") or "").strip() or None,
                        subcategory=(row.get("SUBCATNAME") or "").strip() or None,
                        attachment_url=url,
                        raw={k: row.get(k) for k in ("NEWSID", "SCRIP_CD", "SLONGNAME", "CRITICALNEWS", "NSURL")},
                    )
                )
            total = 0
            try:
                total = int((data.get("Table1") or [{}])[0].get("ROWCNT") or 0)
            except (ValueError, TypeError):
                pass
            if not rows or page * 50 >= total:
                break
    return out


def _parse_nse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M:%S"):
        try:
            return _ist_to_utc(datetime.strptime(s.strip(), fmt))
        except ValueError:
            continue
    return None


def fetch_nse(symbol: str, start: date, end: date) -> list[RawAnnouncement]:
    with make_client(headers={"Referer": NSE_HOME}) as c:
        get(c, NSE_HOME, headers={"Accept": "text/html"}, retries=1)  # sets session cookies
        r = get(
            c, NSE_API,
            params={"index": "equities", "symbol": symbol, "from_date": f"{start:%d-%m-%Y}", "to_date": f"{end:%d-%m-%Y}"},
        )
    try:
        rows = r.json()
    except ValueError as e:
        raise SourceError("NSE returned non-JSON (likely bot protection)") from e
    out = []
    for row in rows if isinstance(rows, list) else rows.get("data", []):
        filed = _parse_nse_dt(row.get("sort_date") or row.get("an_dt"))
        if not filed:
            continue
        text = (row.get("attchmntText") or "").strip()
        out.append(
            RawAnnouncement(
                exchange="NSE",
                source_id=str(row.get("seq_id") or f"{symbol}-{row.get('sort_date')}"),
                filed_at_utc=filed,
                subject=(row.get("desc") or "").strip() + (f": {text[:300]}" if text else ""),
                headline=text or None,
                category=(row.get("desc") or "").strip() or None,
                subcategory=None,
                attachment_url=(row.get("attchmntFile") or None),
                raw={k: row.get(k) for k in ("symbol", "sm_name", "seq_id")},
            )
        )
    return out


# Circuit breaker: after 3 consecutive failures a source is skipped for 10 minutes, so a blocked
# exchange costs a few seconds per run instead of retries for every company.
_breaker: dict[str, dict] = {"BSE": {"fails": 0, "until": 0.0}, "NSE": {"fails": 0, "until": 0.0}}


def _open(src: str) -> bool:
    import time

    return time.monotonic() < _breaker[src]["until"]


def _record(src: str, ok: bool) -> None:
    import time

    b = _breaker[src]
    if ok:
        b["fails"], b["until"] = 0, 0.0
    else:
        b["fails"] += 1
        if b["fails"] >= 3:
            b["until"] = time.monotonic() + 600
            log.warning("%s unreachable 3 times in a row; pausing it for 10 minutes", src)


def fetch_company(symbol: str, bse_code: str | None, start: date, end: date) -> tuple[list[RawAnnouncement], str]:
    """Try BSE, then NSE. Returns (items, source_used). Raises SourceError if both fail."""
    errors = []
    if bse_code and not _open("BSE"):
        try:
            out = fetch_bse(bse_code, start, end)
            _record("BSE", True)
            return out, "BSE"
        except SourceError as e:
            _record("BSE", False)
            errors.append(f"BSE: {e}")
            log.warning("BSE failed for %s: %s", symbol, e)
    elif bse_code:
        errors.append("BSE: paused after repeated failures")
    if not _open("NSE"):
        try:
            out = fetch_nse(symbol, start, end)
            _record("NSE", True)
            return out, "NSE"
        except SourceError as e:
            _record("NSE", False)
            errors.append(f"NSE: {e}")
    else:
        errors.append("NSE: paused after repeated failures")
    raise SourceError("; ".join(errors))
