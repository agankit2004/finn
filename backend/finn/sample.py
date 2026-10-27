"""SAMPLE MODE fixtures: synthetic, clearly labelled data for UI development and offline demos.

Nothing here is real. Prices are seeded random walks; filings are invented and marked [Sample];
the UI shows a persistent "Sample data" banner whenever FINN_SAMPLE_MODE=1. Sample mode uses its own
database file (data/finn_sample.db), so it can never mix with real ingested data.
"""
from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from .db import (Announcement, AnnouncementAnalysis, Chunk, Company, Document, GuidanceItem, Holding, NewsItem, Price,
                 get_setting, init_db, session_scope, set_setting, utcnow)
from .pipeline import alerts
from .pipeline import financials as fin
from .pipeline.classify import classify_rule
from .pipeline.enrich import store_metrics
from .pipeline.score import score
from .universe import DEMO_PORTFOLIO, KNOWN, RESEARCH_PICKS

IST = timezone(timedelta(hours=5, minutes=30))
BASE_PRICE = {"RELIANCE": 1400, "HDFCBANK": 950, "BAJFINANCE": 900, "TCS": 3100, "INFY": 1500, "BHARTIARTL": 1900,
              "LT": 3600, "HAL": 4400, "SUNPHARMA": 1650, "APOLLOHOSP": 7200, "MARUTI": 12500, "TITAN": 3500,
              "TRENT": 5000, "ITC": 410, "HINDUNILVR": 2450, "DIXON": 15500, "POLYCAB": 7000, "TATAPOWER": 390,
              "ASIANPAINT": 2400, "PIDILITIND": 1450, "INDIGO": 5600, "NESTLEIND": 1200}


def _ist(days_ago: float, hour: int, minute: int) -> datetime:
    d = datetime.now(IST) - timedelta(days=days_ago)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)


def _business_days(n: int) -> list[date]:
    out, d = [], datetime.now(IST).date()
    if datetime.now(IST).hour < 16:
        d -= timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def _results_card(symbol: str, rev0: float, margin: float, growth: float, is_financial: bool, end: date) -> dict:
    """Build a synthetic results card through the SAME code path real extraction uses."""
    rnd = random.Random(symbol)
    def period(d: date, scale: float) -> dict:
        rev = rev0 * scale
        if is_financial:
            return {"period_end": d.isoformat(), "months": 3, "page": 2, "interest_earned": round(rev, 1),
                    "operating_profit": round(rev * margin, 1), "pbt": round(rev * margin * 0.78, 1),
                    "tax_expense": round(rev * margin * 0.78 * 0.25, 1), "pat": round(rev * margin * 0.78 * 0.75, 1)}
        ebitda = rev * margin
        dep, fc, oi = rev * 0.04, rev * 0.015, rev * 0.02
        pbt = ebitda - dep - fc + oi
        return {"period_end": d.isoformat(), "months": 3, "page": 2, "revenue_from_operations": round(rev, 1),
                "other_income": round(oi, 1), "finance_costs": round(fc, 1), "depreciation": round(dep, 1),
                "exceptional_items": 0, "pbt": round(pbt, 1), "tax_expense": round(pbt * 0.25, 1), "pat": round(pbt * 0.75, 1)}
    prev = {9: date(end.year, 6, 30), 12: date(end.year, 9, 30), 3: date(end.year - 1, 12, 31), 6: date(end.year, 3, 31)}[end.month]
    ya = date(end.year - 1, end.month, end.day)
    q_growth = rnd.uniform(-0.02, 0.05)
    periods = [period(end, 1.0), period(prev, 1 / (1 + q_growth)), period(ya, 1 / (1 + growth))]
    heads = {k: fin.headline(p, is_financial) for k, p in zip(("current", "previous", "year_ago"), periods)}
    rows = []
    for key, label in (("revenue", "Interest earned" if is_financial else "Revenue"),
                       ("ebitda", "Operating profit" if is_financial else "EBITDA"), ("pbt", "PBT"), ("pat", "PAT")):
        c, p, y = heads["current"][key], heads["previous"][key], heads["year_ago"][key]
        rows.append({"metric": key, "label": label, "current": c, "previous": p, "year_ago": y,
                     "qoq": fin.growth(c, p), "yoy": fin.growth(c, y)})
    return {"kind": "results", "basis": "consolidated", "unit_in_filing": "crore", "is_financial": is_financial,
            "quarter": fin.quarter_label(end), "period_end": end.isoformat(), "rows": rows,
            "margins": {"ebitda_margin": heads["current"]["ebitda_margin"],
                        "ebitda_margin_prev_year": heads["year_ago"]["ebitda_margin"], "pat_margin": heads["current"]["pat_margin"]},
            "ebitda_method": heads["current"]["ebitda_method"], "checks": [], "page": 2, "segments": [],
            "balance_sheet": None, "cash_flow": None, "periods": periods, "notes": "SAMPLE — synthetic figures"}


