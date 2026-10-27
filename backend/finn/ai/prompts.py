"""Prompt templates. Every prompt forbids outside knowledge and demands page references."""

GROUNDING = (
    "You are FINN's extraction engine for Indian listed-company filings. Use ONLY the document "
    "provided. Never use outside knowledge. If a value is not printed in the document, return null; "
    "never estimate, infer or compute it. Copy numbers exactly as printed (no rounding), using a minus "
    "sign for negatives or values shown in brackets. Respond with JSON only."
)

RESULTS_PROMPT = """This excerpt of a quarterly/annual results filing contains {n} pages, numbered 1..{n}.
Extract the financial results table. Prefer the CONSOLIDATED profit-and-loss statement; if these pages
have no consolidated P&L table (even if a consolidated balance sheet or cash flow is present), extract the
STANDALONE P&L and set basis to "standalone". is_financial_results is true whenever any quarterly
profit-and-loss statement (consolidated or standalone) is present.

Return JSON:
{{
  "is_financial_results": true|false,          // false if this is not an actual results statement
  "basis": "consolidated"|"standalone",
  "unit": "crore"|"lakh"|"million"|"thousand"|"rupees",   // as stated in the table header
  "entity_type": "non_financial"|"bank"|"nbfc"|"insurance",
  "periods": [                                  // one entry per numeric column in the P&L table
    {{
      "period_end": "YYYY-MM-DD", "months": 3|6|9|12, "audited": true|false, "page": <int>,
      "revenue_from_operations": <num|null>, "other_income": <num|null>, "total_income": <num|null>,
      "total_expenses": <num|null>, "finance_costs": <num|null>,
      "depreciation": <num|null>,              // depreciation and amortisation expense
      "exceptional_items": <num|null>,         // signed as it affects profit: gain +, loss -
      "pbt": <num|null>,                       // profit before tax (after exceptional items)
      "tax_expense": <num|null>, "pat": <num|null>,   // net profit for the period
      "pat_owners": <num|null>,                // attributable to owners of the parent, if shown
      "interest_earned": <num|null>, "interest_expended": <num|null>,   // banks / NBFCs
      "operating_profit": <num|null>, "provisions": <num|null>          // banks: pre-provision op. profit
    }}
  ],
  "segments": [ {{"name": "...", "revenue": <num>, "period_end": "YYYY-MM-DD", "months": 3, "page": <int>}} ],
  "balance_sheet": null | {{
      "as_of": "YYYY-MM-DD", "page": <int>, "total_equity": <num|null>,
      "borrowings_non_current": <num|null>, "borrowings_current": <num|null>,
      "cash_and_equivalents": <num|null>, "other_bank_balances": <num|null>, "current_investments": <num|null>,
      "trade_receivables": <num|null>, "inventories": <num|null>, "trade_payables": <num|null>,
      "total_assets": <num|null> }},
  "cash_flow": null | {{
      "period_end": "YYYY-MM-DD", "months": 6|12, "page": <int>,
      "cfo": <num|null>,                       // net cash from operating activities
      "capex": <num|null> }},                  // purchase of PP&E + intangibles, as a POSITIVE number
  "notes": "<one short line on anything unusual, e.g. restated figures, or null>"
}}
Rules: segments = segment REVENUE for the latest quarter column only. Leave balance_sheet / cash_flow
null if those statements are not in the excerpt. Dates are period END dates (e.g. quarter ended
30 September 2026 -> 2026-09-30)."""

MGMT_PROMPT = """Below is the text of a corporate filing about a change in management, split into pages.
Identify each person whose position changes.

Return JSON:
{{
  "people": [ {{
      "name": "...", "change": "appointed"|"resigned"|"retired"|"reappointed"|"ceased"|"redesignated"|"passed_away",
      "role": "...", "effective_date": "YYYY-MM-DD"|null, "reason": "<as stated, or null>",
      "profile": "<= 60 words summarising the brief profile given IN THIS FILING, or null if none>",
      "prior_roles": ["..."], "qualifications": ["..."], "page": <int>
  }} ],
  "summary": "<= 20 words, factual"
}}

FILING TEXT:
{text}"""

SUMMARY_PROMPT = """Company: {company}. Filing category: {category}. Subject: {subject}
Below is the filing text, split into pages. Write what an investor needs to know.

Return JSON:
{{
  "summary": "<= 28 words: what happened, with the key number if any. Facts from the filing only.",
  "materiality": "high"|"medium"|"low",   // low = routine paperwork with no economic effect
  "key_facts": [ {{"label": "...", "value": "..."}} ],  // max 4, e.g. Deal value / Counterparty / Rating
  "page": <int|null>
}}

FILING TEXT:
{text}"""

CLASSIFY_PROMPT = """Classify each Indian stock-exchange announcement into exactly one category from:
results, M&A, fund_raise, management_change, litigation, insider_trading, earnings_call,
investor_meetings, credit_rating, dividend, bonus_split, capex, press_release, postal_ballot,
agm_egm, pledging, unclassified.
"unclassified" = routine paperwork (ESOP allotments, compliance certificates, ESG reports, auditor
appointments, general "Updates" with no economic content).

Return JSON: {{"items": [{{"id": <id>, "category": "<one of the above>"}}]}}

ANNOUNCEMENTS:
{items}"""


def paged(texts: list[str], max_chars: int = 14000, offset: int = 0) -> str:
    out, used = [], 0
    for i, t in enumerate(texts):
        t = " ".join(t.split())
        if not t:
            continue
        chunk = f"[page {i + 1 + offset}] {t}"
        if used + len(chunk) > max_chars:
            chunk = chunk[: max(0, max_chars - used)]
        out.append(chunk)
        used += len(chunk)
        if used >= max_chars:
            break
    return "\n".join(out)
