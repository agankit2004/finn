"""FINN HTTP API (FastAPI). Run: uvicorn finn.api:app --reload --port 8000"""
from __future__ import annotations

import logging
import re
import threading
from datetime import date, datetime, timedelta, timezone

import ipaddress

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from . import config, universe
from .db import (AlertEvent, AlertRule, Announcement, AnnouncementAnalysis, Company, Document, Holding, IngestionRun,
                 Job, LlmCall, NewsItem, Price, ResearchReport, get_setting, init_db, session_scope, set_setting, utcnow)
from .pipeline import alerts as alerts_mod
from .pipeline import ingest
from .pipeline.classify import CATEGORIES, LABELS
from .pipeline.score import ROUTINE_THRESHOLD, score
from .research import ask as ask_mod
from .research import build as research
from .sources import pdfs
from .sources.http import SourceError
from .sources.prices import expected_last_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("finn.api")
IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="FINN API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
_stop = threading.Event()
_last_manual_refresh: datetime | None = None


@app.on_event("startup")
def _startup() -> None:
    init_db()
    if config.SAMPLE_MODE:
        from . import sample

        sample.load()
        log.warning("SAMPLE MODE: serving synthetic data. Do not present it as real.")
    else:
        ingest.bootstrap()
        universe.warm_master()
        if config.RUN_SCHEDULER:
            threading.Thread(target=ingest.scheduler_loop, args=(_stop,), daemon=True, name="scheduler").start()


@app.on_event("shutdown")
def _shutdown() -> None:
    _stop.set()


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


# --- helpers ---------------------------------------------------------------------------------------
def _prices(s, company_id: int, limit: int = 60) -> list[Price]:
    return list(s.execute(select(Price).where(Price.company_id == company_id).order_by(Price.date.desc()).limit(limit)).scalars())[::-1]


def _logo(c: Company) -> str | None:
    """Logo for the company's website domain. logo.dev when a key is set (clean logos for most companies),
    else the site's own icon via Google's favicon service. Either way the UI falls back to initials."""
    if not c.website:
        return None
    host = re.sub(r"^https?://", "", c.website).split("/")[0].removeprefix("www.")
    if not host:
        return None
    if config.LOGO_DEV_TOKEN.startswith("pk_"):  # never put a secret (sk_) key into a page
        # fallback=404: no generated placeholder, so the UI shows initials instead
        return f"https://img.logo.dev/{host}?token={config.LOGO_DEV_TOKEN}&size=128&format=png&fallback=404"
    return f"https://www.google.com/s2/favicons?domain={host}&sz=128"


def _clean_subject(subj: str) -> str:
    s = re.sub(r"^(announcement under regulation 30 \(lodr\)\s*[-–:]\s*)", "", subj or "", flags=re.I)
    s = re.sub(r"^(intimation|disclosure) under regulation \d+[^-–:]*[-–:]\s*", "", s, flags=re.I)
    s = s.strip(" -–:")
    return s[:1].upper() + s[1:] if s else subj


def _title(ann: Announcement, a: AnnouncementAnalysis | None) -> str:
    sym = ann.company.nse_symbol
    st = (a.structured or {}) if a else {}
    if a and st.get("kind") == "results" and not st.get("error"):
        rows = {r["metric"]: r for r in st.get("rows", [])}
        pat = rows.get("pat")
        bit = f": PAT {pat['yoy']['label']} YoY" if pat and pat["yoy"]["label"] not in ("n/a", "n/m") else ""
        return f"{sym} {st.get('quarter')} results{bit}"
    if a and st.get("kind") == "management_change" and st.get("people"):
        p = st["people"][0]
        verb = {"appointed": "appointed", "resigned": "resigns", "retired": "retires", "ceased": "steps down",
                "reappointed": "reappointed", "redesignated": "redesignated", "passed_away": "passes away"}.get(p.get("change"), p.get("change") or "")
        role = p.get("role") or "role"
        if p.get("change") == "appointed":
            return f"{sym}: {p['name']} {verb} as {role}"
        return f"{sym}: {role} {p['name']} {verb}"
    return f"{sym}: {_clean_subject(ann.subject)}"


def _spark(rows: list[Price], n: int = 30) -> list[float]:
    return [round(r.close, 2) for r in rows[-n:]]


_PRICE_SOURCES = {
    "yahoo": ("Yahoo Finance", "End-of-day price and volume", "https://finance.yahoo.com/quote/{sym}.NS/history/"),
    "nse_bhavcopy": ("NSE bhavcopy", "NSE's official end-of-day price file", "https://www.nseindia.com/all-reports"),
}


_SAMPLE_SOURCE = {"name": "Sample data", "kind": "Synthetic, for demo only: not a real price or filing", "url": None, "label": None}


