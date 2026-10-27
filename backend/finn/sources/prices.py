"""End-of-day prices and volumes.

Primary:  Yahoo Finance via yfinance (unofficial; NSE tickers use the .NS suffix).
Fallback: NSE's official daily "bhavcopy" CSV (UDiFF format) for the most recent sessions.

This is END-OF-DAY data. FINN never labels it as live.
"""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from .http import SourceError, get, make_client

log = logging.getLogger("finn.prices")
IST = timezone(timedelta(hours=5, minutes=30))


def fetch_history(symbols: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """Return {symbol: DataFrame[date, open, high, low, close, volume]} from Yahoo."""
    import yfinance as yf

    if not symbols:
        return {}
    tickers = [f"{s}.NS" for s in symbols]
    try:
        df = yf.download(
            tickers, period=period, interval="1d", group_by="ticker", auto_adjust=True,
            progress=False, threads=True,
        )
    except Exception as e:  # yfinance raises many exception types
        raise SourceError(f"Yahoo download failed: {e}") from e
    if df is None or df.empty:
        raise SourceError("Yahoo returned no data (possibly rate-limited or blocked)")
    out: dict[str, pd.DataFrame] = {}
    for sym, t in zip(symbols, tickers):
        try:
            sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
        except KeyError:
            continue
        sub = sub.rename(columns=str.lower)
        if "close" not in sub:
            continue
        sub = sub.dropna(subset=["close"])
        if sub.empty:
            continue
        sub = sub.reset_index().rename(columns={"Date": "date", "index": "date"})
        sub["date"] = pd.to_datetime(sub["date"]).dt.date
        out[sym] = sub[[c for c in ["date", "open", "high", "low", "close", "volume"] if c in sub]]
    return out


def fetch_key_stats(symbol: str) -> dict:
    """Market cap (₹ crore), trailing P/E and dividend yield from Yahoo. Best effort."""
    import yfinance as yf

    try:
        info = yf.Ticker(f"{symbol}.NS").get_info() or {}
    except Exception as e:
        raise SourceError(f"Yahoo info failed for {symbol}: {e}") from e
    mc = info.get("marketCap")
    dy = info.get("dividendYield")
    # yfinance has reported dividendYield both as a fraction and as a percent across versions.
    if dy is not None and dy < 0.5:
        dy = dy * 100
    return {
        "market_cap_cr": (mc / 1e7) if mc else None,
        "pe": info.get("trailingPE"),
        "dividend_yield": dy,
        "industry": info.get("industry"),
        "website": info.get("website"),
    }


def fetch_nse_bhavcopy(day: date) -> pd.DataFrame:
    """Official NSE end-of-day file for one session (UDiFF format, introduced July 2024)."""
    url = (
        "https://nsearchives.nseindia.com/content/cm/"
        f"BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
    )
    with make_client(headers={"Referer": "https://www.nseindia.com/"}) as c:
        r = get(c, url, retries=2)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        raw = z.read(z.namelist()[0]).decode()
    df = pd.read_csv(io.StringIO(raw))
    df = df[df.get("SctySrs", "EQ") == "EQ"]
    return pd.DataFrame(
        {
            "symbol": df["TckrSymb"],
            "date": day,
            "open": df["OpnPric"],
            "high": df["HghPric"],
            "low": df["LwPric"],
            "close": df["ClsPric"],
            "volume": df["TtlTradgVol"],
        }
    )


def expected_last_session(now: datetime | None = None) -> date:
    """Most recent weekday whose session has closed (NSE closes 15:30 IST; data settles later).

    Exchange holidays aren't modelled, so on a holiday the UI says "may be a market holiday"."""
    now = (now or datetime.now(timezone.utc)).astimezone(IST)
    d = now.date()
    if now.hour < 18:  # give EOD sources time to publish
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d
