"""Ingestion orchestration: prices, announcements, classification, scoring, alerts, enrichment.

Runs from the API's background scheduler (local use), `python -m scripts.refresh`, or a cron
hitting POST /api/refresh (deployment). Every run is recorded in ingestion_runs so the UI can show
data freshness honestly.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from .. import config, universe
from ..ai import prompts
from ..ai.llm import LlmUnavailable, generate_json
from ..db import (Announcement, AnnouncementAnalysis, Company, Holding, IngestionRun, NewsItem, Price, get_setting,
                  session_scope, set_setting, utcnow)
from ..sources import announcements as ann_src
from ..sources import news as news_src
from ..sources import prices as price_src
from ..sources.http import SourceError
from . import alerts
from .classify import CATEGORIES, Classification, classify_rule
from .enrich import enrich
from .score import score

log = logging.getLogger("finn.ingest")
IST = timezone(timedelta(hours=5, minutes=30))
_run_lock = threading.Lock()


# --- companies ----------------------------------------------------------------------------
def get_or_create_company(s, symbol: str) -> Company:
    sym = universe.clean_symbol(symbol)
    c = s.execute(select(Company).where(Company.nse_symbol == sym)).scalar_one_or_none()
    if c:
        return c
    info = universe.resolve(sym)
    c = Company(nse_symbol=sym, name=info["name"], bse_code=info.get("bse_code"), isin=info.get("isin"),
                sector=info.get("sector"), is_financial=bool(info.get("is_financial")))
    s.add(c)
    s.flush()
    return c


def bootstrap() -> None:
    """First run: create the demo portfolio (only if the user has no holdings yet)."""
    with session_scope() as s:
        alerts.ensure_default_rules(s)
        if get_setting(s, "bootstrapped"):
            return
        for sym, qty in universe.DEMO_PORTFOLIO.items():
            c = get_or_create_company(s, sym)
            if not s.execute(select(Holding).where(Holding.company_id == c.id)).first():
                s.add(Holding(company_id=c.id, quantity=qty))
        for sym in universe.RESEARCH_PICKS:
            get_or_create_company(s, sym)
        set_setting(s, "bootstrapped", True)


def _start_run(source: str) -> int:
    with session_scope() as s:
        r = IngestionRun(source=source)
        s.add(r)
        s.flush()
        return r.id


def _finish_run(run_id: int, status: str, items: int, detail: str | None = None) -> None:
    with session_scope() as s:
        r = s.get(IngestionRun, run_id)
        r.status, r.items_new, r.detail, r.finished_at = status, items, (detail or "")[:2000], utcnow()


# --- prices -------------------------------------------------------------------------------
def refresh_prices(symbols: list[str] | None = None, with_stats: bool = True) -> dict:
    with session_scope() as s:
        q = select(Company).join(Holding, Holding.company_id == Company.id)
        companies = list(s.execute(q).scalars())
        if symbols:
            companies = list(s.execute(select(Company).where(Company.nse_symbol.in_(symbols))).scalars())
        latest = {c.id: s.execute(select(func.max(Price.date)).where(Price.company_id == c.id)).scalar() for c in companies}
        targets = [(c.id, c.nse_symbol) for c in companies]
    if not targets:
        return {"status": "ok", "new": 0}
    run = _start_run("prices")
    new, errors, source = 0, [], "yahoo"
    need_long = any(latest[cid] is None for cid, _ in targets)
    try:
        data = price_src.fetch_history([sym for _, sym in targets], period="2y" if need_long else "1mo")
    except SourceError as e:
        errors.append(str(e))
        data, source = {}, "nse_bhavcopy"
        # Fallback: official NSE end-of-day files for the last few sessions.
        sym_set = {sym for _, sym in targets}
        d = price_src.expected_last_session()
        frames = []
        for _ in range(5):
            try:
                df = price_src.fetch_nse_bhavcopy(d)
                frames.append(df[df["symbol"].isin(sym_set)])
            except (SourceError, KeyError, ValueError) as e2:
                errors.append(f"bhavcopy {d}: {e2}")
            d -= timedelta(days=1)
            while d.weekday() >= 5:
                d -= timedelta(days=1)
        if frames:
            import pandas as pd

            allf = pd.concat(frames)
            for sym in sym_set:
                sub = allf[allf["symbol"] == sym]
                if not sub.empty:
                    data[sym] = sub.drop(columns=["symbol"])
    with session_scope() as s:
        for cid, sym in targets:
            df = data.get(sym)
            if df is None:
                continue
            # One query per company for existing rows (not one per day: ~500 round trips to a remote DB).
            have = {p.date: p for p in s.execute(select(Price).where(Price.company_id == cid)).scalars()}
            for row in df.itertuples(index=False):
                d = row.date if isinstance(row.date, date) else row.date.date()
                p = have.get(d)
                if p is None:
                    p = Price(company_id=cid, date=d)
                    s.add(p)
                    new += 1
                p.open, p.high, p.low = getattr(row, "open", None), getattr(row, "high", None), getattr(row, "low", None)
                p.close, p.volume = float(row.close), float(getattr(row, "volume", 0) or 0)
                p.source, p.fetched_at = source, utcnow()
        rules = alerts.get_rules(s)
        fired = 0
        for cid, _ in targets:
            fired += alerts.evaluate_prices(s, s.get(Company, cid), rules)
    if with_stats and data:  # don't hammer Yahoo for stats if prices already failed
        _refresh_stats(targets)
    missing = [sym for _, sym in targets if sym not in data]
    status = "ok" if not missing else ("partial" if data else "failed")
    detail = "; ".join(errors + ([f"no data: {', '.join(missing)}"] if missing else []))
    _finish_run(run, status, new, detail)
    return {"status": status, "new": new, "alerts": fired, "missing": missing}


def refresh_stats(symbols: list[str]) -> None:
    """Key stats (and website, for the logo) only, without re-downloading prices."""
    with session_scope() as s:
        targets = [(c.id, c.nse_symbol) for c in s.execute(select(Company).where(Company.nse_symbol.in_(symbols))).scalars()]
    _refresh_stats(targets)


def _refresh_stats(targets) -> None:
    today = utcnow().date()
    fails = 0
    for cid, sym in targets:
        with session_scope() as s:
            c = s.get(Company, cid)
            if c.stats_updated_at and c.stats_updated_at.date() == today and c.website is not None:
                continue
        try:
            st = price_src.fetch_key_stats(sym)
            fails = 0
        except SourceError:
            fails += 1
            if fails >= 3:
                log.warning("key stats unavailable; skipping the rest this run")
                return
            continue
        with session_scope() as s:
            c = s.get(Company, cid)
            c.market_cap_cr, c.pe, c.dividend_yield = st["market_cap_cr"], st["pe"], st["dividend_yield"]
            if not c.sector and st.get("industry"):
                c.sector = st["industry"]
            c.website = st.get("website") or ""  # "" = Yahoo has none; don't ask again today
            c.stats_updated_at = utcnow()


# --- announcements ---------------------------------------------------------------------------
def _llm_classify(items: list[tuple[int, str, str | None]]) -> dict[int, str]:
    """Batch-classify announcements the rules couldn't place. One cheap call per 40 items."""
    out: dict[int, str] = {}
    for i in range(0, len(items), 40):
        batch = items[i:i + 40]
        payload = json.dumps([{"id": aid, "subject": subj[:240], "detail": (hl or "")[:240]} for aid, subj, hl in batch])
        try:
            res = generate_json("classify", "You classify stock-exchange filings. JSON only.",
                                prompts.CLASSIFY_PROMPT.format(items=payload), tier="fast", version="classify-v1")
        except LlmUnavailable:
            break
        for it in res.get("items", []):
            if it.get("category") in CATEGORIES:
                try:
                    out[int(it["id"])] = it["category"]
                except (TypeError, ValueError):
                    pass
    return out