def _price_source(sym: str, source: str | None) -> dict:
    if source == "sample" or config.SAMPLE_MODE:
        return _SAMPLE_SOURCE
    name, kind, url = _PRICE_SOURCES.get(source or "yahoo", _PRICE_SOURCES["yahoo"])
    return {"name": name, "kind": kind, "url": url.format(sym=sym), "label": f"{sym} price history on {name}"}


def _ann_source(ann: Announcement) -> dict:
    if ann.exchange == "SAMPLE":
        return _SAMPLE_SOURCE
    exch = {"BSE": "BSE (Bombay Stock Exchange)", "NSE": "NSE (National Stock Exchange)"}.get(ann.exchange, ann.exchange)
    via = " Found through the company's screener.in page; the document is the original on BSE." \
        if (ann.raw or {}).get("via") == "screener" else ""
    return {"name": exch, "kind": "Company filing to the stock exchange (primary source)." + via,
            "url": ann.attachment_url, "label": "Original filing on the exchange website" if ann.attachment_url else None}


def _ann_item(s, ann: Announcement, price_cache: dict) -> dict:
    a = ann.analysis
    cid = ann.company_id
    if cid not in price_cache:
        rows = _prices(s, cid, 40)
        price_cache[cid] = {"stats": alerts_mod.price_stats(rows), "spark": _spark(rows)}
    pc = price_cache[cid]
    imp = a.importance if a else 0
    return {
        "id": f"a{ann.id}", "type": "announcement", "announcement_id": ann.id,
        "category": a.category if a else "unclassified", "category_label": LABELS.get(a.category if a else "unclassified"),
        "subtype": a.subtype if a else None, "classified_by": a.category_method if a else None,
        "importance": round(imp), "reasons": (a.importance_reasons or []) if a else [], "routine": imp < ROUTINE_THRESHOLD,
        "title": _title(ann, a), "subject": ann.subject, "summary": a.summary if a else None,
        "structured": a.structured if a else None, "enrich_status": a.enrich_status if a else None,
        "enrich_error": a.enrich_error if a else None,
        "time": iso(ann.filed_at), "exchange": ann.exchange, "has_file": bool(ann.attachment_url),
        "source_url": ann.attachment_url, "source": _ann_source(ann),
        "company": {"symbol": ann.company.nse_symbol, "name": ann.company.name},
        "price": {**{k: pc["stats"].get(k) for k in ("close", "change_pct", "date")}, "spark": pc["spark"]},
        "sample": ann.exchange == "SAMPLE",
    }


def _alert_item(s, ev: AlertEvent, price_cache: dict) -> dict:
    cid = ev.company_id
    if cid not in price_cache or "sources" not in price_cache[cid]:
        rows = _prices(s, cid, 40)
        price_cache[cid] = {"stats": alerts_mod.price_stats(rows), "spark": _spark(rows),
                            "sources": {r.date.isoformat(): r.source for r in rows}}  # which feed each day came from
    ob = ev.observed or {}
    mag = abs(ob.get("change_pct") or 0) if ev.kind == "price" else (ob.get("volume_mult") or 0)
    imp = min(95, 55 + mag * (4 if ev.kind == "price" else 8))
    return {
        "id": f"e{ev.id}", "type": ev.kind, "alert_id": ev.id, "category": "price", "category_label": "Price alert" if ev.kind == "price" else "Volume alert",
        "importance": round(imp), "reasons": [f"crossed your threshold ({ob.get('threshold')}{'%' if ev.kind == 'price' else '×'})"],
        "routine": False, "title": ev.title,
        "summary": _alert_summary(ev.kind, ob),
        "structured": {"kind": ev.kind, **ob}, "time": iso(ev.occurred_at), "exchange": "EOD",
        "source": _price_source(ev.company.nse_symbol, price_cache[cid]["sources"].get(ob.get("date") or "")),
        "company": {"symbol": ev.company.nse_symbol, "name": ev.company.name},
        "price": {**{k: price_cache[cid]["stats"].get(k) for k in ("close", "change_pct", "date")}, "spark": price_cache[cid]["spark"]},
        "seen": ev.seen, "sample": ev.company.source == "sample",
    }


def _alert_summary(kind: str, ob: dict) -> str:
    bits = []
    if ob.get("change_pct") is not None:
        bits.append(f"Closed at ₹{ob.get('close'):,.2f} ({ob['change_pct']:+.2f}%)")
    if ob.get("volume_mult") is not None:
        bits.append(f"volume {ob['volume_mult']:.1f}× its 20-day average")
    d = ob.get("date")
    return (", ".join(bits) + (f" on {datetime.fromisoformat(d):%d %b}" if d else "") + ". End-of-day data.") if bits else ""


