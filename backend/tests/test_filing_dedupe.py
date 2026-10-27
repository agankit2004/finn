from datetime import datetime

from finn.db import Announcement, Company, init_db, session_scope
from finn.pipeline import alerts, ingest
from finn.sources.announcements import RawAnnouncement

init_db()


def test_same_bse_document_from_api_and_screener_is_stored_once():
    api_item = RawAnnouncement(exchange="BSE", source_id="12345", filed_at_utc=datetime(2026, 10, 14, 10, 25),
                               subject="Earnings Call Transcript", headline=None, category="Company Update",
                               subcategory=None, attachment_url="https://www.bseindia.com/xml-data/corpfiling/AttachLive/7dc14216-f892.pdf")
    via_screener = RawAnnouncement(exchange="BSE", source_id="pdf:7dc14216-f892.pdf", filed_at_utc=datetime(2026, 10, 14, 10, 25),
                                   subject="Announcement under Regulation 30 (LODR)-Earnings Call Transcript", headline=None,
                                   category=None, subcategory=None, raw={"via": "screener"},
                                   attachment_url="https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=7dc14216-f892.pdf")
    with session_scope() as s:
        alerts.ensure_default_rules(s)
        c = Company(nse_symbol="DUPTEST", name="Dup Test Ltd")
        s.add(c)
        s.flush()
        rules = alerts.get_rules(s)
        assert len(ingest.store_announcements(s, c, [api_item], rules["categories"], rules)) == 1
        assert len(ingest.store_announcements(s, c, [via_screener], rules["categories"], rules)) == 0
        assert s.query(Announcement).filter(Announcement.company_id == c.id).count() == 1