def store_announcements(s, company: Company, raws: list[ann_src.RawAnnouncement], cares: list[str], rules: dict) -> list[int]:
    new_ids, unknown = [], []
    for r in raws:
        if not r.source_id or r.source_id == "None":
            continue
        exists = s.execute(select(Announcement.id).where(Announcement.exchange == r.exchange,
                                                         Announcement.source_id == r.source_id)).first()
        if exists:
            continue
        if r.exchange == "NSE":  # avoid duplicating a filing we already have from BSE
            dup = s.execute(select(Announcement.id).where(
                Announcement.company_id == company.id, Announcement.exchange == "BSE",
                Announcement.filed_at.between(r.filed_at_utc - timedelta(minutes=15), r.filed_at_utc + timedelta(minutes=15)),
            )).first()
            if dup:
                continue
        ann = Announcement(company_id=company.id, exchange=r.exchange, source_id=r.source_id, filed_at=r.filed_at_utc,
                           subject=r.subject or "(no subject)", headline=r.headline, exchange_category=r.category,
                           exchange_subcategory=r.subcategory, attachment_url=r.attachment_url, raw=r.raw)
        s.add(ann)
        s.flush()
        cl = classify_rule(ann.subject, ann.headline, ann.exchange_category, ann.exchange_subcategory)
        if cl is None:
            unknown.append((ann.id, ann.subject, ann.headline))
            cl = Classification("unclassified", None, "fallback")
        sc, reasons = score(cl.category, cl.subtype, cares)
        s.add(AnnouncementAnalysis(announcement_id=ann.id, category=cl.category, subtype=cl.subtype,
                                   category_method=cl.method, importance=sc, importance_reasons=reasons))
        new_ids.append(ann.id)
    if unknown:
        got = _llm_classify(unknown)
        for aid, cat in got.items():
            a = s.get(AnnouncementAnalysis, aid)
            if a:
                a.category, a.category_method = cat, "llm"
                a.importance, a.importance_reasons = score(cat, None, cares)
    s.flush()
    for aid in new_ids:
        alerts.evaluate_announcement(s, s.get(Announcement, aid), rules)
    return new_ids


