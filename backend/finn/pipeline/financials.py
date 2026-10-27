"""Deterministic financial maths. The LLM only reads numbers off the page; code does the rest.

Conventions
  * All money is normalised to ₹ crore.
  * Signs: expenses are positive numbers; losses are negative profits; exceptional items are
    signed as they affect profit (gain +, loss -).
  * EBITDA (non-financial companies) = PBT before exceptional items + finance costs
    + depreciation & amortisation - other income.  Shown in the UI with this definition.
  * Financial companies (banks/NBFCs) get a different template: EBITDA is not meaningful, so we
    show "Operating profit" (pre-provision) where the filing reports it.
"""
from __future__ import annotations

from datetime import date, timedelta

UNIT_TO_CR = {
    "crore": 1.0, "crores": 1.0, "cr": 1.0,
    "lakh": 0.01, "lakhs": 0.01, "lacs": 0.01, "lac": 0.01,
    "million": 0.1, "millions": 0.1, "mn": 0.1,
    "billion": 100.0, "bn": 100.0,
    "thousand": 0.0001, "thousands": 0.0001,
    "rupees": 1e-7, "inr": 1e-7, "rs": 1e-7,
}

FIELDS = [
    "revenue_from_operations", "other_income", "total_income", "total_expenses", "finance_costs",
    "depreciation", "exceptional_items", "pbt", "tax_expense", "pat", "pat_owners",
    "interest_earned", "interest_expended", "operating_profit", "provisions",
]


def unit_factor(unit: str | None) -> float | None:
    if not unit:
        return None
    u = unit.strip().lower().replace("₹", "").replace("in ", "").strip(" .()")
    for k, v in UNIT_TO_CR.items():
        if u == k or u.startswith(k):
            return v
    return None


def to_cr(value, factor: float | None):
    if value is None or factor is None:
        return None
    try:
        return round(float(value) * factor, 2)
    except (TypeError, ValueError):
        return None


def growth(cur: float | None, prev: float | None) -> dict:
    """Percentage change that behaves sensibly around zero and negative bases."""
    if cur is None or prev is None:
        return {"pct": None, "label": "n/a"}
    if prev == 0:
        return {"pct": None, "label": "n/m"}
    if prev < 0 and cur >= 0:
        return {"pct": None, "label": "turned positive"}
    if prev > 0 and cur < 0:
        return {"pct": None, "label": "turned negative"}
    if prev < 0 and cur < 0:
        return {"pct": None, "label": "loss narrowed" if cur > prev else "loss widened"}
    pct = (cur - prev) / abs(prev) * 100
    return {"pct": round(pct, 1), "label": f"{pct:+.1f}%"}


def headline(p: dict, is_financial: bool) -> dict:
    """Compute headline metrics for one period column (values already in ₹ crore)."""
    g = lambda k: p.get(k)  # noqa: E731
    revenue = g("interest_earned") if is_financial and g("interest_earned") is not None else g("revenue_from_operations")
    if revenue is None and is_financial:
        revenue = g("total_income")
    pbt, pat = g("pbt"), g("pat_owners") if g("pat_owners") is not None else g("pat")
    ebitda = None
    ebitda_method = None
    if is_financial:
        if g("operating_profit") is not None:
            ebitda, ebitda_method = g("operating_profit"), "reported operating profit (pre-provision)"
    elif pbt is not None and g("finance_costs") is not None and g("depreciation") is not None:
        exc = g("exceptional_items") or 0.0
        ebitda = pbt - exc + g("finance_costs") + g("depreciation") - (g("other_income") or 0.0)
        ebitda_method = "PBT before exceptional items + finance costs + D&A − other income"
    out = {
        "revenue": revenue, "ebitda": None if ebitda is None else round(ebitda, 2), "pbt": pbt, "pat": pat,
        "ebitda_method": ebitda_method,
    }
    out["ebitda_margin"] = round(out["ebitda"] / revenue * 100, 1) if out["ebitda"] is not None and revenue else None
    out["pat_margin"] = round(pat / revenue * 100, 1) if pat is not None and revenue else None
    return out


def reconcile(p: dict) -> str | None:
    """Catch a misread revenue figure using the statement's own arithmetic (done here, never by the model).

    revenue + other income must equal total income. If it doesn't, but total income is confirmed by
    total income − total expenses = PBT, revenue is recomputed as total income − other income.
    Otherwise revenue is dropped (shown as n/a) rather than shown wrong. Returns a note, or None."""
    rev, oi, ti = p.get("revenue_from_operations"), p.get("other_income"), p.get("total_income")
    if None in (rev, oi, ti) or p.get("interest_earned") is not None:
        return None
    tol = max(2.0, 0.005 * abs(ti))
    if abs(rev + oi - ti) <= tol:
        return None
    te, pbt, exc = p.get("total_expenses"), p.get("pbt"), p.get("exceptional_items") or 0.0
    when = p.get("period_end") or "one period"
    if te is not None and pbt is not None and min(abs(ti - te - pbt), abs(ti - te + exc - pbt)) <= tol:
        p["revenue_from_operations"] = round(ti - oi, 2)
        return (f"revenue for {when} recomputed as total income − other income ({ti - oi:,.0f}); "
                f"the figure read from the filing ({rev:,.0f}) didn't add up")
    p["revenue_from_operations"] = None
    return f"revenue for {when} didn't add up with other income and total income, so it isn't shown"


def checks(p: dict) -> list[str]:
    """Sanity checks on extracted numbers. Any failure shows a 'verify' badge in the UI."""
    issues = []
    pbt, tax, pat = p.get("pbt"), p.get("tax_expense"), p.get("pat")
    if None not in (pbt, tax, pat):
        if abs((pbt - tax) - pat) > max(1.0, 0.03 * abs(pat)):
            # Share of associates / JVs can legitimately sit below tax; flag only large gaps.
            issues.append(f"PBT − tax ({pbt - tax:,.0f}) ≠ PAT ({pat:,.0f})")
    rev = p.get("revenue_from_operations")
    if rev is not None and rev <= 0:
        issues.append("revenue is not positive")
    ti = p.get("total_income")
    if rev is not None and ti is not None and ti + 1 < rev:
        issues.append("total income below revenue")
    return issues


def _parse_date(s) -> date | None:
    if isinstance(s, date):
        return s
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _near(a: date, b: date, days: int = 20) -> bool:
    return abs((a - b).days) <= days


def pick_columns(periods: list[dict]) -> dict:
    """From extracted period columns, choose current quarter, previous quarter, year-ago quarter.

    Selection is by DATES, not by the model's labels, so QoQ/YoY can't be mixed up."""
    qs = []
    for p in periods:
        d = _parse_date(p.get("period_end"))
        months = p.get("months")
        if d and (months == 3 or (months is None and p.get("type") == "quarter")):
            qs.append((d, p))
    if not qs:
        return {}
    qs.sort(key=lambda x: x[0], reverse=True)
    cur_d, cur = qs[0]
    prev = next((p for d, p in qs if _near(d, cur_d - timedelta(days=91))), None)
    yoy = next((p for d, p in qs if _near(d, cur_d - timedelta(days=365))), None)
    return {"current": cur, "previous": prev, "year_ago": yoy, "current_end": cur_d}


def fy_label(d: date) -> str:
    """Indian fiscal year label for a date: FY ends 31 March. 2026-09-30 -> FY27."""
    fy = d.year + 1 if d.month > 3 else d.year
    return f"FY{fy % 100:02d}"


def quarter_label(d: date) -> str:
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(d.month)
    return f"Q{q} {fy_label(d)}" if q else f"{d:%b %Y}"
