"""Guidance vs. delivered.

1. A cheap model extracts explicit forward-looking guidance from each concall transcript, with a
   verbatim quote and page. We verify the quote really appears on that page.
2. For quantitative guidance (revenue growth, margins, PAT growth, capex) CODE compares the target
   with actuals from the results filings and decides the verdict.
3. Only qualitative promises go to the model for an assessment, which must cite evidence and is
   labelled as FINN's interpretation.
"""
from __future__ import annotations

import re
from datetime import date

from ..ai.llm import generate_json
from ..ai.prompts import GROUNDING, paged
from ..pipeline import financials as fin
from .index import tokens

GUIDANCE_PROMPT = """This is an earnings-call transcript of {company}, split into pages.
Extract EXPLICIT forward-looking guidance given by management on headline numbers: revenue / sales
growth, volume growth, EBITDA or operating margin, PAT / profit growth, capex amount, or another
concrete target (e.g. order inflow, store additions, capacity). Ignore vague optimism without a target
or direction, and ignore analysts' questions.

Return JSON:
{{
  "call_quarter": "<the quarter whose results this call discusses, e.g. Q1 FY27, or null>",
  "items": [ {{
      "quote": "<verbatim words from the transcript, max 45 words>",
      "page": <int>,
      "metric": "revenue_growth"|"volume_growth"|"ebitda_margin"|"pat_growth"|"capex"|"other",
      "target_low": <number|null>, "target_high": <number|null>,   // e.g. 15-17% -> 15 and 17; "at least 20%" -> 20, null
      "unit": "pct"|"cr"|null,                                    // capex in ₹ crore -> "cr"
      "target_period": "<FY27 | Q3 FY27 | H2 FY27 | medium term | null>",
      "topic": "<3-6 word description, e.g. 'FY27 revenue growth'>"
  }} ]
}}
At most 8 items, the most material first. Use only what is in the transcript.

TRANSCRIPT:
{text}"""

ASSESS_PROMPT = """You are checking whether management delivered on qualitative promises. Use ONLY the
sources below (S = transcript or filing excerpts, F = numbers computed from results filings).
For each promise, decide: "delivered", "not_delivered", "in_progress" or "unclear" (unclear when the
sources don't say). Explain in <= 30 words and cite the sources you used.

Return JSON: {{"items": [{{"id": <id>, "verdict": "...", "text": "...", "cites": ["S1","F3"]}}]}}

PROMISES:
{promises}

SOURCES:
{sources}"""


def _norm(t: str) -> list[str]:
    return tokens(t)


def quote_on_page(quote: str, page_text: str) -> bool:
    q = _norm(quote)
    if not q:
        return False
    p = set(_norm(page_text))
    return sum(1 for t in q if t in p) / len(q) >= 0.85


def extract(company_name: str, texts: list[str]) -> dict:
    out = generate_json("guidance_extract", GROUNDING,
                        GUIDANCE_PROMPT.format(company=company_name, text=paged(texts, 60000)),
                        tier="fast", version="guidance-v1")
    items = []
    for it in out.get("items") or []:
        if not it.get("quote"):
            continue
        pg = it.get("page")
        ok = isinstance(pg, int) and 1 <= pg <= len(texts) and quote_on_page(it["quote"], texts[pg - 1])
        if not ok:  # search the whole transcript before giving up
            for i, t in enumerate(texts, 1):
                if quote_on_page(it["quote"], t):
                    pg, ok = i, True
                    break
        it["page"] = pg if ok else None
        it["quote_verified"] = ok
        items.append(it)
    return {"call_quarter": out.get("call_quarter"), "items": items}


# --- period helpers ---------------------------------------------------------------------------
def parse_period(label: str | None) -> dict | None:
    if not label:
        return None
    t = label.upper().replace(" ", "")
    m = re.search(r"Q([1-4])FY(\d{2,4})", t)
    if m:
        q, fy = int(m.group(1)), int(m.group(2)) % 100 + 2000
        end = {1: date(fy - 1, 6, 30), 2: date(fy - 1, 9, 30), 3: date(fy - 1, 12, 31), 4: date(fy, 3, 31)}[q]
        return {"kind": "Q", "end": end, "fy": fy}
    m = re.search(r"H([12])FY(\d{2,4})", t)
    if m:
        h, fy = int(m.group(1)), int(m.group(2)) % 100 + 2000
        return {"kind": "H", "half": h, "fy": fy, "end": date(fy - 1, 9, 30) if h == 1 else date(fy, 3, 31)}
    m = re.search(r"FY(\d{2,4})", t)
    if m:
        fy = int(m.group(1)) % 100 + 2000
        return {"kind": "FY", "fy": fy, "end": date(fy, 3, 31)}
    return None


def default_period(made_in: str | None) -> dict | None:
    """When management gives a target without a period, judge it on the fiscal year it was said in;
    a Q4 call (held after the year ends) talks about the NEXT year."""
    p = parse_period(made_in)
    if not p:
        return None
    fy = p["fy"] + 1 if p["kind"] == "Q" and p["end"].month == 3 else p["fy"]
    return {"kind": "FY", "fy": fy, "end": date(fy, 3, 31), "assumed": True}


