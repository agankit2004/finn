"""Build a research dossier for ANY NSE ticker from primary documents.

Steps (each recorded on the job so the UI can show progress):
  1. resolve the ticker            -> company row (name, BSE code)
  2. discover documents            -> BSE filings (results, transcripts, annual report) + screener links
  3. extract results filings       -> financial_metrics (Revenue/EBITDA/PBT/PAT, balance sheet, cash flow)
  4. index transcripts + annual report (chunk, keep page numbers)
  5. extract guidance from transcripts; compare with actuals in code
  6. synthesise narrative sections with citations; run grounding checks
  7. cache the dossier (regenerated only when the document set changes)
"""
from __future__ import annotations

import hashlib
import json
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from .. import config
from ..ai.llm import LlmUnavailable, generate_json
from ..db import (Announcement, AnnouncementAnalysis, Chunk, Company, Document, GuidanceItem, Job,
                  ResearchReport, session_scope, utcnow)
from ..pipeline import alerts
from ..pipeline import financials as fin
from ..pipeline.enrich import extract_results, store_metrics
from ..pipeline.ingest import get_or_create_company, refresh_prices, store_announcements
from ..sources import announcements as ann_src
from ..sources import pdfs, screener
from ..sources.http import SourceError
from . import grounding, guidance, index, metrics

log = logging.getLogger("finn.research")
IST = timezone(timedelta(hours=5, minutes=30))
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="research")

MAX_RESULTS = 6       # results filings to extract (each gives ~3 quarter columns)
MAX_TRANSCRIPTS = 4   # last four calls = the brief's "last four quarters"

SYNTH_PROMPT = """Company: {company} ({symbol}). Write for a professional investor.
Use ONLY the sources below. S = excerpts from the company's annual report / earnings-call transcripts.
F = numbers extracted from results filings (₹ crore) or computed from them. G = management guidance with a
verdict computed by code. Every statement must cite at least one source id. Write numbers exactly as they
appear in the sources. No outside knowledge, no news, no price targets, no predictions presented as certain.

Return JSON:
{{
  "business": {{"summary": "<= 45 words: what the company does and how it makes money",
                "points": [{{"text": "<= 30 words", "cites": ["S1"]}}]}},          // up to 4: segments, products, customers, geographies
  "narrative_vs_numbers": [{{"stance": "agrees"|"diverges"|"mixed", "text": "<= 40 words", "cites": ["G1","F3"]}}],  // 2-5
  "bull": [{{"text": "<= 28 words", "cites": ["..."]}}],     // 3
  "bear": [{{"text": "<= 28 words", "cites": ["..."]}}],     // 3
  "open_questions": ["<= 16 words"]                          // 2 questions to ask management next
}}
Use empty lists where sources are insufficient.

SOURCES:
{sources}"""


# --- job plumbing -------------------------------------------------------------------------------
def _job_update(job_id: int, step: str | None = None, progress: float | None = None, log_line: str | None = None,
                status: str | None = None, error: str | None = None) -> None:
    with session_scope() as s:
        j = s.get(Job, job_id)
        if step:
            j.step = step
        if progress is not None:
            j.progress = progress
        if log_line:
            j.log = (j.log or []) + [{"t": utcnow().isoformat(), "msg": log_line}]
        if status:
            j.status = status
        if error:
            j.error = error[:2000]


def start(symbol: str, force: bool = False) -> int:
    with session_scope() as s:
        company = get_or_create_company(s, symbol)  # raises LookupError for unknown tickers
        running = s.execute(select(Job).where(Job.company_id == company.id, Job.kind == "research",
                                              Job.status.in_(["queued", "running"]))).scalar_one_or_none()
        if running and utcnow() - running.updated_at < timedelta(minutes=20):
            return running.id
        j = Job(kind="research", company_id=company.id, status="queued", step="Queued", log=[])
        s.add(j)
        s.flush()
        jid, cid = j.id, company.id
    _pool.submit(_run, jid, cid, force)
    return jid


def _run(job_id: int, company_id: int, force: bool) -> None:
    try:
        _job_update(job_id, status="running", step="Starting", progress=0.02)
        build(job_id, company_id, force)
        _job_update(job_id, status="done", step="Dossier ready", progress=1.0)
    except Exception as e:  # surface everything to the UI rather than dying silently
        log.exception("research job failed")
        _job_update(job_id, status="failed", error=f"{e}\n{traceback.format_exc()[-800:]}", step="Failed")