def refresh_announcements(days_back: int | None = None, symbols: list[str] | None = None) -> dict:
    with session_scope() as s:
        if symbols:
            companies = list(s.execute(select(Company).where(Company.nse_symbol.in_(symbols))).scalars())
        else:
            companies = list(s.execute(select(Company).join(Holding, Holding.company_id == Company.id)).scalars())
        first = s.execute(select(func.count(Announcement.id))).scalar() == 0
        targets = [(c.id, c.nse_symbol, c.bse_code) for c in companies]
    if days_back is None:
        days_back = 10 if first else 2
    end = datetime.now(IST).date()
    start = end - timedelta(days=days_back)
    run = _start_run("announcements")
    new, errors, used = 0, [], set()
    for cid, sym, code in targets:
        try:
            raws, src = ann_src.fetch_company(sym, code, start, end)
            used.add(src)
        except SourceError as e:
            errors.append(f"{sym}: {e}")
            continue
        with session_scope() as s:
            cares = alerts.get_rules(s)["categories"]
            rules = alerts.get_rules(s)
            new += len(store_announcements(s, s.get(Company, cid), raws, cares, rules))
    status = "ok" if not errors else ("partial" if len(errors) < len(targets) else "failed")
    _finish_run(run, status, new, (f"source: {', '.join(sorted(used))}. " if used else "") + "; ".join(errors[:6]))
    return {"status": status, "new": new, "errors": errors[:6]}


