"""Announcement classification: deterministic rules first, LLM only for what rules can't place.

Taxonomy follows ENAM's reference document, plus a `subtype` that captures distinctions that
matter for priority (e.g. an actual results filing vs. a notice of the board meeting).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CATEGORIES = [
    "results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
    "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex",
    "press_release", "postal_ballot", "agm_egm", "pledging", "unclassified",
]

LABELS = {
    "results": "Results", "M&A": "M&A", "fund_raise": "Fund raise", "management_change": "Management change",
    "litigation": "Litigation", "insider_trading": "Insider trading", "earnings_call": "Earnings call",
    "investor_meetings": "Investor meet", "credit_rating": "Credit rating", "dividend": "Dividend",
    "bonus_split": "Bonus / split", "capex": "Capex", "press_release": "Press release",
    "postal_ballot": "Postal ballot", "agm_egm": "AGM / EGM", "pledging": "Pledging",
    "unclassified": "Routine",
}


@dataclass
class Classification:
    category: str
    subtype: str | None
    method: str  # rule | llm | fallback


def _rx(p: str) -> re.Pattern:
    return re.compile(p, re.I)


TOP_ROLE = _rx(r"\b(ceo|cfo|coo|cto|chief executive|chief financial|chief operating|managing director|"
               r"\bmd\b|chairman|chairperson|whole[- ]?time director|executive director|group ceo|president)\b")

RULES: list[tuple[re.Pattern, str, str | None]] = [
    # --- routine paperwork that would otherwise match a stronger rule -----------------
    (_rx(r"trading window"), "unclassified", "trading_window"),
    (_rx(r"newspaper|publication of (the )?(un)?audited|advertisement"), "_ad", None),
    (_rx(r"\b(esop|esos|esps|employee stock|stock option)"), "unclassified", "esop"),
    (_rx(r"scrutini[sz]er"), "agm_egm", None),
    (_rx(r"\biepf\b|unclaimed dividend|tds on dividend|deduction of tax"), "unclassified", "compliance"),
    (_rx(r"(repayment|redemption) of .{0,40}(commercial paper|\bcps?\b|debentures?|\bncds?\b|bonds?)|"
         r"payment of (interest|coupon)|record date for (payment of )?(interest|redemption)"), "unclassified", "debt_servicing"),
    (_rx(r"regulation 74\s*\(5\)|74\(5\)|loss of share cert|duplicate share|issue of duplicate"), "unclassified", "compliance"),
    (_rx(r"shareholding pattern|investor complaint|reconciliation of share capital|compliance cert|"
         r"certificate under|corporate governance report|statement of deviation|change in (registrar|rta)|"
         r"secretarial (audit|compliance)|brsr|business responsibility|esg (report|rating)|sustainability report"),
     "unclassified", "compliance"),
    (_rx(r"\b(statutory |secretarial |cost |internal )?auditors?\b.*(appoint|resign|change)|"
         r"(appoint|resign|change).*\b(statutory|secretarial|cost|internal) auditor"), "unclassified", "auditor"),
    # --- earnings call before results (subjects often say "results conference call") ---
    (_rx(r"transcript"), "earnings_call", "transcript"),
    (_rx(r"(audio|video)[\s/-]*(recording|link)|recording of the (earnings|conference|analyst|investor)"),
     "earnings_call", "recording"),
    (_rx(r"(earnings|conference|investor|analyst)[\s/-]*calls?\b|con[- ]?call"), "earnings_call", "call_notice"),
    # --- results ---------------------------------------------------------------------------
    (_rx(r"(investor|earnings|results|analyst) presentation|press release.*results|results press release"),
     "results", "results_presentation"),
    (_rx(r"outcome of (the )?board meeting.*(result|financial)"), "results", "results_filing"),
    (_rx(r"(intimation|notice) of (the )?board meeting|board meeting intimation|prior intimation|"
         r"board meeting (to be held|scheduled|on .{0,40} to consider)|to consider and approve .{0,40}results"),
     "results", "results_intimation"),
    (_rx(r"financial results|\bresults for the (quarter|half|period|year)|(un)?audited (standalone|consolidated)?\s*"
         r"(financial )?results|quarterly results|q[1-4]\s*(fy)?\s*'?\d{2}.*results"), "results", "results_filing"),
    # board meeting outcome that doesn't mention results (in results season it often is): FINN reads it to check
    (_rx(r"outcome of (the )?board meeting|board meeting outcome"), "results", "board_outcome"),
    # --- corporate events -------------------------------------------------------------------
    (_rx(r"pledg|encumbrance|invocation of"), "pledging", None),
    (_rx(r"credit rating|\bratings?\b.*(reaffirm|upgrade|downgrade|assign|revis)|"
         r"\b(crisil|icra|care ratings|careedge|india ratings|fitch|moody|s&p global)\b"), "credit_rating", None),
    (_rx(r"insider trading|\bsast\b|regulation 29|regulation 31|regulation 7\s*\(\s*2|substantial acquisition"),
     "insider_trading", None),
    (_rx(r"buy[- ]?back|\bqip\b|qualified institution|rights issue|preferential (issue|allotment)|"
         r"commercial paper|non[- ]?convertible debenture|\bncds?\b|issue of (bonds|debentures)|"
         r"fund[- ]?rais|raising of funds|issue of warrants|initial public offer|\bipo\b|offer for sale|"
         r"\bdrhp\b|red herring"), "fund_raise", None),
    (_rx(r"acqui|merger|amalgamation|de-?merger|joint venture|\bjv\b|scheme of arrangement|"
         r"divest|disinvest|slump sale|sale of (stake|shares|business|undertaking)|stake in|"
         r"incorporation of (a |an )?(new )?(wholly[- ]owned |step[- ]down )?subsidiar|investment in .*subsidiar"),
     "M&A", None),
    (_rx(r"(appoint|resign|cessation|re-?appoint|retire|step(s|ping)? down|change in (management|directorate|kmp|"
         r"key managerial|senior management)|demise)"), "management_change", None),
    (_rx(r"litigation|lawsuit|\bcourt\b|tribunal|\bnclt\b|\bnclat\b|\bsebi\b.*order|penalt|\bfine[ds]?\b|"
         r"show[- ]cause|demand order|tax demand|\bdemand (of|notice)|tax authorit|order passed by|assessment order|\bgst\b.*(order|demand)|income[- ]tax.*(order|demand)|"
         r"insolvency|\bcirp\b|arbitra|warning letter|form 483|regulatory action|search (and|&) seizure"),
     "litigation", None),
    (_rx(r"bonus|stock split|sub-?division|split of (equity )?shares"), "bonus_split", None),
    (_rx(r"dividend") , "dividend", None),
    (_rx(r"capex|capital expenditure|capacity (expansion|addition)|new (plant|facility|unit|factory)|"
         r"commission(ing|ed)|commercial (production|operation)|greenfield|brownfield"), "capex", None),
    (_rx(r"postal ballot"), "postal_ballot", None),
    (_rx(r"\bagm\b|\begm\b|annual general meeting|extra[- ]?ordinary general meeting|book closure|e-?voting|"
         r"scrutini[sz]er"), "agm_egm", None),
    (_rx(r"analysts?\s*/?\s*(institutional )?investors?\s*meet|investor (meet|conference|day)|analyst meet|"
         r"one[- ]on[- ]one|roadshow|non[- ]deal|schedule of (analyst|investor)|meeting with (analyst|investor|fund)"),
     "investor_meetings", None),
    (_rx(r"annual report"), "unclassified", "annual_report"),
    (_rx(r"order (win|received|inflow)|receipt of (an )?orders?|bagging|receiving of orders?|award of (order|contract)|bags?\b|secures?\b|"
         r"\bwins?\b.*(order|contract)|letter of (award|intent)"), "press_release", "order_win"),
    (_rx(r"clarification|rumou?r|news item|media report"), "press_release", "clarification"),
    (_rx(r"press release|media release|launch|partnership|collaborat|\bmou\b|agreement|tie[- ]up"),
     "press_release", None),
]

BSE_CATEGORY_FALLBACK = {
    "result": ("results", "results_filing"),
    "agm/egm": ("agm_egm", None),
    "insider trading / sast": ("insider_trading", None),
    "corp. action": ("dividend", None),
    "new listing": ("unclassified", None),
}


def classify_rule(subject: str, headline: str | None = None, category: str | None = None,
                  subcategory: str | None = None) -> Classification | None:
    text = " ".join(x for x in [subcategory, subject, (headline or "")[:400]] if x)
    for rx, cat, sub in RULES:
        if rx.search(text):
            if cat == "_ad":  # newspaper ads: results ads are still "results", but trivial
                if re.search(r"result", text, re.I):
                    return Classification("results", "results_ad", "rule")
                return Classification("unclassified", "newspaper_ad", "rule")
            if cat == "management_change":
                if re.search(r"\bauditor", text, re.I):
                    return Classification("unclassified", "auditor", "rule")
                return Classification(cat, "top" if TOP_ROLE.search(text) else "other", "rule")
            if cat == "credit_rating":
                sub = ("downgrade" if re.search(r"downgrad|negative", text, re.I)
                       else "upgrade" if re.search(r"upgrad|positive", text, re.I)
                       else "reaffirm" if re.search(r"reaffirm", text, re.I) else "assign")
            return Classification(cat, sub, "rule")
    if category:
        fb = BSE_CATEGORY_FALLBACK.get(category.strip().lower())
        if fb:
            return Classification(fb[0], fb[1], "fallback")
    return None
