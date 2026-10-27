"""Demo portfolio, research picks, and NSE symbol resolution for any ticker."""
from __future__ import annotations

import csv
import io
import json
import logging
import re

from . import config
from .sources.http import SourceError, get, make_client

log = logging.getLogger("finn.universe")

# BSE scrip codes are needed for BSE announcements. They are re-checked against BSE's scrip list
# at runtime when that list is reachable.
KNOWN = {
    # symbol: (name, bse_code, sector, is_financial)
    "RELIANCE": ("Reliance Industries Ltd", "500325", "Energy & Conglomerate", False),
    "HDFCBANK": ("HDFC Bank Ltd", "500180", "Banking", True),
    "BAJFINANCE": ("Bajaj Finance Ltd", "500034", "NBFC", True),
    "TCS": ("Tata Consultancy Services Ltd", "532540", "IT Services", False),
    "INFY": ("Infosys Ltd", "500209", "IT Services", False),
    "BHARTIARTL": ("Bharti Airtel Ltd", "532454", "Telecom", False),
    "LT": ("Larsen & Toubro Ltd", "500510", "Infrastructure", False),
    "HAL": ("Hindustan Aeronautics Ltd", "541154", "Defence", False),
    "SUNPHARMA": ("Sun Pharmaceutical Industries Ltd", "524715", "Pharma", False),
    "APOLLOHOSP": ("Apollo Hospitals Enterprise Ltd", "508869", "Healthcare", False),
    "MARUTI": ("Maruti Suzuki India Ltd", "532500", "Automobiles", False),
    "TITAN": ("Titan Company Ltd", "500114", "Consumer Durables", False),
    "TRENT": ("Trent Ltd", "500251", "Retail", False),
    "ITC": ("ITC Ltd", "500875", "FMCG", False),
    "HINDUNILVR": ("Hindustan Unilever Ltd", "500696", "FMCG", False),
    "DIXON": ("Dixon Technologies (India) Ltd", "540699", "Electronics Manufacturing", False),
    "POLYCAB": ("Polycab India Ltd", "542652", "Cables & Wires", False),
    "TATAPOWER": ("Tata Power Company Ltd", "500400", "Power", False),
    # Ad-hoc research picks (outside the portfolio)
    "ASIANPAINT": ("Asian Paints Ltd", "500820", "Paints", False),
    "PIDILITIND": ("Pidilite Industries Ltd", "500331", "Chemicals", False),
    "INDIGO": ("InterGlobe Aviation Ltd", "539448", "Aviation", False),
    "NESTLEIND": ("Nestle India Ltd", "500790", "FMCG", False),
}

# Demo portfolio with illustrative share quantities (labelled "Demo portfolio" in the UI).
DEMO_PORTFOLIO = {
    "RELIANCE": 60, "HDFCBANK": 80, "BAJFINANCE": 40, "TCS": 20, "INFY": 50, "BHARTIARTL": 45,
    "LT": 20, "HAL": 15, "SUNPHARMA": 40, "APOLLOHOSP": 10, "MARUTI": 5, "TITAN": 20,
    "TRENT": 10, "ITC": 200, "HINDUNILVR": 25, "DIXON": 4, "POLYCAB": 10, "TATAPOWER": 150,
}
RESEARCH_PICKS = ["ASIANPAINT", "PIDILITIND", "INDIGO", "NESTLEIND"]

_FIN_HINTS = re.compile(r"\b(bank|finance|financial|insurance|nbfc|capital|housing fin)", re.I)

_BSE_LIST_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
_NSE_LIST_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
_CACHE = config.DATA_DIR / "symbol_master.json"


def clean_symbol(s: str) -> str:
    s = (s or "").strip().upper()
    s = re.sub(r"\.(NS|BO)$", "", s)
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", s):
        raise ValueError("Enter an NSE symbol like RELIANCE or TCS")
    return s


_MEMO: dict | None = None
_FAILED_AT: float = 0.0


def _load_master() -> dict:
    """Symbol master (NSE list + BSE codes). Cached on disk; a failed fetch is retried after 15 min."""
    global _MEMO, _FAILED_AT
    import time

    if _MEMO is not None:
        return _MEMO
    if _FAILED_AT and time.time() - _FAILED_AT < 900:
        return {}
    m = _fetch_master()
    if m:
        _MEMO = m
    else:
        _FAILED_AT = time.time()
    return m