# --- document discovery ---------------------------------------------------------------------------
def _discover(job_id: int, company: Company) -> dict:
    found = {"results": [], "transcript": [], "annual_report": [], "presentation": []}
    end = datetime.now(IST).date()
    windows = [(end - timedelta(days=d + 95), end - timedelta(days=d)) for d in range(0, 460, 95)]
    raws = []
    errors = []
    for a, b in windows:
        try:
            got, _src = ann_src.fetch_company(company.nse_symbol, company.bse_code, a, b)
            raws.extend(got)
        except SourceError as e:
            errors.append(str(e))
            break
    with session_scope() as s:
        c = s.get(Company, company.id)
        rules = alerts.get_rules(s)
        store_announcements(s, c, raws, rules["categories"], rules)
        rows = list(s.execute(
            select(Announcement, AnnouncementAnalysis).join(AnnouncementAnalysis)
            .where(Announcement.company_id == company.id, Announcement.attachment_url.is_not(None))
            .order_by(Announcement.filed_at.desc())))
        for ann, an in rows:
            item = {"title": ann.subject[:300], "url": ann.attachment_url, "filed_at": ann.filed_at,
                    "via": ann.exchange.lower(), "announcement_id": ann.id}
            subj = ann.subject.lower()
            if an.category == "results" and an.subtype == "results_filing":
                found["results"].append(item)
            elif an.category == "earnings_call" and an.subtype == "transcript":
                found["transcript"].append(item)
            elif an.subtype == "annual_report" or "annual report" in subj:
                found["annual_report"].append(item)
            elif an.category == "results" and an.subtype == "results_presentation":
                found["presentation"].append(item)
    if errors:
        _job_update(job_id, log_line=f"Exchange filings partly unavailable: {errors[0][:160]}")
    if len(found["transcript"]) < 2 or not found["annual_report"]:
        try:
            sc = screener.discover(company.nse_symbol)
            have = {d["url"] for d in found["transcript"]}
            for t in sc["transcripts"]:
                if t["url"] not in have:
                    found["transcript"].append({"title": t["title"], "url": t["url"], "filed_at": t["date"], "via": "screener"})
            if not found["annual_report"]:
                for ar in sc["annual_reports"]:
                    found["annual_report"].append({"title": ar["title"], "url": ar["url"],
                                                   "filed_at": datetime(ar["year"], 9, 1) if ar.get("year") else None,
                                                   "via": "screener"})
            _job_update(job_id, log_line=f"screener.in links: {len(sc['transcripts'])} transcripts, {len(sc['annual_reports'])} annual reports")
        except SourceError as e:
            _job_update(job_id, log_line=f"screener.in unavailable ({str(e)[:100]})")
    for k in found:
        found[k].sort(key=lambda d: d.get("filed_at") or datetime(1900, 1, 1), reverse=True)
    return found


def _upsert_doc(s, company_id: int, d: dict, doc_type: str) -> Document:
    doc = s.execute(select(Document).where(Document.company_id == company_id, Document.url == d["url"])).scalar_one_or_none()
    if not doc:
        doc = Document(company_id=company_id, doc_type=doc_type, title=d["title"], url=d["url"],
                       filed_at=d.get("filed_at"), discovered_via=d.get("via", "bse"), announcement_id=d.get("announcement_id"))
        s.add(doc)
        s.flush()
    return doc


def _index_doc(doc_id: int, path, doc_type: str) -> tuple[int, list[str]]:
    texts = pdfs.page_texts(path)
    pages = index.select_annual_report_pages(texts) if doc_type == "annual_report" else None
    chunks = index.chunk_pages(texts, pages)
    with session_scope() as s:
        doc = s.get(Document, doc_id)
        doc.page_count = len(texts)
        if pdfs.is_scanned(texts):
            doc.parse_status = "scanned"
            return 0, texts
        s.execute(delete(Chunk).where(Chunk.document_id == doc_id))
        for c in chunks:
            s.add(Chunk(document_id=doc_id, company_id=doc.company_id, **c))
        doc.parse_status = "parsed"
    return len(chunks), texts


