"""Chunking and retrieval over a company's primary documents.

Retrieval is BM25 keyword search, computed in-process per company. For a few hundred chunks per
company this is fast, free, deterministic, and good at the exact terms financial questions use
("EBITDA margin", "capex", "order book"). Embeddings/pgvector are the documented upgrade path
if recall becomes a problem; they are not needed at this scale.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from sqlalchemy import select

from ..db import Chunk, Document

CHUNK_CHARS = 3200
_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")
STOP = set("""a an the and or of to in on for by with at from as is are was were be been being this that these
those it its we our you your they their he she his her them us i not no but if then than so such which who whom
what when where how all any each other more most some can could will would shall should may might must also into
over under about after before during between up down out off again further once here there very just only own same
too s t ltd limited company""".split())

AR_PRIORITY = re.compile(
    r"management discussion|business overview|our business|segment|chairman|managing director'?s? (message|letter)|"
    r"outlook|strategy|risks? (and|&) (concerns|mitigation)|opportunit|capacity|capex|capital expenditure|"
    r"borrowings|contingent liabilit|related party|key performance|revenue (mix|by)|market share|guidance|"
    r"principal (business )?activit|products|customers|order book", re.I)


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOP and len(t) > 1]


def select_annual_report_pages(texts: list[str], max_pages: int = 90) -> list[int]:
    """Annual reports run 250-450 pages; index the pages that carry business and risk narrative."""
    scored = []
    for i, t in enumerate(texts):
        hits = len(AR_PRIORITY.findall(t[:6000]))
        if hits:
            scored.append((hits, i))
    keep = {i for _, i in sorted(scored, reverse=True)[:max_pages]}
    keep |= set(range(min(4, len(texts))))  # title/contents pages help orient
    return sorted(keep)


def chunk_pages(texts: list[str], pages: list[int] | None = None) -> list[dict]:
    """Split pages into ~CHUNK_CHARS chunks without crossing more than one page boundary."""
    pages = pages if pages is not None else list(range(len(texts)))
    out, buf, start, last = [], "", None, None
    section = None
    for i in pages:
        t = re.sub(r"[ \t]+", " ", texts[i]).strip()
        if not t:
            continue
        for line in t.splitlines()[:6]:
            ls = line.strip()
            if 6 <= len(ls) <= 70 and (ls.isupper() or ls.istitle()) and not re.search(r"\d{3,}", ls):
                section = ls
                break
        paras = [p for p in re.split(r"\n\s*\n|\n(?=[A-Z•\-])", t) if p.strip()]
        for p in paras:
            p = " ".join(p.split())
            if start is None:
                start = i
            if len(buf) + len(p) > CHUNK_CHARS and buf:
                out.append({"page_start": start + 1, "page_end": (last if last is not None else i) + 1, "section": section, "text": buf.strip()})
                buf, start = "", i
            buf += p + "\n"
            last = i
        if start is not None and last is not None and last - start >= 1 and buf:
            out.append({"page_start": start + 1, "page_end": last + 1, "section": section, "text": buf.strip()})
            buf, start = "", None
    if buf.strip():
        out.append({"page_start": (start or 0) + 1, "page_end": (last or 0) + 1, "section": section, "text": buf.strip()})
    return [c for c in out if len(c["text"]) > 120]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = docs
        self.n = len(docs)
        self.avgdl = (sum(len(d) for d in docs) / self.n) if self.n else 0
        self.tf = [Counter(d) for d in docs]
        df = Counter()
        for d in docs:
            df.update(set(d))
        self.idf = {t: math.log(1 + (self.n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, q: list[str]) -> list[float]:
        out = []
        for tf, d in zip(self.tf, self.docs):
            s, dl = 0.0, len(d)
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf.get(t, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1)))
            out.append(s)
        return out


def retrieve(s, company_id: int, query: str, k: int = 8, doc_types: list[str] | None = None) -> list[dict]:
    q = select(Chunk, Document).join(Document, Document.id == Chunk.document_id).where(Chunk.company_id == company_id)
    if doc_types:
        q = q.where(Document.doc_type.in_(doc_types))
    rows = list(s.execute(q))
    if not rows:
        return []
    bm = BM25([tokens((c.section or "") + " " + c.text) for c, _ in rows])
    sc = bm.scores(tokens(query))
    # Mild recency preference: newer documents win ties.
    ranked = sorted(zip(sc, rows), key=lambda x: (x[0], x[1][1].filed_at or 0), reverse=True)
    out = []
    for score, (c, d) in ranked[:k]:
        if score <= 0:
            break
        out.append({"chunk_id": c.id, "doc_id": d.id, "doc_type": d.doc_type, "doc_title": d.title,
                    "period": d.period_label, "page": c.page_start, "page_end": c.page_end, "text": c.text, "score": round(score, 2)})
    return out