def _fy_quarters(fy: int) -> list[date]:
    return [date(fy - 1, 6, 30), date(fy - 1, 9, 30), date(fy - 1, 12, 31), date(fy, 3, 31)]


def _q(m, d, key):
    cell = m["Q"].get(d, {}).get(key)
    return cell["v"] if cell else None


def actual_for(m: dict, metric: str, period: dict) -> dict | None:
    """Return {value, complete, basis} for a guided metric over a period, from extracted metrics."""
    key = {"revenue_growth": "revenue", "pat_growth": "pat", "ebitda_margin": "ebitda", "capex": "capex"}.get(metric)
    if not key:
        return None
    if period["kind"] == "Q":
        d = period["end"]
        if metric == "ebitda_margin":
            e, r = _q(m, d, "ebitda"), _q(m, d, "revenue")
            return {"value": round(e / r * 100, 1), "complete": True, "basis": f"{fin.quarter_label(d)} EBITDA margin"} if e is not None and r else None
        if metric == "capex":
            return None
        cur = _q(m, d, key)
        prev = _q(m, date(d.year - 1, d.month, d.day), key)
        g = fin.growth(cur, prev)["pct"]
        return {"value": g, "complete": True, "basis": f"{fin.quarter_label(d)} YoY"} if g is not None else None

    fy = period["fy"]
    qs = _fy_quarters(fy)
    if period["kind"] == "H":
        qs = qs[:2] if period["half"] == 1 else qs[2:]
    have = [d for d in qs if _q(m, d, "revenue") is not None]
    if not have:
        return None
    complete = len(have) == len(qs)
    span = f"{fin.quarter_label(have[0])}–{fin.quarter_label(have[-1])}" if len(have) > 1 else fin.quarter_label(have[0])
    if metric == "capex":
        for ptype in ("FY", "H"):
            for d, row in m[ptype].items():
                if row.get("capex") and fin.fy_label(d) == f"FY{fy % 100:02d}":
                    return {"value": row["capex"]["v"], "complete": ptype == "FY",
                            "basis": f"capex spent in {'FY' if ptype == 'FY' else 'H1 '}FY{fy % 100:02d} (cash-flow statement)"}
        return None
    if metric == "ebitda_margin":
        es = [_q(m, d, "ebitda") for d in have]
        rs = [_q(m, d, "revenue") for d in have]
        if None in es or None in rs or not sum(rs):
            return None
        return {"value": round(sum(es) / sum(rs) * 100, 1), "complete": complete,
                "basis": f"EBITDA margin {span}" + ("" if complete else " (year to date)")}
    cur = [_q(m, d, key) for d in have]
    prev = [_q(m, date(d.year - 1, d.month, d.day), key) for d in have]
    if None in cur or None in prev:
        return None
    g = fin.growth(sum(cur), sum(prev))["pct"]
    if g is None:
        return None
    return {"value": g, "complete": complete, "basis": f"YoY growth {span}" + ("" if complete else " (year to date)")}


def verdict(item: dict, actual: dict | None) -> tuple[str, str | None]:
    lo, hi = item.get("target_low"), item.get("target_high")
    if actual is None or actual.get("value") is None:
        return "pending", None
    v = actual["value"]
    if lo is None and hi is None:
        return "unverifiable", None
    lo = lo if lo is not None else hi
    if item.get("metric") == "capex":
        if not actual["complete"]:
            share = v / lo * 100 if lo else None
            return "tracking", (f"₹{v:,.0f} cr spent so far ({share:.0f}% of ₹{lo:,.0f} cr guided)" if share is not None else None)
        return ("met" if v >= 0.9 * lo else "missed"), f"₹{v:,.0f} cr spent vs ₹{lo:,.0f} cr guided"
    unit = "%" if item.get("unit") == "pct" or item.get("metric") != "capex" else ""
    tgt = f"{lo:g}{unit}" + (f"–{hi:g}{unit}" if hi is not None and hi != lo else "")
    above = hi is not None and v > hi
    if actual["complete"]:
        v_ = "met" if v >= lo else ("partly" if v >= lo * 0.8 else "missed")
    else:
        v_ = "on_track" if v >= lo else "behind"
    note = f"Actual {v:+.1f}{unit} vs guided {tgt}" if item.get("metric") != "ebitda_margin" else f"Actual {v:.1f}% vs guided {tgt}"
    if above:
        note += " (above range)"
    return v_, note


def assess_qualitative(items: list[dict], sources: dict[str, str]) -> dict[int, dict]:
    if not items:
        return {}
    promises = "\n".join(f"[{it['id']}] ({it.get('made_in') or 'call'}) {it['quote']}" for it in items)
    src_text = "\n".join(f"{k}: {v[:900]}" for k, v in sources.items())
    out = generate_json("guidance_assess", "You assess management delivery strictly from sources. JSON only.",
                        ASSESS_PROMPT.format(promises=promises, sources=src_text), tier="smart", version="assess-v1")
    res = {}
    for r in out.get("items") or []:
        try:
            res[int(r["id"])] = r
        except (KeyError, TypeError, ValueError):
            continue
    return res