# --- status ---------------------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/status")
def status():
    with session_scope() as s:
        runs = {}
        for src in ("prices", "announcements", "news"):
            r = s.execute(select(IngestionRun).where(IngestionRun.source == src).order_by(IngestionRun.started_at.desc()).limit(1)).scalar_one_or_none()
            ok = s.execute(select(IngestionRun).where(IngestionRun.source == src, IngestionRun.status.in_(["ok", "partial"]))
                           .order_by(IngestionRun.started_at.desc()).limit(1)).scalar_one_or_none()
            runs[src] = {"last_run": iso(r.started_at) if r else None, "status": r.status if r else None,
                         "detail": r.detail if r else None, "last_success": iso(ok.finished_at) if ok else None}
        last_price = s.execute(select(func.max(Price.date))).scalar()
        exp = expected_last_session()
        calls = s.execute(
            select(LlmCall.purpose, LlmCall.model, LlmCall.cache_hit, func.count(), func.sum(LlmCall.input_tokens),
                   func.sum(LlmCall.output_tokens)).group_by(LlmCall.purpose, LlmCall.model, LlmCall.cache_hit)).all()
        ledger = {"calls": 0, "cache_hits": 0, "input_tokens": 0, "output_tokens": 0, "by_purpose": {}}
        for purpose, model, hit, n, tin, tout in calls:
            if hit:
                ledger["cache_hits"] += n
            else:
                ledger["calls"] += n
            ledger["input_tokens"] += tin or 0
            ledger["output_tokens"] += tout or 0
            bp = ledger["by_purpose"].setdefault(purpose, {"calls": 0, "cache_hits": 0, "tokens": 0, "models": set()})
            bp["cache_hits" if hit else "calls"] += n
            bp["tokens"] += (tin or 0) + (tout or 0)
            if not hit:
                bp["models"].add(model)
        for bp in ledger["by_purpose"].values():
            bp["models"] = sorted(bp["models"])
        n_ann = s.execute(select(func.count(Announcement.id))).scalar()
        by_method = dict(s.execute(select(AnnouncementAnalysis.category_method, func.count()).group_by(AnnouncementAnalysis.category_method)).all())
        return {
            "sample_mode": config.SAMPLE_MODE,
            "user_name": config.USER_NAME or get_setting(s, "user_name", ""),
            "llm": {"enabled": config.llm_enabled(), "fast_model": config.GEMINI_FAST_MODEL, "smart_model": config.GEMINI_SMART_MODEL,
                    "groq": bool(config.GROQ_API_KEY)},
            "runs": runs,
            "prices": {"as_of": last_price.isoformat() if last_price else None, "expected_session": exp.isoformat(),
                       "stale": bool(last_price and last_price < exp), "kind": "end_of_day"},
            "announcements": {"total": n_ann, "classified_by": by_method},
            "ledger": ledger,
            "server_time": iso(utcnow()),
        }


@app.post("/api/refresh")
def refresh(bg: BackgroundTasks, scope: str = "all", x_finn_secret: str | None = Header(default=None)):
    global _last_manual_refresh
    if config.SAMPLE_MODE:
        return {"status": "sample_mode", "message": "Refresh is disabled in sample mode."}
    if config.REFRESH_SECRET and x_finn_secret != config.REFRESH_SECRET:
        # Without the secret, allow at most one refresh every 5 minutes (public demo button).
        if _last_manual_refresh and utcnow() - _last_manual_refresh < timedelta(minutes=5):
            return {"status": "throttled", "message": "Refreshed recently; try again in a few minutes."}
    _last_manual_refresh = utcnow()
    if scope == "prices":
        bg.add_task(ingest.refresh_prices)
    elif scope == "announcements":
        bg.add_task(lambda: (ingest.refresh_announcements(), ingest.enrich_pending()))
    else:
        bg.add_task(ingest.refresh_all)
    return {"status": "started"}


# --- AI key (local setup convenience) -------------------------------------------------------------
class KeyIn(BaseModel):
    gemini_api_key: str = Field(min_length=20, max_length=200)


def _local_request(request: Request) -> bool:
    try:
        ip = ipaddress.ip_address((request.client.host if request.client else "") or "0.0.0.0")
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def _write_env(key: str, value: str) -> None:
    env = config.BACKEND_DIR / ".env"
    lines = env.read_text().splitlines() if env.exists() else []
    out, done = [], False
    for ln in lines:
        if ln.strip().startswith(f"{key}="):
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(ln)
    if not done:
        out.append(f"{key}={value}")
    env.write_text("\n".join(out) + "\n")


