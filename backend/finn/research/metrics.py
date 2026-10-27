"""Code-computed research sections built from extracted financial_metrics rows.

Nothing here calls an LLM. Every value carries {doc_id, page} so the UI can link to evidence.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select

from ..db import Document, FinancialMetric
from ..pipeline import financials as fin


def load(s, company_id: int) -> dict:
    rows = list(s.execute(select(FinancialMetric).where(FinancialMetric.company_id == company_id)).scalars())
    if not rows:
        return {"basis": None, "Q": {}, "H": {}, "FY": {}, "BS": {}}
    counts = defaultdict(int)
    for r in rows:
        if r.period_type == "Q":
            counts[r.basis] += 1
    basis = max(counts, key=counts.get) if counts else rows[0].basis
    out: dict = {"basis": basis, "Q": defaultdict(dict), "H": defaultdict(dict), "FY": defaultdict(dict), "BS": defaultdict(dict)}
    for r in rows:
        if r.basis != basis or r.value_cr is None:
            continue
        out[r.period_type][r.period_end][r.metric] = {"v": r.value_cr, "doc": r.document_id, "page": r.page, "method": r.method}
    return out


def _v(cell):
    return cell["v"] if cell else None


def _src(cell):
    return {"doc_id": cell["doc"], "page": cell["page"]} if cell else None


def quarter_series(m: dict, n: int = 8) -> list[dict]:
    qs = sorted(m["Q"].keys())[-n:]
    out = []
    for d in qs:
        row = m["Q"][d]
        rev, ebitda, pat = _v(row.get("revenue")), _v(row.get("ebitda")), _v(row.get("pat"))
        ya = m["Q"].get(_shift(d, -365), {})
        out.append({
            "label": fin.quarter_label(d), "period_end": d.isoformat(),
            "revenue": rev, "ebitda": ebitda, "pbt": _v(row.get("pbt")), "pat": pat,
            "ebitda_margin": round(ebitda / rev * 100, 1) if ebitda is not None and rev else None,
            "pat_margin": round(pat / rev * 100, 1) if pat is not None and rev else None,
            "revenue_yoy": fin.growth(rev, _v(ya.get("revenue")))["pct"],
            "pat_yoy": fin.growth(pat, _v(ya.get("pat")))["pct"],
            "source": _src(row.get("revenue")),
        })
    return out


def year_series(m: dict) -> list[dict]:
    out = []
    for d in sorted(m["FY"].keys()):
        row = m["FY"][d]
        if d.month != 3:
            continue
        rev, ebitda, pat = _v(row.get("revenue")), _v(row.get("ebitda")), _v(row.get("pat"))
        if rev is None and pat is None:
            continue  # e.g. only a cash-flow figure for that year
        out.append({"label": fin.fy_label(d), "period_end": d.isoformat(), "revenue": rev, "ebitda": ebitda,
                    "pbt": _v(row.get("pbt")), "pat": pat,
                    "ebitda_margin": round(ebitda / rev * 100, 1) if ebitda is not None and rev else None,
                    "source": _src(row.get("revenue"))})
    return out


def _shift(d: date, days: int) -> date:
    """Find the quarter-end date nearest to d+days (quarter ends vary: 30th/31st)."""
    t = d + timedelta(days=days)
    for cand in (t, t + timedelta(days=1), t - timedelta(days=1), t + timedelta(days=2), t - timedelta(days=2)):
        if cand.month in (3, 6, 9, 12) and cand.day >= 28:
            return date(cand.year, cand.month, {3: 31, 6: 30, 9: 30, 12: 31}[cand.month])
    return t


def ttm(m: dict) -> dict | None:
    qs = sorted(m["Q"].keys())
    if len(qs) < 4:
        return None
    last4 = qs[-4:]
    if (last4[-1] - last4[0]).days > 290:  # must be four consecutive quarters
        return None
    tot = {}
    for k in ("revenue", "ebitda", "pat"):
        vals = [_v(m["Q"][d].get(k)) for d in last4]
        tot[k] = round(sum(vals), 2) if all(v is not None for v in vals) else None
    tot["label"] = f"TTM to {fin.quarter_label(last4[-1])}"
    return tot


def snapshot(m: dict, is_financial: bool) -> dict | None:
    qs = quarter_series(m, 8)
    if not qs:
        return None
    cur = qs[-1]
    prev = qs[-2] if len(qs) > 1 else None
    t = ttm(m)
    return {
        "quarter": cur["label"], "period_end": cur["period_end"], "basis": m["basis"],
        "revenue": cur["revenue"], "revenue_yoy": cur["revenue_yoy"], "ebitda": cur["ebitda"], "pat": cur["pat"],
        "pat_yoy": cur["pat_yoy"], "ebitda_margin": cur["ebitda_margin"], "pat_margin": cur["pat_margin"],
        "ebitda_margin_change_bps": (round((cur["ebitda_margin"] - prev["ebitda_margin"]) * 100)
                                     if prev and cur["ebitda_margin"] is not None and prev["ebitda_margin"] is not None else None),
        "ttm": t, "revenue_label": "Interest earned" if is_financial else "Revenue",
        "ebitda_label": "Operating profit" if is_financial else "EBITDA",
        "source": cur["source"],
    }


def trajectory_observations(qs: list[dict]) -> list[dict]:
    """Deterministic, computed observations (labelled 'Computed' in the UI)."""
    obs = []
    with_yoy = [q for q in qs if q["revenue_yoy"] is not None]
    if with_yoy:
        last = with_yoy[-1]
        trail = ", ".join(f"{q['label']} {q['revenue_yoy']:+.1f}%" for q in with_yoy[-4:])
        trend = ""
        if len(with_yoy) >= 3:
            a, b = with_yoy[-3]["revenue_yoy"], last["revenue_yoy"]
            trend = " — accelerating" if b > a + 2 else " — decelerating" if b < a - 2 else " — broadly steady"
        obs.append({"text": f"Revenue growth YoY: {trail}{trend}.", "kind": "computed"})
    mq = [q for q in qs if q["ebitda_margin"] is not None]
    if len(mq) >= 5:
        cur, ya = mq[-1], None
        for q in mq:
            if q["period_end"][:4] == str(int(cur["period_end"][:4]) - 1) and q["period_end"][5:7] == cur["period_end"][5:7]:
                ya = q
        if ya:
            bps = round((cur["ebitda_margin"] - ya["ebitda_margin"]) * 100)
            verb = "expanded" if bps > 0 else "compressed" if bps < 0 else "was flat"
            obs.append({"text": f"EBITDA margin {verb} {abs(bps)} bps YoY to {cur['ebitda_margin']:.1f}% in {cur['label']}.",
                        "kind": "computed"})
    pq = [q for q in qs if q["pat_yoy"] is not None]
    if pq:
        p = pq[-1]
        obs.append({"text": f"PAT {p['pat_yoy']:+.1f}% YoY in {p['label']}.", "kind": "computed"})
    return obs


def balance_sheet(m: dict, is_financial: bool) -> dict | None:
    if not m["BS"]:
        return None
    dates = sorted(m["BS"].keys())
    def build(d):
        r = m["BS"][d]
        debt_parts = [_v(r.get("borrowings_non_current")), _v(r.get("borrowings_current"))]
        debt = sum(x for x in debt_parts if x is not None) if any(x is not None for x in debt_parts) else None
        cash_parts = [_v(r.get("cash_and_equivalents")), _v(r.get("other_bank_balances")), _v(r.get("current_investments"))]
        cash = sum(x for x in cash_parts if x is not None) if any(x is not None for x in cash_parts) else None
        eq = _v(r.get("total_equity"))
        return {"as_of": d.isoformat(), "total_debt": debt, "cash_and_investments": cash,
                "net_debt": round(debt - cash, 2) if debt is not None and cash is not None else None,
                "equity": eq, "de_ratio": round(debt / eq, 2) if debt is not None and eq else None,
                "receivables": _v(r.get("trade_receivables")), "inventories": _v(r.get("inventories")),
                "payables": _v(r.get("trade_payables")), "total_assets": _v(r.get("total_assets")),
                "source": _src(r.get("total_equity") or r.get("total_assets"))}
    cur = build(dates[-1])
    prior = build(dates[-2]) if len(dates) > 1 else None
    t = ttm(m)
    rev = t["revenue"] if t else None
    if not is_financial and rev:
        for k, name in (("receivables", "receivable_days"), ("inventories", "inventory_days"), ("payables", "payable_days")):
            cur[name] = round(cur[k] / rev * 365) if cur.get(k) is not None else None
        if None not in (cur.get("receivable_days"), cur.get("inventory_days"), cur.get("payable_days")):
            cur["cash_cycle_days"] = cur["receivable_days"] + cur["inventory_days"] - cur["payable_days"]
        cur["days_basis"] = f"on {t['label']} revenue (inventory & payable days approximated on revenue, not COGS)"
    if is_financial:
        cur["note"] = ("For lenders, borrowings are raw material: D/E and working-capital days are not meaningful. "
                       "Asset quality (GNPA/NNPA), NIM and CASA are not extracted in this prototype.")
    return {"current": cur, "prior": prior}


def cash_quality(m: dict) -> dict | None:
    rows = []
    for ptype in ("FY", "H"):
        for d in sorted(m[ptype].keys()):
            r = m[ptype][d]
            cfo, capex = _v(r.get("cfo")), _v(r.get("capex"))
            if cfo is None:
                continue
            pat = _v(r.get("pat"))
            if pat is None and ptype == "H":  # sum the two quarters
                q2 = [m["Q"].get(d, {}).get("pat"), m["Q"].get(_shift(d, -91), {}).get("pat")]
                pat = sum(_v(x) for x in q2) if all(q2) else None
            rows.append({
                "label": (fin.fy_label(d) if ptype == "FY" else f"H1 {fin.fy_label(d)}" if d.month == 9 else f"H {d:%b %Y}"),
                "period_end": d.isoformat(), "months": 12 if ptype == "FY" else 6,
                "cfo": cfo, "pat": pat, "capex": capex,
                "fcf": round(cfo - capex, 2) if capex is not None else None,
                "conversion": round(cfo / pat, 2) if pat else None, "source": _src(r.get("cfo")),
            })
    if not rows:
        return None
    rows.sort(key=lambda r: r["period_end"])
    latest = rows[-1]
    verdict = None
    if latest["conversion"] is not None:
        c = latest["conversion"]
        verdict = ("Profits are converting to cash well" if c >= 0.9 else
                   "Cash conversion is moderate" if c >= 0.6 else "Profits are not turning into cash — check working capital")
    return {"periods": rows, "verdict": verdict}


def facts_table(m: dict, is_financial: bool, limit: int = 40) -> list[dict]:
    """Compact, citeable facts for LLM prompts: F-ids with value, period and source page."""
    facts = []
    label_rev = "Interest earned" if is_financial else "Revenue"
    for q in quarter_series(m, 8):
        src = q["source"] or {}
        for key, label in (("revenue", label_rev), ("ebitda", "Operating profit" if is_financial else "EBITDA"),
                           ("pat", "PAT")):
            if q[key] is not None:
                facts.append({"text": f"{label} {q['label']} = ₹{q[key]:,.1f} cr", **src})
        if q["ebitda_margin"] is not None:
            facts.append({"text": f"EBITDA margin {q['label']} = {q['ebitda_margin']:.1f}% (computed)", **src})
        if q["revenue_yoy"] is not None:
            facts.append({"text": f"{label_rev} growth YoY {q['label']} = {q['revenue_yoy']:+.1f}% (computed)", **src})
        if q["pat_yoy"] is not None:
            facts.append({"text": f"PAT growth YoY {q['label']} = {q['pat_yoy']:+.1f}% (computed)", **src})
    for y in year_series(m):
        src = y["source"] or {}
        if y["revenue"] is not None:
            facts.append({"text": f"{label_rev} {y['label']} = ₹{y['revenue']:,.1f} cr", **src})
        if y["pat"] is not None:
            facts.append({"text": f"PAT {y['label']} = ₹{y['pat']:,.1f} cr", **src})
    bs = balance_sheet(m, is_financial)
    if bs:
        c = bs["current"]
        src = c.get("source") or {}
        for k, label in (("total_debt", "Total borrowings"), ("cash_and_investments", "Cash & liquid investments"),
                         ("net_debt", "Net debt"), ("equity", "Total equity")):
            if c.get(k) is not None:
                facts.append({"text": f"{label} as of {c['as_of']} = ₹{c[k]:,.1f} cr", **src})
        if c.get("de_ratio") is not None:
            facts.append({"text": f"Debt/Equity as of {c['as_of']} = {c['de_ratio']:.2f} (computed)", **src})
    cq = cash_quality(m)
    if cq:
        for p in cq["periods"][-2:]:
            src = p.get("source") or {}
            facts.append({"text": f"Cash from operations {p['label']} = ₹{p['cfo']:,.1f} cr", **src})
            if p["conversion"] is not None:
                facts.append({"text": f"CFO/PAT {p['label']} = {p['conversion']:.2f}x (computed)", **src})
    facts = facts[-limit:]
    for i, f in enumerate(facts, 1):
        f["id"] = f"F{i}"
    return facts


def doc_titles(s, ids: set[int]) -> dict[int, dict]:
    if not ids:
        return {}
    return {d.id: {"title": d.title, "type": d.doc_type, "period": d.period_label}
            for d in s.execute(select(Document).where(Document.id.in_(ids))).scalars()}
