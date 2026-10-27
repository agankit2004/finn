"""Core unit tests: maths, classification, alerts, grounding, guidance, retrieval, extraction plumbing.

Run:  cd backend && python -m pytest -q
These tests use an isolated temporary database and never touch the network.
"""
import os
import tempfile
from datetime import date, datetime, timedelta

os.environ["FINN_DATA_DIR"] = tempfile.mkdtemp(prefix="finn-test-")
os.environ.pop("GEMINI_API_KEY", None)

import pymupdf  # noqa: E402
import pytest  # noqa: E402

from finn.db import Company, Price, init_db, session_scope  # noqa: E402
from finn.pipeline import alerts, financials as fin  # noqa: E402
from finn.pipeline.classify import classify_rule  # noqa: E402
from finn.pipeline.score import ROUTINE_THRESHOLD, score  # noqa: E402
from finn.research import grounding, guidance, index  # noqa: E402

init_db()


# --- financial maths ---------------------------------------------------------------------------
def test_growth_handles_signs_and_zero():
    assert fin.growth(112, 100)["pct"] == 12.0
    assert fin.growth(90, 100)["pct"] == -10.0
    assert fin.growth(10, -5)["label"] == "turned positive"
    assert fin.growth(-5, 10)["label"] == "turned negative"
    assert fin.growth(-3, -5)["label"] == "loss narrowed"
    assert fin.growth(-8, -5)["label"] == "loss widened"
    assert fin.growth(5, 0)["label"] == "n/m"
    assert fin.growth(None, 4)["pct"] is None


def test_units_normalise_to_crore():
    assert fin.unit_factor("Lakhs") == 0.01
    assert fin.unit_factor("₹ in crore") == 1.0
    assert fin.unit_factor("Rs. Million") is None or fin.unit_factor("million") == 0.1
    assert fin.to_cr(123456, fin.unit_factor("lakh")) == 1234.56


def test_ebitda_definition():
    p = {"revenue_from_operations": 1000, "pbt": 150, "finance_costs": 20, "depreciation": 50, "other_income": 30,
         "exceptional_items": -10}
    h = fin.headline(p, is_financial=False)
    # PBT before exceptional (150 - (-10) = 160) + 20 + 50 - 30 = 200
    assert h["ebitda"] == 200
    assert h["ebitda_margin"] == 20.0


def test_bank_template_uses_operating_profit():
    h = fin.headline({"interest_earned": 500, "operating_profit": 120, "pbt": 90, "pat": 70}, is_financial=True)
    assert h["revenue"] == 500 and h["ebitda"] == 120 and "operating profit" in h["ebitda_method"]


def test_columns_chosen_by_date_not_label():
    periods = [
        {"period_end": "2025-09-30", "months": 3, "revenue_from_operations": 90},
        {"period_end": "2026-09-30", "months": 3, "revenue_from_operations": 110},
        {"period_end": "2026-06-30", "months": 3, "revenue_from_operations": 105},
        {"period_end": "2026-09-30", "months": 6, "revenue_from_operations": 215},
    ]
    cols = fin.pick_columns(periods)
    assert cols["current"]["revenue_from_operations"] == 110
    assert cols["previous"]["revenue_from_operations"] == 105
    assert cols["year_ago"]["revenue_from_operations"] == 90


def test_fiscal_labels():
    assert fin.quarter_label(date(2026, 9, 30)) == "Q2 FY27"
    assert fin.quarter_label(date(2027, 3, 31)) == "Q4 FY27"
    assert fin.fy_label(date(2026, 4, 1)) == "FY27"


def test_consistency_check_flags_bad_pat():
    assert fin.checks({"pbt": 100, "tax_expense": 25, "pat": 75}) == []
    assert fin.checks({"pbt": 100, "tax_expense": 25, "pat": 40})


# --- classification & scoring ------------------------------------------------------------------
@pytest.mark.parametrize("subject,cat,sub", [
    ("Outcome of Board Meeting - Financial Results for Q2", "results", "results_filing"),
    ("Board Meeting Intimation for Considering Financial Results", "results", "results_intimation"),
    ("Newspaper Publication of Financial Results", "results", "results_ad"),
    ("Closure of Trading Window", "unclassified", "trading_window"),
    ("Resignation of Chief Financial Officer", "management_change", "top"),
    ("Appointment of Statutory Auditors", "unclassified", "auditor"),
    ("Earnings Call Transcript", "earnings_call", "transcript"),
    ("Credit rating downgraded by ICRA", "credit_rating", "downgrade"),
    ("Disclosure under Regulation 29 of SAST", "insider_trading", None),
    ("Creation of pledge on promoter shares", "pledging", None),
    ("Buyback of equity shares", "fund_raise", None),
    # real BSE subjects seen on 27 Oct 2026 (via screener.in)
    ("Outcome Of Board Meeting Of Larsen & Toubro Limited Held On October 27, 2026", "results", "board_outcome"),
    ("Board Meeting Outcome for Un-Audited Financial Results For The Quarter Ended 30th September 2026", "results", "results_filing"),
    ("Announcement under Regulation 30 (LODR) - Bagging/receiving of order(s)/contract(s)", "press_release", "order_win"),
    ("Initial Public Offer Of Jio Platforms Limited - Update", "fund_raise", None),
    ("Intimation of Repayment of Commercial Paper (CP)", "unclassified", "debt_servicing"),
    ("Analyst Presentation - Q2 / H1 FY27", "results", "results_presentation"),
    ("Announcement under Regulation 30 (LODR)-Earnings Call Transcript", "earnings_call", "transcript"),
])
def test_rules(subject, cat, sub):
    c = classify_rule(subject)
    assert c is not None and c.category == cat and c.subtype == sub


