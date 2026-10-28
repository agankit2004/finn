from datetime import date

from fastapi.testclient import TestClient

from finn import api, config
from finn.db import Company, Holding, Price, init_db, session_scope

init_db()


def test_add_by_amount_edit_and_remove(monkeypatch):
    monkeypatch.setattr(config, "SAMPLE_MODE", True)  # no network calls from background tasks
    with session_scope() as s:
        c = Company(nse_symbol="PFTEST", name="Portfolio Test Ltd")
        s.add(c)
        s.flush()
        s.add(Price(company_id=c.id, date=date(2026, 10, 27), close=333.0, volume=1))
    client = TestClient(api.app)

    r = client.post("/api/portfolio/holdings", json={"symbol": "PFTEST", "amount": 10000})
    assert r.status_code == 200, r.text
    assert r.json()["quantity"] == 30  # 10,000 // 333 = 30 whole shares, computed in code
    assert r.json()["price"]["close"] == 333.0

    assert client.post("/api/portfolio/holdings", json={"symbol": "PFTEST", "quantity": 5}).status_code == 409
    assert client.post("/api/portfolio/holdings", json={"symbol": "PFTEST"}).status_code == 422

    assert client.patch("/api/portfolio/holdings/PFTEST", json={"quantity": 12}).status_code == 200
    with session_scope() as s:
        assert s.query(Holding).join(Company).filter(Company.nse_symbol == "PFTEST").one().quantity == 12
    assert client.patch("/api/portfolio/holdings/PFTEST", json={"quantity": 0}).status_code == 422

    assert client.delete("/api/portfolio/holdings/PFTEST").status_code == 200
    with session_scope() as s:
        assert s.query(Holding).join(Company).filter(Company.nse_symbol == "PFTEST").count() == 0


def test_amount_below_one_share_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "SAMPLE_MODE", True)
    with session_scope() as s:
        c = Company(nse_symbol="PFBIG", name="Expensive Ltd")
        s.add(c)
        s.flush()
        s.add(Price(company_id=c.id, date=date(2026, 10, 27), close=50000.0, volume=1))
    r = TestClient(api.app).post("/api/portfolio/holdings", json={"symbol": "PFBIG", "amount": 1000})
    assert r.status_code == 422 and "less than one share" in r.json()["detail"]


def test_price_alert_names_its_source():
    from datetime import datetime, timedelta

    from finn.db import AlertEvent
    day = (datetime.utcnow() - timedelta(days=1)).date()  # alerts list shows the last 14 days
    with session_scope() as s:
        c = Company(nse_symbol="SRCTEST", name="Source Test Ltd")
        s.add(c)
        s.flush()
        s.add(Holding(company_id=c.id, quantity=1))  # alerts are shown for holdings only
        s.add(Price(company_id=c.id, date=day, close=100.0, volume=1, source="yahoo"))
        s.add(AlertEvent(kind="price", company_id=c.id, trigger_key=day.isoformat(), occurred_at=datetime.combine(day, datetime.min.time()),
                         observed={"date": day.isoformat(), "close": 100.0, "change_pct": 5.0, "threshold": 4.0}, title="SRCTEST up 5%"))
    items = TestClient(api.app).get("/api/alerts").json()["items"]
    src = next(i for i in items if i["company"]["symbol"] == "SRCTEST")["source"]
    assert src["name"] == "Yahoo Finance" and src["url"] == "https://finance.yahoo.com/quote/SRCTEST.NS/history/"


def test_website_dossier_builds_are_capped_per_day(monkeypatch):
    from finn.research import build as research_build
    monkeypatch.setattr(config, "SAMPLE_MODE", False)
    monkeypatch.setattr(config, "MAX_API_BUILDS_PER_DAY", 2)
    monkeypatch.setattr(research_build, "start", lambda symbol, force=False: 1)  # don't actually build
    client = TestClient(api.app)
    assert client.post("/api/research/TCS").status_code == 200
    assert client.post("/api/research/INFY").status_code == 200
    r = client.post("/api/research/HDFCBANK")
    assert r.status_code == 429 and "at most 2 dossiers a day" in r.json()["detail"]


def test_alerts_follow_the_current_threshold():
    from types import SimpleNamespace

    from finn.pipeline import alerts as al
    rules = {"price_pct": 4.0, "volume_mult": 2.0, "price_enabled": True, "volume_enabled": True, "overrides": {7: {"price_pct": 1.0}}}
    small = SimpleNamespace(kind="price", company_id=1, observed={"change_pct": -0.7})
    big = SimpleNamespace(kind="price", company_id=1, observed={"change_pct": 4.9})
    vol = SimpleNamespace(kind="volume", company_id=1, observed={"volume_mult": 2.7})
    own = SimpleNamespace(kind="price", company_id=7, observed={"change_pct": 1.2})  # company-specific 1% threshold
    assert [al.meets_rules(e, rules) for e in (small, big, vol, own)] == [False, True, True, True]