SAMPLE_FILINGS = [
    # (symbol, days_ago, hh, mm, subject)
    ("TCS", 0.0, 16, 15, "[Sample] Outcome of Board Meeting - Unaudited Financial Results for the quarter ended September 30"),
    ("INFY", 0.0, 11, 20, "[Sample] Resignation of Chief Financial Officer and appointment of successor"),
    ("HDFCBANK", 0.0, 9, 40, "[Sample] Acquisition of 9.5% stake in Example Payments Pvt Ltd"),
    ("HDFCBANK", 0.4, 17, 5, "[Sample] Unaudited Financial Results for the quarter ended September 30"),
    ("LT", 0.3, 18, 30, "[Sample] Receipt of order worth Rs 2,500 crore for a metro rail project"),
    ("TATAPOWER", 0.6, 12, 10, "[Sample] Credit Rating - CRISIL reaffirms AA+ / Stable"),
    ("SUNPHARMA", 0.2, 14, 45, "[Sample] Order passed by tax authority - demand of Rs 85 crore, company to appeal"),
    ("DIXON", 0.5, 15, 50, "[Sample] Board approves capacity expansion at Noida facility"),
    ("TITAN", 0.1, 10, 5, "[Sample] Intimation of Earnings Conference Call for Q2 results"),
    ("ITC", 0.25, 13, 0, "[Sample] Board Meeting Intimation for Considering And Approving Financial Results"),
    ("MARUTI", 0.15, 9, 15, "[Sample] Closure of Trading Window"),
    ("BHARTIARTL", 0.35, 11, 0, "[Sample] Allotment of equity shares under ESOS"),
    ("TRENT", 0.45, 16, 40, "[Sample] Newspaper Publication of Unaudited Financial Results"),
    ("POLYCAB", 0.55, 12, 30, "[Sample] Certificate under Regulation 74(5) of SEBI (DP) Regulations, 2018"),
    ("HAL", 0.65, 17, 20, "[Sample] Schedule of Analyst / Investor Meet"),
    ("APOLLOHOSP", 0.7, 10, 0, "[Sample] Record Date for Interim Dividend"),
    ("RELIANCE", 1.4, 19, 0, "[Sample] Transcript of Earnings Call for Q2"),
    ("BAJFINANCE", 2.2, 16, 0, "[Sample] Unaudited Financial Results for the quarter ended September 30"),
    ("HINDUNILVR", 2.6, 15, 10, "[Sample] Shareholders meeting through postal ballot - notice"),
]

RESULTS = {"TCS": (65800, 0.265, 0.064, False), "HDFCBANK": (88000, 0.27, 0.09, True), "BAJFINANCE": (19500, 0.62, 0.21, True)}


