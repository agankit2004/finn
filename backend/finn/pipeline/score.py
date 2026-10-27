"""Importance scoring: transparent, deterministic, explainable.

score = base weight for (category, subtype)
        + 10 if the investor marked this category as one they care about
        + modifiers from extracted facts (e.g. credit downgrade, large deal, results surprise)
Anything below ROUTINE_THRESHOLD is collapsed under "routine" in the digest.
"""
from __future__ import annotations

ROUTINE_THRESHOLD = 30

BASE: dict[tuple[str, str | None], int] = {
    ("results", "results_filing"): 90,
    ("results", "results_presentation"): 55,
    ("results", "results_intimation"): 35,
    ("results", "board_outcome"): 60,  # often the results themselves; FINN reads the PDF to check
    ("results", "results_ad"): 8,
    ("M&A", None): 82,
    ("management_change", "top"): 84,
    ("management_change", "other"): 48,
    ("management_change", None): 58,  # not yet read: shown, not hidden as routine
    ("fund_raise", None): 74,
    ("litigation", None): 68,
    ("credit_rating", "downgrade"): 80,
    ("credit_rating", "upgrade"): 62,
    ("credit_rating", "reaffirm"): 28,
    ("credit_rating", "assign"): 40,
    ("capex", None): 66,
    ("pledging", None): 70,
    ("bonus_split", None): 62,
    ("dividend", None): 42,
    ("insider_trading", None): 45,
    ("press_release", "order_win"): 58,
    ("press_release", "clarification"): 50,
    ("press_release", None): 40,
    ("earnings_call", "transcript"): 46,
    ("earnings_call", "call_notice"): 24,
    ("earnings_call", "recording"): 18,
    ("investor_meetings", None): 15,
    ("agm_egm", None): 22,
    ("postal_ballot", None): 22,
    ("unclassified", None): 5,
}

DEFAULT_CARE = ["results", "M&A", "management_change", "fund_raise", "litigation", "credit_rating", "pledging"]


def base_weight(category: str, subtype: str | None) -> int:
    return BASE.get((category, subtype), BASE.get((category, None), 20))


def score(category: str, subtype: str | None, cares: list[str], facts: dict | None = None) -> tuple[float, list[str]]:
    s = float(base_weight(category, subtype))
    reasons = [f"{category.replace('_', ' ')}{' · ' + subtype.replace('_', ' ') if subtype else ''} (base {int(s)})"]
    if category in cares and s >= ROUTINE_THRESHOLD:
        s += 10
        reasons.append("you track this category (+10)")
    facts = facts or {}
    mat = facts.get("materiality")
    if mat == "high":
        s += 8
        reasons.append("filing describes a material event (+8)")
    elif mat == "low" and s > ROUTINE_THRESHOLD:
        s -= 12
        reasons.append("filing content is routine (-12)")
    yoy = facts.get("pat_yoy_pct")
    if isinstance(yoy, (int, float)) and abs(yoy) >= 25:
        s += 6
        reasons.append(f"profit moved {yoy:+.0f}% YoY (+6)")
    return min(s, 100.0), reasons