def test_routine_is_collapsed_and_cares_boost():
    low, _ = score("unclassified", "trading_window", [])
    assert low < ROUTINE_THRESHOLD
    a, _ = score("M&A", None, [])
    b, reasons = score("M&A", None, ["M&A"])
    assert b == a + 10 and any("track" in r for r in reasons)


# --- alerts -----------------------------------------------------------------------------------------
def _seed_prices(sym, closes, vols):
    with session_scope() as s:
        c = Company(nse_symbol=sym, name=sym)
        s.add(c)
        s.flush()
        d0 = date(2026, 1, 1)
        for i, (cl, v) in enumerate(zip(closes, vols)):
            s.add(Price(company_id=c.id, date=d0 + timedelta(days=i), close=cl, volume=v))
        return c.id


def test_price_and_volume_alerts_fire_once():
    closes = [100.0] * 25 + [106.0]
    vols = [1000.0] * 25 + [2500.0]
    cid = _seed_prices("TESTA", closes, vols)
    with session_scope() as s:
        rules = alerts.get_rules(s)
        c = s.get(Company, cid)
        n1 = alerts.evaluate_prices(s, c, rules, lookback_days=2)
        n2 = alerts.evaluate_prices(s, c, rules, lookback_days=2)
    assert n1 == 2  # price (+6% >= 4%) and volume (2.5x >= 2x)
    assert n2 == 0  # never fires twice for the same day


def test_volume_baseline_excludes_today():
    with session_scope() as s:
        rows = [Price(company_id=0, date=date(2026, 1, i + 1), close=100, volume=1000) for i in range(20)]
        rows.append(Price(company_id=0, date=date(2026, 1, 21), close=100, volume=3000))
        st = alerts.price_stats(rows)
    assert st["volume_mult"] == 3.0


# --- grounding --------------------------------------------------------------------------------------
def test_grounding_flags_unsupported_numbers():
    src = {"F1": "Revenue Q2 FY27 = ₹65,800.0 cr", "S1": "EBITDA margin of around 18%"}
    ok = grounding.check_statement("Revenue was ₹65,800 cr in Q2 FY27.", ["F1"], src)
    bad = grounding.check_statement("Revenue was ₹70,000 cr.", ["F1"], src)
    nocite = grounding.check_statement("Margins are 18%.", [], src)
    fake = grounding.check_statement("Margins are 18%.", ["S9"], src)
    assert ok["verified"] and not bad["verified"] and not nocite["verified"] and not fake["verified"]


# --- guidance ---------------------------------------------------------------------------------------
def test_period_parse():
    assert guidance.parse_period("FY27")["end"] == date(2027, 3, 31)
    assert guidance.parse_period("Q3 FY27")["end"] == date(2026, 12, 31)
    assert guidance.parse_period("H2 FY27")["half"] == 2
    assert guidance.parse_period("medium term") is None


def _m(qvals):
    return {"basis": "consolidated", "Q": {d: {k: {"v": v} for k, v in row.items()} for d, row in qvals.items()},
            "H": {}, "FY": {}, "BS": {}}


def test_guidance_verdict_ytd_by_code():
    m = _m({date(2025, 6, 30): {"revenue": 100, "ebitda": 18}, date(2025, 9, 30): {"revenue": 100, "ebitda": 18},
            date(2026, 6, 30): {"revenue": 111, "ebitda": 20}, date(2026, 9, 30): {"revenue": 113, "ebitda": 21}})
    act = guidance.actual_for(m, "revenue_growth", guidance.parse_period("FY27"))
    assert act["value"] == 12.0 and act["complete"] is False
    v, note = guidance.verdict({"metric": "revenue_growth", "target_low": 10, "target_high": 12, "unit": "pct"}, act)
    assert v == "on_track" and "12.0" in note
    v2, _ = guidance.verdict({"metric": "revenue_growth", "target_low": 15, "target_high": None, "unit": "pct"}, act)
    assert v2 == "behind"
    mg = guidance.actual_for(m, "ebitda_margin", guidance.parse_period("FY27"))
    assert mg["value"] == round(41 / 224 * 100, 1)


