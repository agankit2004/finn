"""Parsing tests for exchange and screener responses, using recorded-shape fixtures (no network)."""
import os
import tempfile

os.environ.setdefault("FINN_DATA_DIR", tempfile.mkdtemp(prefix="finn-test-"))

from datetime import date  # noqa: E402

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


SCREENER_HTML = """
<section id="documents"><div class="documents">
 <div><h3>Annual reports</h3><ul>
   <li><a href="https://www.bseindia.com/bseplus/AnnualReport/532540/ar2026.pdf">Financial Year 2026<div>from bse</div></a></li>
 </ul></div>
 <div><h3>Concalls</h3><ul>
   <li><div>Oct 2026</div><a class="concall-link" href="https://www.bseindia.com/xml-data/corpfiling/AttachLive/t1.pdf">Transcript</a>
       <a href="https://example.com/ppt.pdf">PPT</a></li>
   <li><div>Jul 2026</div><a class="concall-link" href="https://www.bseindia.com/xml-data/corpfiling/AttachLive/t0.pdf">Transcript</a></li>
 </ul></div>
</div></section>"""


def test_screener_parsing(monkeypatch):
    def fake_get(client, url, params=None, headers=None, retries=3):
        return httpx.Response(200, text=SCREENER_HTML, request=httpx.Request("GET", url))

    monkeypatch.setattr(screener, "get", fake_get)
    out = screener.discover("TCS")
    assert len(out["annual_reports"]) == 1 and out["annual_reports"][0]["year"] == 2026
    assert [t["url"].rsplit("/", 1)[1] for t in out["transcripts"]] == ["t1.pdf", "t0.pdf"]
    assert out["transcripts"][0]["date"].month == 10
