"""Type-specific enrichment of announcements (push side) and results extraction (shared with research).

  results filing     -> headline table (Revenue / EBITDA / PBT / PAT, QoQ & YoY) computed in code
  management change  -> who, what role, when, and the profile printed in the filing itself
  other material     -> a one-line summary + key facts
  routine            -> nothing (no LLM spend)
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

from sqlalchemy import select

from .. import config
from ..ai import prompts
from ..ai.llm import LlmUnavailable, generate_json
from ..db import Announcement, AnnouncementAnalysis, Company, Document, FinancialMetric
from ..sources import pdfs
from ..sources.http import SourceError
from . import financials as fin
from .score import score

log = logging.getLogger("finn.enrich")

SUMMARY_CATEGORIES = {"M&A", "fund_raise", "litigation", "credit_rating", "capex", "pledging",
                      "bonus_split", "press_release", "dividend", "insider_trading"}

_TABLE_HINTS = re.compile(
    r"profit before (tax|exceptional)|revenue from operations|interest earned|total income|net profit", re.I)
_BS_HINTS = re.compile(r"statement of assets and liabilities|balance sheet|total equity", re.I)
_CF_HINTS = re.compile(r"cash flow|operating activities", re.I)
_CONSOL = re.compile(r"consolidated", re.I)
# Results-statement titles survive poor scans only roughly ("Statcmcnt of Consolidstcd ... Rcsulls"), so match loosely.
_STATEMENT_TITLE = re.compile(r"st.t.?m.nt of .{0,60}(r.sul|rcsul)", re.I)


def _select_result_pages(texts: list[str], limit: int = 8) -> list[int]:
    """Pick the pages most likely to hold the P&L, segment, balance-sheet and cash-flow tables."""
    if pdfs.is_scanned(texts):
        return list(range(min(len(texts), 10)))
    scored = []
    for i, t in enumerate(texts):
        s = 0
        if _TABLE_HINTS.search(t):
            s += 3 + len(_TABLE_HINTS.findall(t))
        if _STATEMENT_TITLE.search(t):
            s += 5
            if re.search(r"consolid", t, re.I):
                s += 2
        if _BS_HINTS.search(t):
            s += 2
        if _CF_HINTS.search(t):
            s += 2
        if re.search(r"segment", t, re.I):
            s += 1
        if _CONSOL.search(t):
            s += 2
        if s:
            scored.append((s, i))
    pages = sorted(i for _, i in sorted(scored, reverse=True)[:limit])
    return pages or list(range(min(len(texts), limit)))


def _norm_period(p: dict, factor: float) -> dict:
    out = {k: fin.to_cr(p.get(k), factor) for k in fin.FIELDS}
    out["period_end"] = p.get("period_end")
    out["months"] = p.get("months")
    out["page"] = p.get("page")
    return out


def extract_results(path, is_financial: bool) -> dict:
    """Run results extraction on a PDF and return the structured, code-computed result card."""
    texts = pdfs.page_texts(path)
    pages = _select_result_pages(texts)
    subset = pdfs.subset_pdf(path, pages)
    raw = generate_json(
        "results_extract", prompts.GROUNDING, prompts.RESULTS_PROMPT.format(n=len(pages)),
        tier="fast", pdf=subset, version="results-v3",
    )
    if not raw.get("is_financial_results"):
        return {"kind": "not_results"}
    factor = fin.unit_factor(raw.get("unit"))
    if factor is None:
        return {"kind": "results", "error": f"Unrecognised unit '{raw.get('unit')}'", "raw_unit": raw.get("unit")}
    page_map = lambda p: pages[p - 1] + 1 if isinstance(p, int) and 1 <= p <= len(pages) else None  # noqa: E731
    is_fin = is_financial or raw.get("entity_type") in {"bank", "nbfc", "insurance"}

    periods = [_norm_period(p, factor) for p in raw.get("periods") or []]
    notes = {}
    for p in periods:
        p["page"] = page_map(p.get("page"))
        note = fin.reconcile(p)  # may fix or drop a misread revenue figure
        if note:
            notes[id(p)] = note
    cols = fin.pick_columns(periods)
    if not cols:
        return {"kind": "results", "error": "No quarterly column found", "periods": periods}
    col_notes = [notes[id(cols[k])] for k in ("current", "previous", "year_ago") if cols.get(k) is not None and id(cols[k]) in notes]

    heads = {k: (fin.headline(cols[k], is_fin) if cols.get(k) else None) for k in ("current", "previous", "year_ago")}
    metric_rows = []
    labels = [("revenue", "Interest earned" if is_fin else "Revenue"),
              ("ebitda", "Operating profit" if is_fin else "EBITDA"), ("pbt", "PBT"), ("pat", "PAT")]
    for key, label in labels:
        cur = heads["current"][key]
        prev = heads["previous"][key] if heads["previous"] else None
        ya = heads["year_ago"][key] if heads["year_ago"] else None
        metric_rows.append({
            "metric": key, "label": label, "current": cur, "previous": prev, "year_ago": ya,
            "qoq": fin.growth(cur, prev), "yoy": fin.growth(cur, ya),
        })
    cur_end = cols["current_end"]
    segments = []
    for sgm in raw.get("segments") or []:
        v = fin.to_cr(sgm.get("revenue"), factor)
        if sgm.get("name") and v is not None and v > 0:
            segments.append({"name": sgm["name"].strip(), "revenue": v, "page": page_map(sgm.get("page"))})
    total_seg = sum(x["revenue"] for x in segments)
    for x in segments:
        x["share_pct"] = round(x["revenue"] / total_seg * 100, 1) if total_seg else None

    bs = raw.get("balance_sheet") or None
    if bs:
        bs = {k: (fin.to_cr(v, factor) if k not in ("as_of", "page") else v) for k, v in bs.items()}
        bs["page"] = page_map(bs.get("page"))
    cf = raw.get("cash_flow") or None
    if cf:
        cf = {k: (fin.to_cr(v, factor) if k not in ("period_end", "months", "page") else v) for k, v in cf.items()}
        cf["page"] = page_map(cf.get("page"))
        if cf.get("capex") is not None:
            cf["capex"] = abs(cf["capex"])

    return {
        "kind": "results",
        "basis": raw.get("basis") or "consolidated",
        "unit_in_filing": raw.get("unit"),
        "is_financial": is_fin,
        "quarter": fin.quarter_label(cur_end),
        "period_end": cur_end.isoformat(),
        "rows": metric_rows,
        "margins": {
            "ebitda_margin": heads["current"]["ebitda_margin"],
            "ebitda_margin_prev_year": heads["year_ago"]["ebitda_margin"] if heads["year_ago"] else None,
            "pat_margin": heads["current"]["pat_margin"],
        },
        "ebitda_method": heads["current"]["ebitda_method"],
        "checks": fin.checks(cols["current"]) + col_notes,
        "page": cols["current"].get("page"),
        "segments": segments,
        "balance_sheet": bs,
        "cash_flow": cf,
        "periods": periods,
        "notes": raw.get("notes"),
    }


def store_metrics(s, company: Company, doc: Document, card: dict, filed_at: datetime | None) -> int:
    """Persist every extracted period column as financial_metrics rows (used by research)."""
    if card.get("kind") != "results" or card.get("error"):
        return 0
    basis = card.get("basis", "consolidated")
    n = 0

    def put(period_end, ptype, metric, value, page):
        nonlocal n
        if value is None or not period_end:
            return
        pe = date.fromisoformat(str(period_end)[:10])
        row = s.execute(select(FinancialMetric).where(
            FinancialMetric.company_id == company.id, FinancialMetric.period_end == pe,
            FinancialMetric.period_type == ptype, FinancialMetric.basis == basis,
            FinancialMetric.metric == metric)).scalar_one_or_none()
        if row and row.filed_at and filed_at and row.filed_at > filed_at:
            return  # a newer filing already supplied this (possibly restated) number
        if not row:
            row = FinancialMetric(company_id=company.id, period_end=pe, period_type=ptype, basis=basis, metric=metric)
            s.add(row)
        row.value_cr, row.document_id, row.page, row.filed_at = value, doc.id, page, filed_at
        row.method = "computed" if metric in ("ebitda",) else "extracted"
        n += 1

    for p in card.get("periods") or []:
        ptype = {3: "Q", 6: "H", 12: "FY"}.get(p.get("months"))
        if not ptype:
            continue
        h = fin.headline(p, card.get("is_financial", False))
        for m in ("revenue", "ebitda", "pbt", "pat"):
            put(p["period_end"], ptype, m, h[m], p.get("page"))
        for m in ("finance_costs", "depreciation", "other_income", "tax_expense"):
            put(p["period_end"], ptype, m, p.get(m), p.get("page"))
    bs = card.get("balance_sheet")
    if bs and bs.get("as_of"):
        for m in ("total_equity", "borrowings_non_current", "borrowings_current", "cash_and_equivalents",
                  "other_bank_balances", "current_investments", "trade_receivables", "inventories",
                  "trade_payables", "total_assets"):
            put(bs["as_of"], "BS", m, bs.get(m), bs.get("page"))
    cf = card.get("cash_flow")
    if cf and cf.get("period_end"):
        ptype = {6: "H", 12: "FY"}.get(cf.get("months"), "H")
        put(cf["period_end"], ptype, "cfo", cf.get("cfo"), cf.get("page"))
        put(cf["period_end"], ptype, "capex", cf.get("capex"), cf.get("page"))
    return n


def ensure_document(s, ann: Announcement, doc_type: str, sha: str | None, pages: int | None) -> Document:
    doc = s.execute(select(Document).where(Document.company_id == ann.company_id,
                                           Document.url == ann.attachment_url)).scalar_one_or_none()
    if not doc:
        doc = Document(company_id=ann.company_id, doc_type=doc_type, title=ann.subject[:300],
                       filed_at=ann.filed_at, url=ann.attachment_url, discovered_via=ann.exchange.lower(),
                       announcement_id=ann.id)
        s.add(doc)
        s.flush()
    doc.sha256 = sha or doc.sha256
    doc.page_count = pages or doc.page_count
    return doc


def enrich(s, ann: Announcement, cares: list[str]) -> None:
    a = ann.analysis
    company = ann.company
    if a is None:
        return
    needs_llm = (
        (a.category == "results" and a.subtype == "results_filing")
        or (a.category == "management_change")
        or (a.category in SUMMARY_CATEGORIES and a.importance >= 30)
    )
    if not needs_llm:
        a.enrich_status = "skipped"
        return
    if not ann.attachment_url:
        a.enrich_status = "skipped"
        a.enrich_error = "no attachment"
        return
    if not config.llm_enabled() and not (config.GROQ_API_KEY and a.category != "results"):
        a.enrich_status = "needs_key"
        return
    try:
        path, sha = pdfs.download(ann.attachment_url)
        ann.attachment_sha256 = sha
        texts = pdfs.page_texts(path, max_pages=40)
        facts: dict = {}
        if a.category == "results":
            card = extract_results(path, company.is_financial)
            if card.get("kind") == "not_results":
                a.subtype = "results_other"
                a.structured = None
                a.importance, a.importance_reasons = score("results", "results_presentation", cares)
            else:
                doc = ensure_document(s, ann, "results", sha, len(texts))
                doc.extracted = {k: card.get(k) for k in ("quarter", "period_end", "basis", "segments", "balance_sheet", "cash_flow")}
                doc.period_label = card.get("quarter")
                store_metrics(s, company, doc, card, ann.filed_at)
                a.structured = card
                pat = next((r for r in card.get("rows", []) if r["metric"] == "pat"), None)
                if pat and pat["yoy"]["pct"] is not None:
                    facts["pat_yoy_pct"] = pat["yoy"]["pct"]
                a.summary = _results_line(card)
        elif a.category == "management_change":
            if pdfs.is_scanned(texts):
                raise SourceError("filing is a scanned image; no text to read")
            out = generate_json("mgmt_change", prompts.GROUNDING,
                                prompts.MGMT_PROMPT.format(text=prompts.paged(texts, 12000)), tier="fast", version="mgmt-v1")
            people = [p for p in out.get("people") or [] if p.get("name")]
            a.structured = {"kind": "management_change", "people": people}
            a.summary = out.get("summary")
            if any(re.search(r"\b(ceo|cfo|chief|managing director|md)\b", p.get("role") or "", re.I) for p in people):
                a.subtype = "top"
        else:
            if pdfs.is_scanned(texts):
                raise SourceError("filing is a scanned image; no text to read")
            out = generate_json(
                "summary", prompts.GROUNDING,
                prompts.SUMMARY_PROMPT.format(company=company.name, category=a.category, subject=ann.subject,
                                              text=prompts.paged(texts, 9000)),
                tier="fast", version="summary-v1")
            a.summary = out.get("summary")
            a.structured = {"kind": "summary", "key_facts": out.get("key_facts") or [], "page": out.get("page")}
            facts["materiality"] = out.get("materiality")
        a.importance, a.importance_reasons = score(a.category, a.subtype, cares, facts)
        a.enrich_status = "done"
        a.enrich_error = None
    except LlmUnavailable as e:
        a.enrich_status = "failed"
        a.enrich_error = f"AI unavailable: {e}"[:500]
    except (SourceError, OSError, ValueError, KeyError, TypeError) as e:
        log.warning("enrich failed for %s: %s", ann.id, e)
        a.enrich_status = "failed"
        a.enrich_error = str(e)[:500]


def _fmt_cr(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"₹{v:,.0f} cr" if abs(v) >= 100 else f"₹{v:,.1f} cr"


def _results_line(card: dict) -> str:
    rows = {r["metric"]: r for r in card.get("rows", [])}
    rev, pat = rows.get("revenue"), rows.get("pat")
    bits = []
    if rev and rev["current"] is not None:
        bits.append(f"{rev['label']} {_fmt_cr(rev['current'])} ({rev['yoy']['label']} YoY)")
    if pat and pat["current"] is not None:
        bits.append(f"PAT {_fmt_cr(pat['current'])} ({pat['yoy']['label']} YoY)")
    m = card.get("margins", {})
    if m.get("ebitda_margin") is not None and not card.get("is_financial"):
        bits.append(f"EBITDA margin {m['ebitda_margin']:.1f}%")
    return f"{card.get('quarter')}: " + ", ".join(bits) if bits else "Results filed"