def test_quote_verification():
    assert guidance.quote_on_page("we expect revenue growth of 15 to 17 percent", "Management: We expect revenue growth of 15 to 17 percent this year.")
    assert not guidance.quote_on_page("margins will double next year", "We expect revenue growth of 15 percent.")


# --- retrieval --------------------------------------------------------------------------------------
def test_bm25_ranks_relevant_chunk_first():
    docs = [index.tokens("Capex for FY27 will be Rs 5,000 crore for the new plant"),
            index.tokens("Dividend policy and shareholder returns"),
            index.tokens("Revenue grew due to volume growth in exports")]
    bm = index.BM25(docs)
    sc = bm.scores(index.tokens("what is the capex plan"))
    assert sc.index(max(sc)) == 0


def test_chunking_keeps_page_numbers():
    texts = ["Intro page " * 50, "Management Discussion\n" + ("Demand was strong. " * 300), "Risks\n" + ("Input costs rose. " * 40)]
    chunks = index.chunk_pages(texts)
    assert chunks and all(1 <= c["page_start"] <= c["page_end"] <= 3 for c in chunks)


# --- results extraction plumbing (LLM mocked) ---------------------------------------------------------
def test_extract_results_end_to_end(monkeypatch, tmp_path):
    from finn.pipeline import enrich

    doc = pymupdf.open()
    for i in range(5):
        page = doc.new_page()
        text = "Cover letter to the exchange" if i == 0 else (
            "Statement of Consolidated Unaudited Financial Results. Revenue from operations. Profit before tax. "
            "Total income. Net profit" if i == 2 else f"Notes page {i}")
        page.insert_text((72, 72), text)
    path = tmp_path / "r.pdf"
    doc.save(path)

    def fake_llm(purpose, system, prompt, **kw):
        assert kw.get("pdf", b"").startswith(b"%PDF")
        return {"is_financial_results": True, "basis": "consolidated", "unit": "lakh", "entity_type": "non_financial",
                "periods": [
                    {"period_end": "2026-09-30", "months": 3, "page": 1, "revenue_from_operations": 1100000, "other_income": 20000,
                     "finance_costs": 10000, "depreciation": 40000, "exceptional_items": 0, "pbt": 170000, "tax_expense": 42500, "pat": 127500},
                    {"period_end": "2026-06-30", "months": 3, "page": 1, "revenue_from_operations": 1050000, "other_income": 20000,
                     "finance_costs": 10000, "depreciation": 40000, "exceptional_items": 0, "pbt": 160000, "tax_expense": 40000, "pat": 120000},
                    {"period_end": "2025-09-30", "months": 3, "page": 1, "revenue_from_operations": 1000000, "other_income": 20000,
                     "finance_costs": 10000, "depreciation": 40000, "exceptional_items": 0, "pbt": 150000, "tax_expense": 37500, "pat": 112500},
                ],
                "segments": [{"name": "A", "revenue": 800000, "page": 1}, {"name": "B", "revenue": 300000, "page": 1}]}

    monkeypatch.setattr(enrich, "generate_json", fake_llm)
    card = enrich.extract_results(path, is_financial=False)
    rows = {r["metric"]: r for r in card["rows"]}
    assert card["quarter"] == "Q2 FY27"
    assert rows["revenue"]["current"] == 11000.0  # lakh -> crore
    assert rows["revenue"]["yoy"]["pct"] == 10.0
    assert rows["pat"]["qoq"]["pct"] == 6.2
    assert rows["ebitda"]["current"] == 2000.0  # 1700 + 100 + 400 - 200
    assert card["page"] is not None and card["page"] >= 1  # mapped back to the original PDF
    assert card["segments"][0]["share_pct"] == 72.7
    assert card["checks"] == []


def test_misread_revenue_is_recomputed_or_dropped():
    # Infosys Q1 FY27 as read from a scanned filing: employee cost (25,287) taken as revenue.
    q1 = {"revenue_from_operations": 25287.0, "other_income": 984.0, "total_income": 49195.0,
          "total_expenses": 38167.0, "pbt": 11028.0, "period_end": "2026-06-30"}
    note = fin.reconcile(q1)
    assert q1["revenue_from_operations"] == 48211.0 and "recomputed" in note  # confirmed by 49,195 − 38,167 = 11,028
    bad = {"revenue_from_operations": 25287.0, "other_income": 984.0, "total_income": 49195.0,
           "total_expenses": 30000.0, "pbt": 11028.0, "period_end": "2026-06-30"}
    assert "isn't shown" in fin.reconcile(bad) and bad["revenue_from_operations"] is None
    ok = {"revenue_from_operations": 49244.0, "other_income": 848.0, "total_income": 50092.0}
    assert fin.reconcile(ok) is None and ok["revenue_from_operations"] == 49244.0