def enrich_pending(limit: int | None = None) -> dict:
    limit = limit or config.ENRICH_LIMIT_PER_RUN
    with session_scope() as s:
        q = (select(AnnouncementAnalysis.announcement_id)
             .join(Announcement, Announcement.id == AnnouncementAnalysis.announcement_id)
             .where(AnnouncementAnalysis.enrich_status.in_(["pending", "needs_key"]))
             .order_by(AnnouncementAnalysis.importance.desc(), Announcement.filed_at.desc()).limit(limit))
        ids = [r[0] for r in s.execute(q)]
    done = 0
    for aid in ids:
        with session_scope() as s:
            ann = s.get(Announcement, aid)
            cares = alerts.get_rules(s)["categories"]
            # Re-use work if the same PDF was already analysed (e.g. filed on both exchanges).
            enrich(s, ann, cares)
            done += ann.analysis.enrich_status == "done"
    return {"processed": len(ids), "enriched": done}


def refresh_news(symbols: list[str] | None = None) -> dict:
    """Headlines from Google News for each holding. Same story from several publishers is grouped."""
    with session_scope() as s:
        q = select(Company).join(Holding, Holding.company_id == Company.id)
        if symbols:
            q = select(Company).where(Company.nse_symbol.in_(symbols))
        targets = [(c.id, c.nse_symbol, c.name) for c in s.execute(q).scalars()]
    run = _start_run("news")
    new, errors, fails = 0, [], 0
    for cid, sym, name in targets:
        try:
            heads = news_src.fetch(sym, name)
            fails = 0
        except SourceError as e:
            errors.append(f"{sym}: {e}")
            fails += 1
            if fails >= 3:
                errors.append("news source unreachable; stopped this run")
                break
            continue
        with session_scope() as s:
            since = utcnow() - timedelta(days=10)
            recent = list(s.execute(select(NewsItem).where(NewsItem.company_id == cid, NewsItem.published_at >= since)).scalars())
            keys = [(n.story_id or n.id, news_src.title_key(n.title)) for n in recent]
            for h in sorted(heads, key=lambda x: x.published_utc):
                if h.published_utc < since:
                    continue
                if s.execute(select(NewsItem.id).where(NewsItem.url == h.url)).first():
                    continue
                k = news_src.title_key(h.title)
                story = next((sid for sid, kk in keys if news_src.same_story(k, kk)), None)
                item = NewsItem(company_id=cid, url=h.url, title=h.title[:500], source=(h.source or "")[:120] or None,
                                published_at=h.published_utc, story_id=story)
                s.add(item)
                s.flush()
                if story is None:
                    item.story_id = item.id
                keys.append((item.story_id, k))
                new += 1
    status = "ok" if not errors else ("partial" if new or len(errors) < len(targets) else "failed")
    _finish_run(run, status, new, "; ".join(errors[:5]))
    return {"status": status, "new": new, "errors": errors[:5]}


def refresh_all(include_prices: bool = True) -> dict:
    if not _run_lock.acquire(blocking=False):
        return {"status": "busy"}
    try:
        out = {}
        if include_prices:
            out["prices"] = refresh_prices()
        out["announcements"] = refresh_announcements()
        out["news"] = refresh_news()
        out["enrich"] = enrich_pending()
        with session_scope() as s:
            set_setting(s, "last_refresh", utcnow().isoformat())
        return out
    finally:
        _run_lock.release()


# --- background scheduler (local single-process use) -------------------------------------------
def _should_refresh_prices() -> bool:
    with session_scope() as s:
        last = s.execute(select(func.max(Price.date))).scalar()
        last_run = s.execute(select(IngestionRun).where(IngestionRun.source == "prices")
                             .order_by(IngestionRun.started_at.desc()).limit(1)).scalar_one_or_none()
    if last is None:
        return True
    if last_run and utcnow() - last_run.started_at < timedelta(hours=1):
        return False
    return last < price_src.expected_last_session()


def scheduler_loop(stop: threading.Event) -> None:
    log.info("scheduler started (every %s min)", config.ANNOUNCEMENT_POLL_MINUTES)
    while not stop.is_set():
        try:
            refresh_all(include_prices=_should_refresh_prices())
        except Exception:
            log.exception("scheduled refresh failed")
        stop.wait(config.ANNOUNCEMENT_POLL_MINUTES * 60)
