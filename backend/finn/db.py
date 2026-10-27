"""Database models. Portable between SQLite (local) and PostgreSQL (deployment).

All timestamps are stored as naive UTC. Conversion to IST happens at the edges.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from . import config


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    nse_symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    bse_code: Mapped[str | None] = mapped_column(String(12), index=True)
    isin: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(200))
    sector: Mapped[str | None] = mapped_column(String(80))
    industry: Mapped[str | None] = mapped_column(String(120))
    is_financial: Mapped[bool] = mapped_column(Boolean, default=False)  # bank / NBFC / insurer
    market_cap_cr: Mapped[float | None] = mapped_column(Float)
    pe: Mapped[float | None] = mapped_column(Float)
    dividend_yield: Mapped[float | None] = mapped_column(Float)
    stats_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(16), default="live")  # live | sample


class Holding(Base):
    __tablename__ = "holdings"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), unique=True)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    company: Mapped[Company] = relationship()


class Price(Base):
    __tablename__ = "prices_daily"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16), default="yahoo")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = (UniqueConstraint("exchange", "source_id", name="uq_ann_source"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    exchange: Mapped[str] = mapped_column(String(8))  # BSE | NSE | SAMPLE
    source_id: Mapped[str] = mapped_column(String(64))
    filed_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    subject: Mapped[str] = mapped_column(Text)
    headline: Mapped[str | None] = mapped_column(Text)
    exchange_category: Mapped[str | None] = mapped_column(String(120))
    exchange_subcategory: Mapped[str | None] = mapped_column(String(160))
    attachment_url: Mapped[str | None] = mapped_column(Text)
    attachment_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    raw: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    company: Mapped[Company] = relationship()
    analysis: Mapped["AnnouncementAnalysis | None"] = relationship(
        back_populates="announcement", uselist=False
    )


class AnnouncementAnalysis(Base):
    __tablename__ = "announcement_analysis"
    announcement_id: Mapped[int] = mapped_column(ForeignKey("announcements.id"), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    subtype: Mapped[str | None] = mapped_column(String(48))
    category_method: Mapped[str] = mapped_column(String(8))  # rule | llm
    importance: Mapped[float] = mapped_column(Float, index=True)
    importance_reasons: Mapped[list | None] = mapped_column(JSON)
    summary: Mapped[str | None] = mapped_column(Text)
    structured: Mapped[dict | None] = mapped_column(JSON)  # results table / people / key facts
    enrich_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|done|skipped|failed|needs_key
    enrich_error: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    announcement: Mapped[Announcement] = relationship(back_populates="analysis")


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))  # null = global
    kind: Mapped[str] = mapped_column(String(16))  # price_pct | volume_mult | category
    threshold: Mapped[float | None] = mapped_column(Float)
    categories: Mapped[list | None] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (UniqueConstraint("kind", "company_id", "trigger_key", name="uq_alert_once"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # price | volume | announcement
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    trigger_key: Mapped[str] = mapped_column(String(64))  # date or announcement id
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    observed: Mapped[dict | None] = mapped_column(JSON)
    title: Mapped[str] = mapped_column(Text)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)
    announcement_id: Mapped[int | None] = mapped_column(ForeignKey("announcements.id"))
    company: Mapped[Company] = relationship()


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("company_id", "url", name="uq_doc_url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(24))  # results | transcript | annual_report | presentation
    title: Mapped[str] = mapped_column(Text)
    period_label: Mapped[str | None] = mapped_column(String(32))
    filed_at: Mapped[datetime | None] = mapped_column(DateTime)
    url: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64))
    page_count: Mapped[int | None] = mapped_column(Integer)
    parse_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|parsed|failed|scanned
    discovered_via: Mapped[str] = mapped_column(String(16))  # bse | nse | screener | sample
    extracted: Mapped[dict | None] = mapped_column(JSON)
    announcement_id: Mapped[int | None] = mapped_column(ForeignKey("announcements.id"))


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    document: Mapped[Document] = relationship()


class FinancialMetric(Base):
    __tablename__ = "financial_metrics"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "period_end", "period_type", "basis", "metric", name="uq_metric"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    period_end: Mapped[date] = mapped_column(Date)
    period_type: Mapped[str] = mapped_column(String(4))  # Q | H | FY
    basis: Mapped[str] = mapped_column(String(16))  # consolidated | standalone
    metric: Mapped[str] = mapped_column(String(48))
    value_cr: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(12))  # extracted | computed
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    page: Mapped[int | None] = mapped_column(Integer)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime)


class GuidanceItem(Base):
    __tablename__ = "guidance_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    page: Mapped[int | None] = mapped_column(Integer)
    made_in: Mapped[str | None] = mapped_column(String(32))  # e.g. Q1 FY27 call
    quote: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(String(32))  # revenue_growth | ebitda_margin | pat_growth | capex | other
    target_low: Mapped[float | None] = mapped_column(Float)
    target_high: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(16))  # pct | cr
    target_period: Mapped[str | None] = mapped_column(String(16))  # FY27 | Q3FY27
    verdict: Mapped[str | None] = mapped_column(String(16))  # met | missed | partly | on_track | behind | pending | unverifiable
    actual_value: Mapped[float | None] = mapped_column(Float)
    actual_basis: Mapped[str | None] = mapped_column(Text)
    assessment: Mapped[str | None] = mapped_column(Text)
    assessment_method: Mapped[str | None] = mapped_column(String(8))  # code | llm


class ResearchReport(Base):
    __tablename__ = "research_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), unique=True)
    content: Mapped[dict] = mapped_column(JSON)
    doc_set_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued|running|done|failed
    step: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[float] = mapped_column(Float, default=0)
    log: Mapped[list | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class LlmCall(Base):
    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    purpose: Mapped[str] = mapped_column(String(48))
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LlmCache(Base):
    __tablename__ = "llm_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(24))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(12), default="running")  # running|ok|partial|failed
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str | None] = mapped_column(Text)


class NewsItem(Base):
    """A news headline (secondary source). Push side only; never used as research evidence."""
    __tablename__ = "news_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(120))
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    story_id: Mapped[int | None] = mapped_column(Integer, index=True)  # first item of the same story
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    company: Mapped[Company] = relationship()


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | None] = mapped_column(JSON)


_connect_args = {"check_same_thread": False, "timeout": 30} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)

if config.DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


@contextmanager
def session_scope():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_setting(s, key: str, default=None):
    row = s.get(Setting, key)
    return row.value if row and row.value is not None else default


def set_setting(s, key: str, value) -> None:
    row = s.get(Setting, key)
    if row:
        row.value = value
    else:
        s.add(Setting(key=key, value=value))
