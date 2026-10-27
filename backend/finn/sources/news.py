"""Company news headlines from Google News RSS (free, no API key).

News is SECONDARY data. FINN shows headlines on the push side only, links out to the publisher,
and never uses news as evidence in research (the brief requires primary sources there).
We store only headline, publisher, time and link — never article text.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

from .http import SourceError, get, make_client

FEED = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
_SUFFIX = re.compile(r"\s*(\(india\)|\b(limited|ltd\.?|corporation|corp\.?))\s*$", re.I)

# How headlines actually name these companies (used for the search query and the relevance filter).
ALIASES = {
    "RELIANCE": ["Reliance Industries", "RIL"], "HDFCBANK": ["HDFC Bank"], "BAJFINANCE": ["Bajaj Finance"],
    "TCS": ["TCS", "Tata Consultancy"], "INFY": ["Infosys"], "BHARTIARTL": ["Bharti Airtel", "Airtel"],
    "LT": ["L&T", "Larsen & Toubro", "Larsen and Toubro"], "HAL": ["HAL", "Hindustan Aeronautics"],
    "SUNPHARMA": ["Sun Pharma", "Sun Pharmaceutical"], "APOLLOHOSP": ["Apollo Hospitals"], "MARUTI": ["Maruti Suzuki", "Maruti"],
    "TITAN": ["Titan Company", "Titan"], "TRENT": ["Trent"], "ITC": ["ITC"], "HINDUNILVR": ["Hindustan Unilever", "HUL"],
    "DIXON": ["Dixon Technologies", "Dixon"], "POLYCAB": ["Polycab"], "TATAPOWER": ["Tata Power"],
    "ASIANPAINT": ["Asian Paints"], "PIDILITIND": ["Pidilite"], "INDIGO": ["IndiGo", "InterGlobe Aviation"],
    "NESTLEIND": ["Nestle India"],
}
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "is", "at", "by", "with", "as", "its", "from", "after", "share", "shares", "stock"}


@dataclass
class Headline:
    title: str
    url: str
    source: str | None
    published_utc: datetime
    guid: str


def short_name(name: str) -> str:
    """'Larsen & Toubro Ltd' -> 'Larsen & Toubro'; 'Dixon Technologies (India) Ltd' -> 'Dixon Technologies'."""
    n = name.strip()
    for _ in range(3):
        n2 = _SUFFIX.sub("", n).strip(" ,.-")
        if n2 == n or len(n2) < 3:
            break
        n = n2
    return n


def terms_for(symbol: str, name: str) -> list[str]:
    if symbol in ALIASES:
        return ALIASES[symbol]
    t = [short_name(name)]
    if len(symbol) >= 4 and symbol.isalpha():
        t.append(symbol)
    return t


def query_for(symbol: str, name: str) -> str:
    q = " OR ".join(f'"{t}"' for t in terms_for(symbol, name))
    return f"({q}) (share OR stock OR results OR NSE) when:7d"


def parse(xml_text: str) -> list[Headline]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise SourceError(f"news feed was not valid RSS: {e}") from e
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        src_el = it.find("source")
        source = src_el.text.strip() if src_el is not None and src_el.text else None
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate") or "")
            pub = pub.astimezone(timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError):
            continue
        if title and link:
            out.append(Headline(title=title, url=link, source=source, published_utc=pub, guid=(it.findtext("guid") or link)))
    return out


def relevant(h: Headline, symbol: str, name: str) -> bool:
    """Keep headlines that actually name the company (Google's matching is loose)."""
    t = h.title.lower()
    for term in terms_for(symbol, name):
        if re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", t):
            return True
    return False


def fetch(symbol: str, name: str) -> list[Headline]:
    url = FEED.format(q=quote_plus(query_for(symbol, name)))
    with make_client(headers={"Accept": "application/rss+xml, application/xml, text/xml"}) as c:
        r = get(c, url, retries=2)
    return [h for h in parse(r.text) if relevant(h, symbol, name)]


def _stem(t: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def title_key(title: str) -> set[str]:
    return {_stem(t) for t in _TOKEN.findall(title.lower()) if t not in _STOP and len(t) > 2}


def same_story(a: set[str], b: set[str]) -> bool:
    """Two headlines about the same story (different publishers). Jaccard on content words."""
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= 0.5