def warm_master() -> None:
    """Load the symbol master in the background so the first search isn't slow."""
    import threading

    threading.Thread(target=_load_master, daemon=True, name="symbol-master").start()


def _fetch_master() -> dict:
    if _CACHE.exists():
        try:
            return json.loads(_CACHE.read_text())
        except Exception:
            pass
    master: dict[str, dict] = {}
    try:
        with make_client(headers={"Accept": "text/csv,*/*"}) as c:
            r = get(c, _NSE_LIST_URL, retries=2)
        for row in csv.DictReader(io.StringIO(r.text)):
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            sym = row.get("SYMBOL")
            if sym and row.get("SERIES", "EQ") in ("EQ", "BE", "BZ", "SM", "ST"):
                master[sym] = {"name": row.get("NAME OF COMPANY", sym), "isin": row.get("ISIN NUMBER")}
    except SourceError as e:
        log.warning("NSE symbol list unavailable: %s", e)
    try:
        with make_client(headers={"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}) as c:
            r = get(c, _BSE_LIST_URL, params={"Group": "", "Scripcode": "", "industry": "", "segment": "Equity", "status": "Active"}, retries=2)
        rows = r.json()
        by_isin = {v.get("isin"): k for k, v in master.items() if v.get("isin")}
        for row in rows if isinstance(rows, list) else []:
            code = str(row.get("SCRIP_CD") or "").strip()
            sid = str(row.get("scrip_id") or "").strip().upper()
            isin = str(row.get("ISIN_NUMBER") or "").strip()
            sym = by_isin.get(isin) or sid
            if not code or not sym:
                continue
            entry = master.setdefault(sym, {"name": row.get("Issuer_Name") or row.get("Scrip_Name") or sym, "isin": isin})
            entry["bse_code"] = code
            entry["industry"] = row.get("INDUSTRY") or row.get("Industry")
    except (SourceError, ValueError) as e:
        log.warning("BSE scrip list unavailable: %s", e)
    if master:
        _CACHE.write_text(json.dumps(master))
    return master


def resolve(symbol: str) -> dict:
    """Return {symbol, name, bse_code, isin, sector, is_financial} for an NSE symbol.

    Raises LookupError if the symbol cannot be found anywhere."""
    sym = clean_symbol(symbol)
    if sym in KNOWN:
        name, code, sector, fin = KNOWN[sym]
        return {"symbol": sym, "name": name, "bse_code": code, "isin": None, "sector": sector, "is_financial": fin}
    master = _load_master()
    if sym in master:
        m = master[sym]
        name = m.get("name") or sym
        return {
            "symbol": sym,
            "name": name,
            "bse_code": m.get("bse_code"),
            "isin": m.get("isin"),
            "sector": m.get("industry"),
            "is_financial": bool(_FIN_HINTS.search(f"{name} {m.get('industry') or ''}")),
        }
    # Last resort: ask Yahoo whether the NSE ticker exists.
    try:
        import yfinance as yf

        info = yf.Ticker(f"{sym}.NS").get_info() or {}
        name = info.get("longName") or info.get("shortName")
        if name:
            sector = info.get("industry") or info.get("sector")
            return {
                "symbol": sym, "name": name, "bse_code": None, "isin": None, "sector": sector,
                "is_financial": (info.get("sector") == "Financial Services"),
            }
    except Exception as e:  # pragma: no cover - network
        log.warning("Yahoo lookup failed for %s: %s", sym, e)
    raise LookupError(f"Could not find NSE symbol {sym}. Check the spelling (e.g. RELIANCE, TCS).")


def search(q: str, limit: int = 8) -> list[dict]:
    q = (q or "").strip().upper()
    if not q:
        return []
    out = []
    for sym, (name, *_rest) in KNOWN.items():
        if sym.startswith(q) or q in name.upper():
            out.append({"symbol": sym, "name": name})
    if len(out) < limit:
        master = _load_master()
        for sym, m in master.items():
            if len(out) >= limit:
                break
            if sym in KNOWN:
                continue
            if sym.startswith(q) or q in (m.get("name") or "").upper():
                out.append({"symbol": sym, "name": m.get("name") or sym})
    out.sort(key=lambda r: (not r["symbol"].startswith(q), r["symbol"]))
    return out[:limit]
