"""Configurable alerts. The investor decides what "unusual" means; FINN watches for it.

Price move  : |close_t / close_{t-1} - 1| >= threshold %
Volume spike: volume_t / mean(volume_{t-20..t-1}) >= multiple   (today excluded from its own baseline)
Announcement: a filing in a category the investor cares about, above the routine threshold
Each (kind, company, date-or-filing) fires at most once (unique constraint).
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from ..db import AlertEvent, AlertRule, Announcement, Price
from .classify import LABELS
from .score import DEFAULT_CARE, ROUTINE_THRESHOLD

IST = timezone(timedelta(hours=5, minutes=30))
DEFAULTS = {"price_pct": 4.0, "volume_mult": 2.0}
VOLUME_WINDOW = 20


def ensure_default_rules(s) -> None:
    have = {(r.kind, r.company_id) for r in s.execute(select(AlertRule)).scalars()}
    if ("price_pct", None) not in have:
        s.add(AlertRule(kind="price_pct", threshold=DEFAULTS["price_pct"]))
    if ("volume_mult", None) not in have:
        s.add(AlertRule(kind="volume_mult", threshold=DEFAULTS["volume_mult"]))
    if ("category", None) not in have:
        s.add(AlertRule(kind="category", categories=list(DEFAULT_CARE)))
    s.flush()


def get_rules(s) -> dict:
    ensure_default_rules(s)
    out = {"price_pct": DEFAULTS["price_pct"], "volume_mult": DEFAULTS["volume_mult"], "categories": list(DEFAULT_CARE),
           "price_enabled": True, "volume_enabled": True, "overrides": {}}
    for r in s.execute(select(AlertRule)).scalars():
        if r.company_id is None:
            if r.kind == "price_pct":
                out["price_pct"], out["price_enabled"] = r.threshold, r.enabled
            elif r.kind == "volume_mult":
                out["volume_mult"], out["volume_enabled"] = r.threshold, r.enabled
            elif r.kind == "category":
                out["categories"] = r.categories or []
        else:
            out["overrides"].setdefault(r.company_id, {})[r.kind] = r.threshold
    return out


def price_stats(rows: list[Price]) -> dict:
    """rows sorted ascending by date. Returns latest close, day change % and volume multiple."""
    if not rows:
        return {}
    last = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else None
    out = {"date": last.date.isoformat(), "close": last.close, "volume": last.volume, "change_pct": None,
           "change_abs": None, "volume_mult": None, "avg_volume": None, "prev_close": prev.close if prev else None}
    if prev and prev.close:
        out["change_abs"] = round(last.close - prev.close, 2)
        out["change_pct"] = round((last.close / prev.close - 1) * 100, 2)
    base = [r.volume for r in rows[-1 - VOLUME_WINDOW:-1] if r.volume]
    if len(base) >= 10 and last.volume:
        avg = sum(base) / len(base)
        out["avg_volume"] = avg
        out["volume_mult"] = round(last.volume / avg, 2) if avg else None
    return out


def _add_event(s, **kw) -> bool:
    exists = s.execute(select(AlertEvent.id).where(
        AlertEvent.kind == kw["kind"], AlertEvent.company_id == kw["company_id"],
        AlertEvent.trigger_key == kw["trigger_key"])).first()
    if exists:
        return False
    s.add(AlertEvent(**kw))
    s.flush()
    return True


def _session_close_utc(d) -> datetime:
    return datetime.combine(d, time(15, 30), IST).astimezone(timezone.utc).replace(tzinfo=None)


def evaluate_prices(s, company, rules: dict, lookback_days: int = 7) -> int:
    rows = list(s.execute(select(Price).where(Price.company_id == company.id).order_by(Price.date.desc()).limit(
        VOLUME_WINDOW + lookback_days + 1)).scalars())[::-1]
    if len(rows) < 2:
        return 0
    ov = rules["overrides"].get(company.id, {})
    p_th = ov.get("price_pct", rules["price_pct"])
    v_th = ov.get("volume_mult", rules["volume_mult"])
    n = 0
    start = max(1, len(rows) - lookback_days)
    for i in range(start, len(rows)):
        st = price_stats(rows[: i + 1])
        d = rows[i].date
        if rules["price_enabled"] and st.get("change_pct") is not None and abs(st["change_pct"]) >= p_th:
            direction = "up" if st["change_pct"] > 0 else "down"
            vol = f" on {st['volume_mult']:.1f}× average volume" if st.get("volume_mult") and st["volume_mult"] >= 1.5 else ""
            n += _add_event(s, kind="price", company_id=company.id, trigger_key=d.isoformat(),
                            occurred_at=_session_close_utc(d),
                            title=f"{company.nse_symbol} {direction} {abs(st['change_pct']):.1f}%{vol}",
                            observed={**st, "threshold": p_th})
        if rules["volume_enabled"] and st.get("volume_mult") is not None and st["volume_mult"] >= v_th:
            n += _add_event(s, kind="volume", company_id=company.id, trigger_key=d.isoformat(),
                            occurred_at=_session_close_utc(d),
                            title=f"{company.nse_symbol} traded {st['volume_mult']:.1f}× its {VOLUME_WINDOW}-day average volume",
                            observed={**st, "threshold": v_th})
    return n


def evaluate_announcement(s, ann: Announcement, rules: dict) -> bool:
    a = ann.analysis
    if not a or a.category not in rules["categories"] or a.importance < ROUTINE_THRESHOLD:
        return False
    if a.category == "results" and a.subtype in ("results_ad", "results_intimation"):
        return False
    return _add_event(s, kind="announcement", company_id=ann.company_id, trigger_key=str(ann.id),
                      occurred_at=ann.filed_at, announcement_id=ann.id,
                      title=f"{LABELS.get(a.category, a.category)}: {ann.subject[:140]}", observed={"category": a.category})