@app.post("/api/settings/gemini")
def set_gemini_key(body: KeyIn, request: Request, x_finn_secret: str | None = Header(default=None)):
    """Save a Gemini key to backend/.env and test it. Only from this computer / local network
    (or with the refresh secret), so a deployed instance can't be reconfigured by visitors."""
    if not (_local_request(request) or (config.REFRESH_SECRET and x_finn_secret == config.REFRESH_SECRET)):
        raise HTTPException(403, "Set GEMINI_API_KEY in the server's environment instead.")
    key = body.gemini_api_key.strip()
    old = config.GEMINI_API_KEY
    config.GEMINI_API_KEY = key
    from .ai.llm import LlmUnavailable, generate_json

    try:
        res = generate_json("check", "Reply with JSON only.", 'Return {"ok": true}', tier="fast", use_cache=False)
    except LlmUnavailable as e:
        config.GEMINI_API_KEY = old
        raise HTTPException(400, f"Google rejected this key or no model answered: {str(e)[:300]}")
    _write_env("GEMINI_API_KEY", key)
    return {"ok": bool(res), "message": "Connected. FINN will now read filings and build research.",
            "fast_model": config.GEMINI_FAST_MODEL, "smart_model": config.GEMINI_SMART_MODEL}


@app.post("/api/settings/gemini/test")
def test_gemini():
    if not config.llm_enabled():
        raise HTTPException(409, "No Gemini key set yet.")
    from .ai.llm import LlmUnavailable, generate_json

    try:
        generate_json("check", "Reply with JSON only.", 'Return {"ok": true}', tier="fast", use_cache=False)
    except LlmUnavailable as e:
        raise HTTPException(400, f"Gemini didn't answer: {str(e)[:300]}")
    return {"ok": True, "message": "Gemini is working."}


# --- portfolio --------------------------------------------------------------------------------------
@app.get("/api/portfolio")
def portfolio():
    with session_scope() as s:
        holdings = list(s.execute(select(Holding).join(Company)).scalars())
        out, total, prev_total = [], 0.0, 0.0
        series: dict[date, float] = {}
        complete_dates: dict[date, int] = {}
        for h in holdings:
            rows = _prices(s, h.company_id, 520)
            st = alerts_mod.price_stats(rows)
            value = (st.get("close") or 0) * h.quantity
            prev_value = (st.get("prev_close") or st.get("close") or 0) * h.quantity
            total += value
            prev_total += prev_value
            for r in rows:
                series[r.date] = series.get(r.date, 0) + r.close * h.quantity
                complete_dates[r.date] = complete_dates.get(r.date, 0) + 1
            hi = round(max((r.high or r.close for r in rows[-250:]), default=0), 2) or None
            lo = round(min((r.low or r.close for r in rows[-250:]), default=0), 2) or None
            out.append({
                "symbol": h.company.nse_symbol, "name": h.company.name, "sector": h.company.sector,
                "quantity": h.quantity, "close": st.get("close"), "change_pct": st.get("change_pct"),
                "change_abs": st.get("change_abs"), "value": round(value, 2), "volume_mult": st.get("volume_mult"),
                "as_of": st.get("date"), "spark": _spark(rows, 30), "high_52w": hi, "low_52w": lo,
                "source": rows[-1].source if rows else None,
            })
        n = len(holdings)
        # Only plot dates where every holding has a price (avoids fake dips when a ticker is missing).
        hist = [{"date": d.isoformat(), "value": round(v, 2)} for d, v in sorted(series.items()) if complete_dates[d] == n]
        for o in out:
            o["weight"] = round(o["value"] / total * 100, 1) if total else None
        movers = sorted([o for o in out if o["change_pct"] is not None], key=lambda o: abs(o["change_pct"]), reverse=True)
        return {
            "holdings": sorted(out, key=lambda o: -o["value"]),
            "total_value": round(total, 2), "day_change_abs": round(total - prev_total, 2),
            "day_change_pct": round((total / prev_total - 1) * 100, 2) if prev_total else None,
            "history": hist, "movers": [m["symbol"] for m in movers[:6]],
            "as_of": max((o["as_of"] for o in out if o["as_of"]), default=None),
            "demo": True,
        }


class HoldingIn(BaseModel):
    symbol: str
    quantity: float | None = Field(default=None, gt=0)  # number of shares, or…
    amount: float | None = Field(default=None, gt=0)    # …rupees to invest, converted to whole shares at the last close


class QuantityIn(BaseModel):
    quantity: float = Field(gt=0)


def _last_close(s, company_id: int) -> Price | None:
    return s.execute(select(Price).where(Price.company_id == company_id).order_by(Price.date.desc()).limit(1)).scalar_one_or_none()


