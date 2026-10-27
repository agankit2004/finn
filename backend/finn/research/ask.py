"""Grounded Q&A over one company's primary documents.

Numbers tables are attached by CODE from extracted metrics (never written by the model); the
model writes the explanation, citing passages (S) and facts (F). Every sentence is grounding-checked.
"""
from __future__ import annotations

import re

from ..ai.llm import generate_json
from ..db import Company
from . import grounding, index, metrics

ASK_PROMPT = """Question about {company} ({symbol}): {question}

Answer for a professional investor using ONLY the sources below (S = passages from the company's
annual report, results filings and earnings-call transcripts; F = numbers from results filings, in
₹ crore, or computed from them). Cite source ids on every statement. Write numbers exactly as they
appear in the sources. If the sources do not answer the question, say so plainly in one statement
with an empty cites list — do not guess and do not use outside knowledge.

Return JSON:
{{"answer": [{{"text": "<one sentence or short bullet>", "cites": ["S2","F4"]}}],   // 2-7 statements
  "takeaways": ["<= 14 words"],                                                     // 0-3
  "follow_ups": ["<a natural next question, <= 10 words>"]}}                         // 2

SOURCES:
{sources}"""

_FIN_Q = re.compile(r"revenue|sales|profit|pat|ebitda|margin|growth|trend|financial|earnings|numbers|quarter|year", re.I)


def ask(s, company: Company, question: str) -> dict:
    question = question.strip()[:500]
    m = metrics.load(s, company.id)
    facts = metrics.facts_table(m, company.is_financial)
    hits = index.retrieve(s, company.id, question, k=8)
    sources, cites = {}, {}
    for i, h in enumerate(hits, 1):
        sid = f"S{i}"
        sources[sid] = h["text"][:2000]
        cites[sid] = {"kind": "passage", "doc_id": h["doc_id"], "page": h["page"], "title": h["doc_title"],
                      "doc_type": h["doc_type"], "period": h["period"], "snippet": h["text"][:280]}
    for f in facts:
        sources[f["id"]] = f["text"]
        cites[f["id"]] = {"kind": "fact", "doc_id": f.get("doc_id"), "page": f.get("page"), "snippet": f["text"]}
    if not hits and not facts:
        return {"answer": [{"text": "FINN has no indexed documents for this company yet. Build the dossier first.",
                            "cites": [], "verified": False, "reason": "no sources"}],
                "takeaways": [], "follow_ups": [], "citations": {}, "table": None}
    out = generate_json("ask", "You are a careful buy-side analyst. JSON only.",
                        ASK_PROMPT.format(company=company.name, symbol=company.nse_symbol, question=question,
                                          sources="\n".join(f"{k}: {v}" for k, v in sources.items())),
                        tier="smart", version="ask-v1", temperature=0.2)
    answer = grounding.check_items(out.get("answer"), sources)
    used = {c for a in answer for c in a["cites"]}
    titles = metrics.doc_titles(s, {cites[c]["doc_id"] for c in used if cites[c].get("doc_id")})
    for c in used:
        d = titles.get(cites[c].get("doc_id"))
        if d:
            cites[c].setdefault("title", d["title"])
            cites[c]["doc_type"] = d["type"]
            cites[c]["period"] = d["period"]
    table = None
    if _FIN_Q.search(question):
        ys = metrics.year_series(m)
        qs = metrics.quarter_series(m, 8)
        series, kind = (ys, "annual") if len(ys) >= 3 else (qs, "quarterly")
        if series:
            table = {"kind": kind, "basis": m["basis"], "columns": [r["label"] for r in series],
                     "rows": [{"metric": lbl, "values": [r.get(k) for r in series]}
                              for k, lbl in (("revenue", "Revenue"), ("ebitda", "EBITDA"), ("pbt", "PBT"), ("pat", "PAT"))
                              if any(r.get(k) is not None for r in series)],
                     "sources": [r.get("source") for r in series]}
    takeaways = []
    for t in [t for t in out.get("takeaways") or [] if isinstance(t, str)][:3]:
        chk = grounding.check_statement(t, list(sources.keys()), sources)
        takeaways.append({"text": t, "verified": chk["verified"]})
    return {"answer": answer, "takeaways": takeaways,
            "follow_ups": [t for t in out.get("follow_ups") or [] if isinstance(t, str)][:3],
            "citations": {k: v for k, v in cites.items() if k in used}, "table": table}
