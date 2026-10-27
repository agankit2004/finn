"""Parsing tests for exchange and screener responses, using recorded-shape fixtures (no network)."""
import os
import tempfile

os.environ.setdefault("FINN_DATA_DIR", tempfile.mkdtemp(prefix="finn-test-"))

from datetime import date, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402

from finn.sources import announcements as ann_src  # noqa: E402
from finn.sources import screener  # noqa: E402

BSE_FIXTURE = {
    "Table": [
        {"NEWSID": "abc-123", "SCRIP_CD": 532540, "NEWSSUB": "Outcome of Board Meeting - Financial Results",
         "NEWS_DT": "2026-10-09T16:12:44.38", "ATTACHMENTNAME": "d1f2.pdf", "HEADLINE": "Results for Q2",
         "CATEGORYNAME": "Result", "SUBCATNAME": "Financial Results", "PDFFLAG": 0},
        {"NEWSID": "abc-124", "SCRIP_CD": 532540, "NEWSSUB": "Closure of Trading Window",
         "NEWS_DT": "2026-09-25T10:00:00", "ATTACHMENTNAME": "", "CATEGORYNAME": "Company Update"},
    ],
    "Table1": [{"ROWCNT": 2}],
}


def test_bse_parsing(monkeypatch):
    def fake_get(client, url, params=None, headers=None, retries=3):
        return httpx.Response(200, json=BSE_FIXTURE, request=httpx.Request("GET", url))

    monkeypatch.setattr(ann_src, "get", fake_get)
    items = ann_src.fetch_bse("532540", date(2026, 9, 1), date(2026, 10, 10))
    assert len(items) == 2
    a = items[0]
    assert a.source_id == "abc-123" and a.exchange == "BSE"
    assert a.attachment_url.endswith("/AttachLive/d1f2.pdf")
    assert a.filed_at_utc.hour == 10 and a.filed_at_utc.minute == 42  # 16:12 IST -> 10:42 UTC
    assert items[1].attachment_url is None


SCREENER_HTML = (Path(__file__).parent / "fixtures" / "screener_tcs.html").read_text()  # real page, trimmed


def test_screener_parsing_real_page(monkeypatch):
    def fake_get(client, url, params=None, headers=None, retries=3):
        return httpx.Response(200, text=SCREENER_HTML, request=httpx.Request("GET", url))

    monkeypatch.setattr(screener, "get", fake_get)
    out = screener.discover("TCS")
    # 5 latest filings: the filing's own title (screener's summary dropped), exact time, BSE document
    assert len(out["recent"]) == 5
    first = out["recent"][0]
    assert first["title"] == "Press Release - TCS Bancs For Treasury Marks Its Entry Into Sri Lanka With Indian Bank"
    assert first["filed_at_utc"] == datetime(2026, 10, 19, 6, 0, 41)  # 11:30:41 IST
    assert first["url"].startswith("https://www.bseindia.com/") and first["url"].endswith(".pdf")
    # transcripts: one per call month, newest first
    titles = [t["title"] for t in out["transcripts"]]
    assert titles[0] == "Concall transcript Oct 2026" and len(titles) == len(set(titles))
    # per-quarter links to results filings, newest quarter first
    assert out["quarters"][0]["period_end"] == date(2026, 9, 30)
    assert out["annual_reports"][0]["year"] == 2026


def test_screener_fallback_becomes_bse_filings(monkeypatch):
    monkeypatch.setattr(screener, "page", lambda symbol: SCREENER_HTML)
    for src in ("BSE", "NSE"):  # both exchange APIs paused, as when they block us
        monkeypatch.setitem(ann_src._breaker, src, {"fails": 3, "until": float("inf")})
    monkeypatch.setitem(ann_src._breaker, "SCREENER", {"fails": 0, "until": 0.0})
    items, used = ann_src.fetch_company("TCS", "532540", date(2026, 10, 1), date(2026, 10, 27))
    assert used == "BSE via screener.in" and len(items) == 5
    assert all(i.exchange == "BSE" and i.source_id.startswith("pdf:") and i.raw == {"via": "screener"} for i in items)


NEWS_RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Infosys shares jump after Q2 beat - Sample Times</title><link>https://news.example/a</link>
 <guid>a</guid><pubDate>Mon, 26 Oct 2026 10:30:00 GMT</pubDate><source url="https://st.example">Sample Times</source></item>
<item><title>Infosys Q2 beat sends shares jumping - Daily Sample</title><link>https://news.example/b</link>
 <guid>b</guid><pubDate>Mon, 26 Oct 2026 11:00:00 GMT</pubDate><source url="https://ds.example">Daily Sample</source></item>
<item><title>Global tech stocks slide on rates - Wire</title><link>https://news.example/c</link>
 <guid>c</guid><pubDate>Mon, 26 Oct 2026 12:00:00 GMT</pubDate><source url="https://w.example">Wire</source></item>
</channel></rss>"""


def test_news_parsing_relevance_and_grouping():
    from finn.sources import news

    items = news.parse(NEWS_RSS)
    assert items[0].title == "Infosys shares jump after Q2 beat" and items[0].source == "Sample Times"
    assert items[0].published_utc.hour == 10
    rel = [h for h in items if news.relevant(h, "INFY", "Infosys Ltd")]
    assert len(rel) == 2  # the generic tech headline is dropped
    assert news.same_story(news.title_key(rel[0].title), news.title_key(rel[1].title))
    assert news.short_name("Dixon Technologies (India) Ltd") == "Dixon Technologies"
    assert news.short_name("Larsen & Toubro Ltd") == "Larsen & Toubro"