@app.post("/api/portfolio/holdings")
def add_holding(body: HoldingIn, bg: BackgroundTasks):
    if (body.quantity is None) == (body.amount is None):
        raise HTTPException(422, "Enter either a number of shares or an amount in ₹.")
    try:
        with session_scope() as s:
            c = ingest.get_or_create_company(s, body.symbol)
            if s.execute(select(Holding).where(Holding.company_id == c.id)).scalar_one_or_none():
                raise HTTPException(409, f"{c.nse_symbol} is already in your portfolio. Edit its quantity instead.")
            sym, cid, name = c.nse_symbol, c.id, c.name
    except (LookupError, ValueError) as e:
        raise HTTPException(404, str(e))

    used_price = None
    qty = body.quantity
    if body.amount is not None:
        with session_scope() as s:
            p = _last_close(s, cid)
        if not p and not config.SAMPLE_MODE:
            ingest.refresh_prices([sym], False)  # first time we see this ticker: fetch prices now
            with session_scope() as s:
                p = _last_close(s, cid)
        if not p:
            raise HTTPException(409, f"No price for {sym} yet, so FINN can't convert ₹ to shares. Enter the number of shares instead.")
        qty = float(int(body.amount // p.close))  # whole shares only; the maths is done here, never by a model
        if qty < 1:
            raise HTTPException(422, f"₹{body.amount:,.0f} is less than one share of {sym} (₹{p.close:,.2f} at the {p.date:%d %b} close).")
        used_price = {"close": round(p.close, 2), "date": p.date.isoformat()}

    with session_scope() as s:
        s.add(Holding(company_id=cid, quantity=qty))
    if not config.SAMPLE_MODE:
        bg.add_task(lambda: (ingest.refresh_prices([sym]), ingest.refresh_announcements(days_back=10, symbols=[sym]),
                             ingest.refresh_news([sym]), ingest.enrich_pending(10)))
    return {"ok": True, "symbol": sym, "name": name, "quantity": qty, "price": used_price}


@app.patch("/api/portfolio/holdings/{symbol}")
def update_holding(symbol: str, body: QuantityIn):
    with session_scope() as s:
        h = s.execute(select(Holding).join(Company).where(Company.nse_symbol == symbol.upper())).scalar_one_or_none()
        if not h:
            raise HTTPException(404, "Not in portfolio")
        h.quantity = body.quantity
    return {"ok": True, "symbol": symbol.upper(), "quantity": body.quantity}


@app.delete("/api/portfolio/holdings/{symbol}")
def remove_holding(symbol: str):
    with session_scope() as s:
        c = s.execute(select(Company).where(Company.nse_symbol == symbol.upper())).scalar_one_or_none()
        if not c:
            raise HTTPException(404, "Not in portfolio")
        h = s.execute(select(Holding).where(Holding.company_id == c.id)).scalar_one_or_none()
        if h:
            s.delete(h)
    return {"ok": True}


# --- feed (push) ----------------------------------------------------------------------------------
@app.get("/api/feed")
def feed(hours: int = Query(24, ge=1, le=24 * 90), category: str = "all", symbol: str | None = None,
         sort: str = "priority", start: str | None = None, end: str | None = None):
    now = utcnow()
    since = now - timedelta(hours=hours)
    until = now
    if start:
        since = datetime.fromisoformat(start).replace(tzinfo=IST).astimezone(timezone.utc).replace(tzinfo=None) if len(start) <= 10 else datetime.fromisoformat(start.rstrip("Z"))
    if end:
        until = (datetime.fromisoformat(end).replace(tzinfo=IST) + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None) if len(end) <= 10 else datetime.fromisoformat(end.rstrip("Z"))
    with session_scope() as s:
        held = {r[0] for r in s.execute(select(Holding.company_id))}
        q = (select(Announcement).where(Announcement.filed_at >= since, Announcement.filed_at <= until,
                                        Announcement.company_id.in_(held)).order_by(Announcement.filed_at.desc()))
        if symbol:
            q = q.join(Company).where(Company.nse_symbol == symbol.upper())
        anns = list(s.execute(q).scalars())
        evq = select(AlertEvent).where(AlertEvent.kind.in_(["price", "volume"]), AlertEvent.occurred_at >= since,
                                       AlertEvent.occurred_at <= until, AlertEvent.company_id.in_(held))
        events = list(s.execute(evq).scalars())
        pc: dict = {}
        items = [_ann_item(s, a, pc) for a in anns]
        # Merge price + volume alerts for the same stock/day into one item.
        merged: dict[tuple, AlertEvent] = {}
        for ev in sorted(events, key=lambda e: e.kind):  # 'price' sorts before 'volume'
            key = (ev.company_id, ev.trigger_key)
            if key not in merged:
                merged[key] = ev
        for ev in merged.values():
            if symbol and ev.company.nse_symbol != symbol.upper():
                continue
            items.append(_alert_item(s, ev, pc))
        counts: dict[str, int] = {}
        for it in items:
            if not it["routine"]:
                counts[it["category"]] = counts.get(it["category"], 0) + 1
        if category != "all":
            items = [i for i in items if i["category"] == category or (category == "price" and i["type"] in ("price", "volume"))]
        material = [i for i in items if not i["routine"]]
        routine = [i for i in items if i["routine"]]
        if sort == "time":
            material.sort(key=lambda i: i["time"] or "", reverse=True)
        else:
            material.sort(key=lambda i: (i["importance"], i["time"] or ""), reverse=True)
        routine.sort(key=lambda i: i["time"] or "", reverse=True)
        return {"window": {"since": iso(since), "until": iso(until), "hours": hours}, "items": material,
                "routine": routine, "counts": counts, "total": len(items),
                "high_importance": sum(1 for i in material if i["importance"] >= 70)}


@app.get("/api/news")
def news(hours: int = Query(48, ge=1, le=24 * 30), symbol: str | None = None, limit: int = Query(30, ge=1, le=200)):
    """Headlines grouped by story. Secondary source: shown for awareness, never used in research."""
    since = utcnow() - timedelta(hours=hours)
    with session_scope() as s:
        q = select(NewsItem).where(NewsItem.published_at >= since).order_by(NewsItem.published_at.desc())
        if symbol:
            q = q.join(Company).where(Company.nse_symbol == symbol.upper())
        else:
            held = {r[0] for r in s.execute(select(Holding.company_id))}
            q = q.where(NewsItem.company_id.in_(held))
        rows = list(s.execute(q).scalars())
        stories: dict[int, dict] = {}
        for n in sorted(rows, key=lambda x: x.published_at):  # earliest item leads its story
            sid = n.story_id or n.id
            st = stories.get(sid)
            if st is None:
                stories[sid] = {"id": sid, "title": n.title, "url": n.url, "source": n.source, "time": iso(n.published_at),
                                "latest": iso(n.published_at),
                                "company": {"symbol": n.company.nse_symbol, "name": n.company.name}, "also": []}
            else:
                st["also"].append({"source": n.source, "url": n.url})
                st["latest"] = iso(n.published_at)
        out = sorted(stories.values(), key=lambda x: x["latest"], reverse=True)
        last = s.execute(select(IngestionRun).where(IngestionRun.source == "news").order_by(IngestionRun.started_at.desc()).limit(1)).scalar_one_or_none()
        return {"stories": out[:limit], "total": len(out), "checked": iso(last.finished_at) if last else None,
                "status": last.status if last else None, "sample": config.SAMPLE_MODE}


@app.get("/api/announcements/{ann_id}")
def announcement(ann_id: int):
    with session_scope() as s:
        a = s.get(Announcement, ann_id)
        if not a:
            raise HTTPException(404, "Not found")
        return _ann_item(s, a, {})


@app.post("/api/announcements/{ann_id}/enrich")
def enrich_now(ann_id: int):
    """Run (or re-run) the AI read of one filing on demand."""
    with session_scope() as s:
        a = s.get(Announcement, ann_id)
        if not a:
            raise HTTPException(404, "Not found")
        cares = alerts_mod.get_rules(s)["categories"]
        from .pipeline.enrich import enrich

        a.analysis.enrich_status = "pending"
        enrich(s, a, cares)
        return _ann_item(s, a, {})


@app.get("/api/announcements/{ann_id}/file")
def announcement_file(ann_id: int):
    with session_scope() as s:
        a = s.get(Announcement, ann_id)
        if not a or not a.attachment_url:
            raise HTTPException(404, "No attachment")
        url = a.attachment_url
    try:
        path, _ = pdfs.download(url)
    except SourceError as e:
        raise HTTPException(502, f"Could not fetch the filing from the exchange: {e}")
    return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": "inline"})


@app.get("/api/documents/{doc_id}/file")
def document_file(doc_id: int):
    with session_scope() as s:
        d = s.get(Document, doc_id)
        if not d:
            raise HTTPException(404, "Not found")
        url = d.url
    try:
        path, _ = pdfs.download(url)
    except SourceError as e:
        raise HTTPException(502, f"Could not fetch the document: {e}")
    return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": "inline"})


# --- alerts -----------------------------------------------------------------------------------------
@app.get("/api/alerts")
def list_alerts(days: int = Query(14, ge=1, le=120)):
    since = utcnow() - timedelta(days=days)
    with session_scope() as s:
        held = {r[0] for r in s.execute(select(Holding.company_id))}
        evs = list(s.execute(select(AlertEvent).where(AlertEvent.occurred_at >= since, AlertEvent.company_id.in_(held))
                             .order_by(AlertEvent.occurred_at.desc())).scalars())
        pc: dict = {}
        out = []
        price_days = {(e.company_id, e.trigger_key) for e in evs if e.kind == "price"}
        for ev in evs:
            if ev.kind == "volume" and (ev.company_id, ev.trigger_key) in price_days:
                continue  # the price alert for the same day already mentions the volume
            if ev.kind == "announcement":
                ann = s.get(Announcement, ev.announcement_id) if ev.announcement_id else None
                if not ann:
                    continue
                it = _ann_item(s, ann, pc)
                it.update({"id": f"e{ev.id}", "alert_id": ev.id, "seen": ev.seen, "alert_kind": "announcement"})
            else:
                it = _alert_item(s, ev, pc)
                it["alert_kind"] = ev.kind
            out.append(it)
        return {"items": out, "unseen": sum(1 for i in out if not i.get("seen")), "today": sum(
            1 for i in out if i["time"] and datetime.fromisoformat(i["time"].rstrip("Z")).replace(tzinfo=timezone.utc).astimezone(IST).date() == datetime.now(IST).date())}


@app.post("/api/alerts/seen")
def mark_seen():
    with session_scope() as s:
        for ev in s.execute(select(AlertEvent).where(AlertEvent.seen.is_(False))).scalars():
            ev.seen = True
    return {"ok": True}


class RulesIn(BaseModel):
    price_pct: float = Field(ge=0.5, le=50)
    volume_mult: float = Field(ge=1.1, le=20)
    price_enabled: bool = True
    volume_enabled: bool = True
    categories: list[str]
    overrides: dict[str, dict] = {}


@app.get("/api/alerts/rules")
def get_rules():
    with session_scope() as s:
        r = alerts_mod.get_rules(s)
        ids = {c.id: c.nse_symbol for c in s.execute(select(Company)).scalars()}
        r["overrides"] = {ids[k]: v for k, v in r["overrides"].items() if k in ids}
        r["all_categories"] = [{"key": c, "label": LABELS[c]} for c in CATEGORIES if c != "unclassified"]
        return r


@app.put("/api/alerts/rules")
def put_rules(body: RulesIn, bg: BackgroundTasks):
    cats = [c for c in body.categories if c in CATEGORIES]
    with session_scope() as s:
        alerts_mod.ensure_default_rules(s)
        for r in s.execute(select(AlertRule).where(AlertRule.company_id.is_(None))).scalars():
            if r.kind == "price_pct":
                r.threshold, r.enabled = body.price_pct, body.price_enabled
            elif r.kind == "volume_mult":
                r.threshold, r.enabled = body.volume_mult, body.volume_enabled
            elif r.kind == "category":
                r.categories = cats
        for r in s.execute(select(AlertRule).where(AlertRule.company_id.is_not(None))).scalars():
            s.delete(r)
        for sym, ov in (body.overrides or {}).items():
            c = s.execute(select(Company).where(Company.nse_symbol == sym.upper())).scalar_one_or_none()
            if not c:
                continue
            for kind in ("price_pct", "volume_mult"):
                if ov.get(kind) is not None:
                    s.add(AlertRule(company_id=c.id, kind=kind, threshold=float(ov[kind])))
        s.flush()
        # Re-score announcements so "categories you track" takes effect immediately.
        for a in s.execute(select(AnnouncementAnalysis)).scalars():
            facts = {}
            st = a.structured or {}
            if st.get("kind") == "results":
                pat = next((r for r in st.get("rows", []) if r["metric"] == "pat"), None)
                if pat and pat["yoy"]["pct"] is not None:
                    facts["pat_yoy_pct"] = pat["yoy"]["pct"]
            a.importance, a.importance_reasons = score(a.category, a.subtype, cats, facts)
        # Re-evaluate recent price alerts with the new thresholds (events already fired are kept).
        rules = alerts_mod.get_rules(s)
        for h in s.execute(select(Holding)).scalars():
            alerts_mod.evaluate_prices(s, h.company, rules, lookback_days=10)
    return get_rules()


# --- companies & research -----------------------------------------------------------------------------
@app.get("/api/companies/search")
def search(q: str = ""):
    res = universe.search(q)
    with session_scope() as s:
        held = {c.nse_symbol for c in s.execute(select(Company).join(Holding)).scalars()}
        built = {c.nse_symbol for c in s.execute(select(Company).join(ResearchReport)).scalars()}
    for r in res:
        r["in_portfolio"] = r["symbol"] in held
        r["has_dossier"] = r["symbol"] in built
    return {"results": res}


@app.get("/api/research")
def research_index():
    with session_scope() as s:
        reps = list(s.execute(select(ResearchReport, Company).join(Company).order_by(ResearchReport.created_at.desc())))
        jobs = list(s.execute(select(Job, Company).join(Company).where(Job.status.in_(["queued", "running"]))))
        return {
            "dossiers": [{"symbol": c.nse_symbol, "name": c.name, "sector": c.sector, "logo": _logo(c),
                          "generated_at": iso(r.created_at),
                          "latest_quarter": (r.content or {}).get("latest_quarter")} for r, c in reps],
            "building": [{"symbol": c.nse_symbol, "job_id": j.id, "step": j.step, "progress": j.progress} for j, c in jobs],
            "suggested": universe.RESEARCH_PICKS,
        }


@app.get("/api/companies/{symbol}")
def company(symbol: str, bg: BackgroundTasks):
    sym = symbol.upper()
    with session_scope() as s:
        c = s.execute(select(Company).where(Company.nse_symbol == sym)).scalar_one_or_none()
        if not c:
            # Any valid NSE ticker gets a company row, so its prices and key stats can be fetched.
            try:
                c = ingest.get_or_create_company(s, sym)
            except (LookupError, ValueError) as e:
                raise HTTPException(404, str(e))
        rows = _prices(s, c.id, 520)
        st = alerts_mod.price_stats(rows)
        last250 = rows[-250:]
        stats = {
            **st, "market_cap_cr": c.market_cap_cr, "pe": c.pe, "dividend_yield": c.dividend_yield,
            "high_52w": round(max((r.high or r.close for r in last250), default=0), 2) or None,
            "low_52w": round(min((r.low or r.close for r in last250), default=0), 2) or None,
            "source": rows[-1].source if rows else None,
        }
        held = s.execute(select(Holding).where(Holding.company_id == c.id)).scalar_one_or_none()
        rep = s.execute(select(ResearchReport).where(ResearchReport.company_id == c.id)).scalar_one_or_none()
        job = s.execute(select(Job).where(Job.company_id == c.id, Job.kind == "research").order_by(Job.created_at.desc()).limit(1)).scalar_one_or_none()
        anns = list(s.execute(select(Announcement).where(Announcement.company_id == c.id).order_by(Announcement.filed_at.desc()).limit(40)).scalars())
        pc: dict = {}
        out = {
            "symbol": c.nse_symbol, "name": c.name, "sector": c.sector, "is_financial": c.is_financial, "known": True,
            "bse_code": c.bse_code, "logo": _logo(c), "logo_pending": c.website is None,
            "prices": [{"date": r.date.isoformat(), "close": round(r.close, 2), "volume": r.volume} for r in rows],
            "stats": stats, "in_portfolio": bool(held), "quantity": held.quantity if held else None,
            "dossier": {"generated_at": iso(rep.created_at), "latest_quarter": rep.content.get("latest_quarter")} if rep else None,
            "job": _job_dict(job) if job else None,
            "announcements": [_ann_item(s, a, pc) for a in anns],
            "sample": c.source == "sample",
        }
        need_stats = c.website is None
    if not rows and not config.SAMPLE_MODE:
        bg.add_task(ingest.refresh_prices, [sym], True)
    elif need_stats and not config.SAMPLE_MODE:  # companies saved before logos existed
        bg.add_task(ingest.refresh_stats, [sym])
    return out


def _job_dict(j: Job) -> dict:
    return {"id": j.id, "status": j.status, "step": j.step, "progress": j.progress, "log": (j.log or [])[-12:],
            "error": (j.error or "").split("\n")[0] if j.error else None, "updated_at": iso(j.updated_at)}


@app.post("/api/research/{symbol}")
def start_research(symbol: str, force: bool = False):
    if config.SAMPLE_MODE:
        raise HTTPException(409, "Research builds are disabled in sample mode.")
    try:
        job_id = research.start(symbol, force=force)
    except (LookupError, ValueError) as e:
        raise HTTPException(404, str(e))
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job(job_id: int):
    with session_scope() as s:
        j = s.get(Job, job_id)
        if not j:
            raise HTTPException(404, "Not found")
        return _job_dict(j)


@app.get("/api/research/{symbol}")
def get_research(symbol: str):
    with session_scope() as s:
        c = s.execute(select(Company).where(Company.nse_symbol == symbol.upper())).scalar_one_or_none()
        if not c:
            return {"status": "none"}
        rep = s.execute(select(ResearchReport).where(ResearchReport.company_id == c.id)).scalar_one_or_none()
        job = s.execute(select(Job).where(Job.company_id == c.id, Job.kind == "research").order_by(Job.created_at.desc()).limit(1)).scalar_one_or_none()
        building = job and job.status in ("queued", "running")
        return {"status": "building" if building else ("ready" if rep else "none"),
                "content": rep.content if rep else None, "job": _job_dict(job) if job else None}


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)  # short ones like "hi" get a hint, not an error


@app.post("/api/research/{symbol}/ask")
def ask(symbol: str, body: AskIn):
    if not config.llm_enabled() and not config.GROQ_API_KEY:
        raise HTTPException(409, "AI answers need a GEMINI_API_KEY in backend/.env")
    from .ai.llm import LlmUnavailable

    with session_scope() as s:
        c = s.execute(select(Company).where(Company.nse_symbol == symbol.upper())).scalar_one_or_none()
        if not c:
            raise HTTPException(404, "Build the dossier for this company first.")
        try:
            return ask_mod.ask(s, c, body.question)
        except LlmUnavailable as e:
            raise HTTPException(503, f"AI unavailable: {e}")