def load() -> None:
    init_db()
    with session_scope() as s:
        if get_setting(s, "sample_loaded"):
            return
    rnd = random.Random(42)
    days = _business_days(500)
    with session_scope() as s:
        alerts.ensure_default_rules(s)
        comp = {}
        for sym, (name, code, sector, isfin) in KNOWN.items():
            c = Company(nse_symbol=sym, name=name, bse_code=code, sector=sector, is_financial=isfin, source="sample",
                        market_cap_cr=round(BASE_PRICE[sym] * rnd.uniform(5e4, 6e5) / 1e3, 0), pe=round(rnd.uniform(18, 70), 1),
                        dividend_yield=round(rnd.uniform(0.2, 3.0), 2), stats_updated_at=utcnow())
            s.add(c)
            s.flush()
            comp[sym] = c
            p = BASE_PRICE[sym] * 0.8
            vol0 = rnd.uniform(1e6, 8e6)
            for i, d in enumerate(days):
                g = rnd.gauss(0.0006, 0.014)
                v = vol0 * math.exp(rnd.gauss(0, 0.3))
                last = i == len(days) - 1
                p *= math.exp(0 if last and sym in ("RELIANCE", "TCS", "INFY", "DIXON") else g)
                if last:
                    if sym == "RELIANCE":
                        p, v = p * 1.053, vol0 * 3.2
                    elif sym == "TCS":
                        p *= 1.028
                    elif sym == "INFY":
                        p *= 0.988
                    elif sym == "DIXON":
                        p, v = p * 0.952, vol0 * 2.4
                s.add(Price(company_id=c.id, date=d, open=p * 0.995, high=p * 1.01, low=p * 0.99, close=round(p, 2),
                            volume=round(v), source="sample"))
        for sym, qty in DEMO_PORTFOLIO.items():
            s.add(Holding(company_id=comp[sym].id, quantity=qty))
        s.flush()
        rules = alerts.get_rules(s)
        cares = rules["categories"]
        last_q = date(2026, 9, 30)
        for i, (sym, ago, hh, mm, subj) in enumerate(SAMPLE_FILINGS):
            c = comp[sym]
            ann = Announcement(company_id=c.id, exchange="SAMPLE", source_id=f"sample-{i}", filed_at=_ist(ago, hh, mm),
                               subject=subj, attachment_url=None)
            s.add(ann)
            s.flush()
            cl = classify_rule(subj)
            facts, structured, summary = {}, None, None
            if cl.category == "results" and cl.subtype == "results_filing" and sym in RESULTS:
                rev0, margin, growth, isfin = RESULTS[sym]
                structured = _results_card(sym, rev0, margin, growth, isfin, last_q)
                pat = structured["rows"][3]
                facts["pat_yoy_pct"] = pat["yoy"]["pct"]
                from .pipeline.enrich import _results_line
                summary = _results_line(structured)
            elif cl.category == "management_change":
                structured = {"kind": "management_change", "people": [
                    {"name": "A. Sample-Person", "change": "resigned", "role": "Chief Financial Officer",
                     "effective_date": "2027-01-31", "reason": "to pursue opportunities outside the company", "page": 1},
                    {"name": "B. Example", "change": "appointed", "role": "Chief Financial Officer",
                     "effective_date": "2027-02-01", "reason": None, "page": 2,
                     "profile": "[Sample profile] Chartered accountant with 22 years in finance; previously deputy CFO and head of investor relations.",
                     "prior_roles": ["Deputy CFO", "Head of Investor Relations"], "qualifications": ["CA", "MBA"]}]}
                summary = "[Sample] CFO resigns effective 31 Jan; deputy CFO named successor from 1 Feb."
            elif cl.category in ("M&A", "press_release", "credit_rating", "litigation", "capex", "dividend"):
                summary = {"M&A": "[Sample] Acquires 9.5% stake for ₹2,100 cr in cash; strategic investment in payments, no board seat.",
                           "press_release": "[Sample] Metro rail order worth ₹2,500 cr; to be executed over 36 months.",
                           "credit_rating": "[Sample] Long-term rating reaffirmed at AA+ with stable outlook.",
                           "litigation": "[Sample] Tax demand of ₹85 cr; company believes it has a strong case and will appeal.",
                           "capex": "[Sample] Board approves ₹450 cr to expand Noida capacity by 30%, commissioning in FY28.",
                           "dividend": "[Sample] Interim dividend record date set."}[cl.category]
                facts["materiality"] = "high" if cl.category in ("M&A", "press_release") else "medium"
                structured = {"kind": "summary", "key_facts": [], "page": 1}
            sc, reasons = score(cl.category, cl.subtype, cares, facts)
            a = AnnouncementAnalysis(announcement_id=ann.id, category=cl.category, subtype=cl.subtype, category_method=cl.method,
                                     importance=sc, importance_reasons=reasons, summary=summary, structured=structured,
                                     enrich_status="done" if structured else "skipped", model="sample")
            s.add(a)
            s.flush()
            alerts.evaluate_announcement(s, ann, rules)
        for sym in DEMO_PORTFOLIO:
            alerts.evaluate_prices(s, comp[sym], rules, lookback_days=1)
        for i, (sym, ago, src, title) in enumerate([
            ("TCS", 0.1, "Sample Wire", "[Sample] TCS shares rise after Q2 numbers; deal wins in focus"),
            ("TCS", 0.08, "Sample Daily", "[Sample] TCS Q2 results: deal wins in focus as shares rise"),
            ("RELIANCE", 0.2, "Sample Markets", "[Sample] Reliance trades heavy volumes ahead of AGM commentary"),
            ("HDFCBANK", 0.3, "Sample Business", "[Sample] HDFC Bank's payments stake: what the 9.5% deal means"),
            ("DIXON", 0.4, "Sample Wire", "[Sample] Dixon slips nearly 5% as brokerages flag margin pressure"),
        ]):
            n = NewsItem(company_id=comp[sym].id, url=f"https://example.com/sample-news/{i}", title=title, source=src,
                         published_at=utcnow() - timedelta(days=ago))
            s.add(n)
            s.flush()
            n.story_id = n.id
        first_tcs = s.execute(select(NewsItem).where(NewsItem.url == "https://example.com/sample-news/0")).scalar_one()
        s.execute(select(NewsItem).where(NewsItem.url == "https://example.com/sample-news/1")).scalar_one().story_id = first_tcs.id
        _sample_research(s, comp["RELIANCE"])
        set_setting(s, "sample_loaded", True)
    from .research.build import compose

    with session_scope() as s:
        rid = s.execute(select(Company.id).where(Company.nse_symbol == "RELIANCE")).scalar()
    compose(rid, synth_override=_sample_synth())