# --- main build -----------------------------------------------------------------------------------
def build(job_id: int, company_id: int, force: bool = False) -> None:
    with session_scope() as s:
        company = s.get(Company, company_id)
        name, symbol, is_fin = company.name, company.nse_symbol, company.is_financial
    if not config.llm_enabled():
        _job_update(job_id, log_line="No GEMINI_API_KEY: documents will be listed but not analysed")

    _job_update(job_id, step="Fetching prices", progress=0.05)
    try:
        refresh_prices([symbol], with_stats=True)
    except Exception as e:
        _job_update(job_id, log_line=f"Price fetch failed: {str(e)[:120]}")

    _job_update(job_id, step="Finding filings, transcripts and annual reports", progress=0.1)
    found = _discover(job_id, company)
    _job_update(job_id, log_line=(f"Found {len(found['results'])} results filings, {len(found['transcript'])} transcripts, "
                                  f"{len(found['annual_report'])} annual reports"))

    if not any(found.values()):
        raise RuntimeError(
            "No filings, transcripts or annual reports could be found for this company. The exchange and "
            "screener.in may be blocking requests from this machine right now (see Settings → Data sources), "
            "or the company has no BSE filings. Try again later.")

    # 3. results filings -> metrics (dedupe by quarter; newest filing wins)
    results_docs = []
    seen_titles = set()
    for d in found["results"]:
        key = d["title"].lower()[:80]
        if key in seen_titles:
            continue
        seen_titles.add(key)
        results_docs.append(d)
        if len(results_docs) >= MAX_RESULTS:
            break
    for i, d in enumerate(results_docs):
        _job_update(job_id, step=f"Reading results filing {i + 1}/{len(results_docs)}",
                    progress=0.15 + 0.35 * i / max(1, len(results_docs)))
        try:
            path, sha = pdfs.download(d["url"])
            with session_scope() as s:
                doc = _upsert_doc(s, company_id, d, "results")
                doc.sha256 = sha
                doc_id = doc.id
            if not config.llm_enabled():
                continue
            card = extract_results(path, is_fin)
            if card.get("kind") != "results" or card.get("error"):
                with session_scope() as s:
                    s.get(Document, doc_id).parse_status = "failed" if card.get("error") else "parsed"
                _job_update(job_id, log_line=f"Skipped '{d['title'][:60]}': {card.get('error') or 'not a results statement'}")
                continue
            with session_scope() as s:
                doc = s.get(Document, doc_id)
                doc.period_label = card.get("quarter")
                doc.parse_status = "parsed"
                doc.extracted = {k: card.get(k) for k in ("quarter", "period_end", "basis", "segments", "checks")}
                store_metrics(s, s.get(Company, company_id), doc, card, d.get("filed_at"))
        except (SourceError, LlmUnavailable, OSError, ValueError) as e:
            _job_update(job_id, log_line=f"Results filing failed: {str(e)[:140]}")

    # 4-5. transcripts: index + guidance
    transcripts = found["transcript"][:MAX_TRANSCRIPTS]
    for i, d in enumerate(transcripts):
        _job_update(job_id, step=f"Reading concall transcript {i + 1}/{len(transcripts)}",
                    progress=0.5 + 0.2 * i / max(1, len(transcripts)))
        try:
            path, sha = pdfs.download(d["url"])
            with session_scope() as s:
                doc = _upsert_doc(s, company_id, d, "transcript")
                doc.sha256 = sha
                doc_id = doc.id
            n, texts = _index_doc(doc_id, path, "transcript")
            if n == 0 or not config.llm_enabled():
                continue
            g = guidance.extract(name, texts)
            with session_scope() as s:
                doc = s.get(Document, doc_id)
                if g.get("call_quarter"):
                    doc.period_label = g["call_quarter"]
                s.execute(delete(GuidanceItem).where(GuidanceItem.document_id == doc_id))
                for it in g["items"]:
                    s.add(GuidanceItem(company_id=company_id, document_id=doc_id, page=it.get("page"),
                                       made_in=g.get("call_quarter"), quote=it["quote"][:600],
                                       metric=it.get("metric") or "other", target_low=it.get("target_low"),
                                       target_high=it.get("target_high"), unit=it.get("unit"),
                                       target_period=it.get("target_period"),
                                       assessment=None if it.get("quote_verified") else "quote not found verbatim in transcript"))
        except (SourceError, LlmUnavailable, OSError, ValueError) as e:
            _job_update(job_id, log_line=f"Transcript failed: {str(e)[:140]}")

    # annual report (latest only)
    if found["annual_report"]:
        d = found["annual_report"][0]
        _job_update(job_id, step="Indexing the latest annual report", progress=0.72)
        try:
            path, sha = pdfs.download(d["url"])
            with session_scope() as s:
                doc = _upsert_doc(s, company_id, d, "annual_report")
                doc.sha256 = sha
                doc_id = doc.id
            n, _ = _index_doc(doc_id, path, "annual_report")
            _job_update(job_id, log_line=f"Annual report indexed ({n} passages from the business & risk sections)")
        except (SourceError, OSError, ValueError) as e:
            _job_update(job_id, log_line=f"Annual report failed: {str(e)[:140]}")

    _job_update(job_id, step="Comparing guidance with results and writing the dossier", progress=0.8)
    compose(company_id, job_id)