def _sample_research(s, c: Company) -> None:
    """A synthetic dossier for RELIANCE built through the real metrics/guidance code paths."""
    rnd = random.Random(7)
    q_ends = [date(2024, 9, 30), date(2024, 12, 31), date(2025, 3, 31), date(2025, 6, 30), date(2025, 9, 30),
              date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30)]
    rev = 230000.0
    periods = []
    for d in q_ends:
        rev *= 1 + rnd.uniform(0.0, 0.035)
        m = rnd.uniform(0.165, 0.185)
        ebitda = rev * m
        dep, fc, oi = rev * 0.055, rev * 0.026, rev * 0.018
        pbt = ebitda - dep - fc + oi
        periods.append({"period_end": d.isoformat(), "months": 3, "page": 3, "revenue_from_operations": round(rev, 1),
                        "other_income": round(oi, 1), "finance_costs": round(fc, 1), "depreciation": round(dep, 1),
                        "exceptional_items": 0, "pbt": round(pbt, 1), "tax_expense": round(pbt * 0.25, 1), "pat": round(pbt * 0.75, 1)})
    fy25 = [p for p in periods if "2024-06-30" < p["period_end"] <= "2025-03-31"]
    docs = []
    for i, title in enumerate(["[Sample] Results filing Q2 FY27", "[Sample] Results filing Q4 FY26"]):
        d = Document(company_id=c.id, doc_type="results", title=title, period_label="Q2 FY27" if i == 0 else "Q4 FY26",
                     filed_at=utcnow() - timedelta(days=5 + 150 * i), url=f"sample://results/{i}", discovered_via="sample",
                     parse_status="parsed", page_count=14,
                     extracted={"segments": [{"name": "Oil to Chemicals", "revenue": 150000, "share_pct": 56.0, "page": 6},
                                             {"name": "Retail", "revenue": 46000, "share_pct": 17.2, "page": 6},
                                             {"name": "Digital Services", "revenue": 40000, "share_pct": 15.0, "page": 6},
                                             {"name": "Oil & Gas", "revenue": 18000, "share_pct": 6.7, "page": 6},
                                             {"name": "Others", "revenue": 13500, "share_pct": 5.1, "page": 6}] if i == 0 else None,
                                "quarter": "Q2 FY27" if i == 0 else "Q4 FY26"})
        s.add(d)
        s.flush()
        docs.append(d)
    card = {"kind": "results", "basis": "consolidated", "is_financial": False, "periods": periods,
            "balance_sheet": {"as_of": "2026-09-30", "page": 9, "total_equity": 880000, "borrowings_non_current": 250000,
                              "borrowings_current": 80000, "cash_and_equivalents": 95000, "other_bank_balances": 20000,
                              "current_investments": 110000, "trade_receivables": 42000, "inventories": 160000,
                              "trade_payables": 190000, "total_assets": 1900000},
            "cash_flow": {"period_end": "2026-09-30", "months": 6, "page": 11, "cfo": 82000, "capex": 64000}}
    store_metrics(s, c, docs[0], card, utcnow())
    fy_card = {"kind": "results", "basis": "consolidated", "is_financial": False, "periods": [
        {**{k: round(sum(p[k] for p in fy25), 1) for k in ("revenue_from_operations", "other_income", "finance_costs", "depreciation", "pbt", "tax_expense", "pat")},
         "exceptional_items": 0, "period_end": "2025-03-31", "months": 12, "page": 4}],
        "cash_flow": {"period_end": "2026-03-31", "months": 12, "page": 12, "cfo": 175000, "capex": 135000}}
    store_metrics(s, c, docs[1], fy_card, utcnow() - timedelta(days=150))

    tr = Document(company_id=c.id, doc_type="transcript", title="[Sample] Q1 FY27 earnings call transcript", period_label="Q1 FY27",
                  filed_at=utcnow() - timedelta(days=80), url="sample://transcript/1", discovered_via="sample", parse_status="parsed", page_count=24)
    ar = Document(company_id=c.id, doc_type="annual_report", title="[Sample] Integrated Annual Report FY26", period_label="FY26",
                  filed_at=utcnow() - timedelta(days=100), url="sample://ar/1", discovered_via="sample", parse_status="parsed", page_count=410)
    s.add_all([tr, ar])
    s.flush()
    s.add_all([
        Chunk(document_id=ar.id, company_id=c.id, page_start=12, page_end=13, section="Business overview",
              text="[Sample text] The company operates across oil-to-chemicals, retail, digital services and new energy. "
                   "Oil-to-chemicals remains the largest segment by revenue, while retail and digital services are the main growth engines."),
        Chunk(document_id=ar.id, company_id=c.id, page_start=48, page_end=48, section="Management discussion",
              text="[Sample text] Retail added stores across tier-2 and tier-3 cities. Digital services subscriber base expanded, "
                   "with average revenue per user improving after tariff revisions."),
        Chunk(document_id=tr.id, company_id=c.id, page_start=6, page_end=6, section="Opening remarks",
              text="[Sample text] We expect consolidated revenue growth of 10 to 12% for FY27 and EBITDA margin of around 18%. "
                   "Capex for the year should be about Rs 1,30,000 crore, largely in new energy and digital."),
        Chunk(document_id=tr.id, company_id=c.id, page_start=14, page_end=14, section="Q&A",
              text="[Sample text] Margins in the chemicals business remain under pressure from weak global spreads; we expect "
                   "recovery only in the second half."),
    ])
    s.add_all([
        GuidanceItem(company_id=c.id, document_id=tr.id, page=6, made_in="Q1 FY27",
                     quote="[Sample] We expect consolidated revenue growth of 10 to 12% for FY27", metric="revenue_growth",
                     target_low=10, target_high=12, unit="pct", target_period="FY27"),
        GuidanceItem(company_id=c.id, document_id=tr.id, page=6, made_in="Q1 FY27",
                     quote="[Sample] ...and EBITDA margin of around 18%", metric="ebitda_margin", target_low=18, target_high=None,
                     unit="pct", target_period="FY27"),
        GuidanceItem(company_id=c.id, document_id=tr.id, page=6, made_in="Q1 FY27",
                     quote="[Sample] Capex for the year should be about Rs 1,30,000 crore", metric="capex", target_low=130000,
                     target_high=None, unit="cr", target_period="FY27"),
        GuidanceItem(company_id=c.id, document_id=tr.id, page=14, made_in="Q1 FY27",
                     quote="[Sample] we expect recovery only in the second half", metric="other", unit=None, target_period="H2 FY27"),
    ])