def _doc_set_hash(s, company_id: int) -> str:
    docs = list(s.execute(select(Document.id, Document.sha256).where(Document.company_id == company_id)))
    return hashlib.sha256(json.dumps(sorted([d[0], d[1]] for d in docs)).encode()).hexdigest()


def compose(company_id: int, job_id: int | None = None, synth_override: dict | None = None) -> dict:
    """Assemble the dossier. Numbers come from code; prose comes from one 'smart' call, then grounding checks."""
    with session_scope() as s:
        company = s.get(Company, company_id)
        m = metrics.load(s, company_id)
        is_fin = company.is_financial
        qs = metrics.quarter_series(m, 8)
        ys = metrics.year_series(m)
        snap = metrics.snapshot(m, is_fin)
        bs = metrics.balance_sheet(m, is_fin)
        cq = metrics.cash_quality(m)
        facts = metrics.facts_table(m, is_fin)
        docs = list(s.execute(select(Document).where(Document.company_id == company_id).order_by(Document.filed_at.desc())).scalars())

        # Guidance ledger: verdicts by code for quantitative items.
        g_rows = list(s.execute(select(GuidanceItem).where(GuidanceItem.company_id == company_id)).scalars())
        ledger, qualitative = [], []
        for g in g_rows:
            period = guidance.parse_period(g.target_period)
            act = guidance.actual_for(m, g.metric, period) if period else None
            v, note = guidance.verdict({"metric": g.metric, "target_low": g.target_low, "target_high": g.target_high, "unit": g.unit}, act)
            if g.metric in ("other", "volume_growth") or (v == "unverifiable"):
                qualitative.append(g)
            g.verdict, g.actual_value = v, act["value"] if act else None
            g.actual_basis = act["basis"] if act else None
            g.assessment_method = "code" if v not in ("pending", "unverifiable") else None
            if note:
                g.assessment = note
        latest_q = qs[-1]["label"] if qs else None

        # Sources for the synthesis call.
        sources: dict[str, str] = {}
        cite_meta: dict[str, dict] = {}
        chunk_hits = []
        for q in ("business overview segments products customers revenue mix", "strategy outlook growth drivers"):
            chunk_hits += index.retrieve(s, company_id, q, k=3, doc_types=["annual_report"]) or []
        for q in ("guidance outlook growth margin target", "capex expansion capacity investment",
                  "challenges headwinds pressure decline risk", "demand volume pricing market share"):
            chunk_hits += index.retrieve(s, company_id, q, k=2, doc_types=["transcript"]) or []
        if not any(h["doc_type"] == "annual_report" for h in chunk_hits):
            chunk_hits += index.retrieve(s, company_id, "business segments products customers", k=3) or []
        seen = set()
        n = 0
        for h in chunk_hits:
            if h["chunk_id"] in seen:
                continue
            seen.add(h["chunk_id"])
            n += 1
            sid = f"S{n}"
            sources[sid] = h["text"][:2200]
            cite_meta[sid] = {"kind": "passage", "doc_id": h["doc_id"], "page": h["page"], "title": h["doc_title"],
                              "doc_type": h["doc_type"], "snippet": h["text"][:280]}
        for f in facts:
            sources[f["id"]] = f["text"]
            cite_meta[f["id"]] = {"kind": "fact", "doc_id": f.get("doc_id"), "page": f.get("page"), "snippet": f["text"]}
        gi = 0
        g_by_id = {}
        for g in g_rows:
            gi += 1
            gid = f"G{gi}"
            g_by_id[g.id] = gid
            txt = f"Guidance ({g.made_in or 'call'}): \"{g.quote}\" — verdict: {g.verdict}" + (f"; {g.assessment}" if g.assessment else "")
            sources[gid] = txt
            cite_meta[gid] = {"kind": "guidance", "doc_id": g.document_id, "page": g.page, "snippet": g.quote[:280]}

        # Qualitative guidance: one model call for all of them.
        if qualitative and config.llm_enabled():
            try:
                res = guidance.assess_qualitative(
                    [{"id": g.id, "quote": g.quote, "made_in": g.made_in} for g in qualitative],
                    {k: v for k, v in sources.items() if not k.startswith("G")})
                for g in qualitative:
                    r = res.get(g.id)
                    if r:
                        chk = grounding.check_statement(r.get("text", ""), r.get("cites", []), sources)
                        g.verdict = {"delivered": "met", "not_delivered": "missed", "in_progress": "on_track"}.get(r.get("verdict"), "unclear")
                        g.assessment = r.get("text")
                        g.assessment_method = "llm"
                        g.actual_basis = json.dumps({"cites": chk["cites"], "verified": chk["verified"]})
            except LlmUnavailable as e:
                if job_id:
                    _job_update(job_id, log_line=f"Qualitative guidance check skipped: {str(e)[:100]}")

        synth = synth_override or {}
        if synth_override is None and config.llm_enabled() and (chunk_hits or facts):
            src_text = "\n".join(f"{k}: {v}" for k, v in sources.items())
            try:
                synth = generate_json("dossier", "You are a careful buy-side analyst. JSON only.",
                                      SYNTH_PROMPT.format(company=company.name, symbol=company.nse_symbol, sources=src_text),
                                      tier="smart", version="dossier-v1", temperature=0.2)
            except LlmUnavailable as e:
                if job_id:
                    _job_update(job_id, log_line=f"AI synthesis unavailable: {str(e)[:120]}")

        business = synth.get("business") or {}
        segments = []
        for d in docs:
            if d.doc_type == "results" and d.extracted and d.extracted.get("segments"):
                segments = [{**x, "doc_id": d.id, "period": d.extracted.get("quarter")} for x in d.extracted["segments"]]
                break

        ledger = []
        for g in sorted(g_rows, key=lambda x: (x.made_in or "", x.id)):
            meta = {}
            if g.assessment_method == "llm" and g.actual_basis:
                try:
                    meta = json.loads(g.actual_basis)
                except ValueError:
                    meta = {}
            ledger.append({
                "id": g_by_id.get(g.id), "made_in": g.made_in, "quote": g.quote, "doc_id": g.document_id, "page": g.page,
                "metric": g.metric, "target_low": g.target_low, "target_high": g.target_high, "unit": g.unit,
                "target_period": g.target_period, "verdict": g.verdict or "pending",
                "actual_value": g.actual_value,
                "actual_basis": None if g.assessment_method == "llm" else g.actual_basis,
                "assessment": g.assessment, "assessment_method": g.assessment_method,
                "cites": meta.get("cites", []), "verified": meta.get("verified", g.assessment_method == "code"),
            })
        tally = {}
        for row in ledger:
            tally[row["verdict"]] = tally.get(row["verdict"], 0) + 1

        content = {
            "company": {"symbol": company.nse_symbol, "name": company.name, "sector": company.sector, "is_financial": is_fin},
            "generated_at": utcnow().isoformat() + "Z",
            "latest_quarter": latest_q,
            "basis": m["basis"],
            "coverage": {
                "results_filings": sum(1 for d in docs if d.doc_type == "results" and d.parse_status == "parsed"),
                "transcripts": sum(1 for d in docs if d.doc_type == "transcript" and d.parse_status == "parsed"),
                "annual_report": any(d.doc_type == "annual_report" and d.parse_status == "parsed" for d in docs),
                "llm": config.llm_enabled(),
            },
            "documents": [{"id": d.id, "type": d.doc_type, "title": d.title, "period": d.period_label,
                           "filed_at": d.filed_at.isoformat() + "Z" if d.filed_at else None, "pages": d.page_count,
                           "status": d.parse_status, "via": d.discovered_via, "source_url": d.url} for d in docs],
            "business": {
                "summary": business.get("summary"),
                "points": grounding.check_items(business.get("points"), sources),
                "segments": segments,
            },
            "snapshot": snap,
            "trajectory": {"quarters": qs, "years": ys, "observations": metrics.trajectory_observations(qs)},
            "balance_sheet": bs,
            "cash_quality": cq,
            "guidance": {"items": ledger, "tally": tally},
            "narrative": grounding.check_items(synth.get("narrative_vs_numbers"), sources),
            "bull": grounding.check_items(synth.get("bull"), sources),
            "bear": grounding.check_items(synth.get("bear"), sources),
            "open_questions": [q for q in (synth.get("open_questions") or []) if isinstance(q, str)][:3],
            "citations": cite_meta,
        }
        doc_ids = {v["doc_id"] for v in cite_meta.values() if v.get("doc_id")}
        titles = metrics.doc_titles(s, doc_ids)
        for v in cite_meta.values():
            if v.get("doc_id") in titles:
                v.setdefault("title", titles[v["doc_id"]]["title"])
                v["doc_type"] = titles[v["doc_id"]]["type"]
                v["period"] = titles[v["doc_id"]]["period"]

        rep = s.execute(select(ResearchReport).where(ResearchReport.company_id == company_id)).scalar_one_or_none()
        if not rep:
            rep = ResearchReport(company_id=company_id, content=content, doc_set_hash="")
            s.add(rep)
        rep.content, rep.doc_set_hash, rep.created_at = content, _doc_set_hash(s, company_id), utcnow()
        return content