def _sample_synth() -> dict:
    return {
        "business": {"summary": "[Sample] A conglomerate spanning oil-to-chemicals, retail, digital services and new energy.",
                     "points": [{"text": "[Sample] Oil-to-chemicals is the largest segment by revenue.", "cites": ["S1"]},
                                {"text": "[Sample] Retail and digital services are the stated growth engines.", "cites": ["S1", "S2"]}]},
        "narrative_vs_numbers": [
            {"stance": "diverges", "text": "[Sample] Management guided FY27 revenue growth of 10 to 12%; year-to-date growth is running well below that.", "cites": ["G1"]},
            {"stance": "diverges", "text": "[Sample] An EBITDA margin of around 18% was guided, but chemicals spreads remain weak per the Q&A.", "cites": ["G2", "S4"]}],
        "bull": [{"text": "[Sample] Retail store expansion into smaller cities widens the growth runway.", "cites": ["S2"]},
                 {"text": "[Sample] Digital ARPU is improving after tariff revisions.", "cites": ["S2"]},
                 {"text": "[Sample] Capex guidance is being executed, building capacity for later growth.", "cites": ["G3"]}],
        "bear": [{"text": "[Sample] Chemicals margins are under pressure from weak global spreads.", "cites": ["S4"]},
                 {"text": "[Sample] Heavy capex on new energy keeps free cash flow thin.", "cites": ["S3"]},
                 {"text": "[Sample] Recovery in chemicals is pushed to the second half.", "cites": ["S4"]}],
        "open_questions": ["[Sample] What returns are expected on new-energy capex?", "[Sample] When do chemicals spreads normalise?"],
    }
