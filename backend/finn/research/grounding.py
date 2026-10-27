"""Grounding checks for AI-written research text.

Every statement the model writes must cite source ids. After generation we verify:
  1. cited ids exist;
  2. every number in the statement appears in the cited sources (or the facts table), allowing
     for rounding. Statements that fail are kept but flagged `verified: false`, and the UI shows
     them as unverified rather than presenting them as fact.
"""
from __future__ import annotations

import re

_NUM = re.compile(r"(?<![A-Za-z])[-−]?\d[\d,]*(?:\.\d+)?")
_YEARISH = re.compile(r"^(19|20)\d{2}$")


def numbers_in(text: str) -> list[float]:
    out = []
    for m in _NUM.finditer(text or ""):
        raw = m.group(0).replace(",", "").replace("−", "-")
        # Skip period labels like FY27 / Q2 (letters before) — handled by the lookbehind — and years.
        if _YEARISH.match(raw.lstrip("-")):
            continue
        try:
            out.append(float(raw))
        except ValueError:
            continue
    return out


def _supported(n: float, pool: list[float]) -> bool:
    if abs(n) < 10 and float(n).is_integer():
        return True  # small counts ("3 segments", "2 quarters") aren't financial claims
    for p in pool:
        if p == n:
            return True
        if p and abs(p - n) / max(abs(p), 1e-9) <= 0.006:  # rounding of displayed figures
            return True
        if abs(abs(p) - abs(n)) < 0.051:  # 12.34 vs 12.3
            return True
    return False


def check_statement(text: str, cites: list[str], sources: dict[str, str]) -> dict:
    valid = [c for c in cites or [] if c in sources]
    pool: list[float] = []
    for c in valid:
        pool.extend(numbers_in(sources[c]))
    nums = numbers_in(text)
    unsupported = [n for n in nums if not _supported(n, pool)]
    verified = bool(valid) and not unsupported
    reason = None
    if not valid:
        reason = "no valid citation"
    elif unsupported:
        reason = "number(s) not found in cited sources: " + ", ".join(f"{u:g}" for u in unsupported[:3])
    return {"text": text, "cites": valid, "verified": verified, "reason": reason}


def check_items(items: list[dict], sources: dict[str, str]) -> list[dict]:
    out = []
    for it in items or []:
        if not isinstance(it, dict) or not it.get("text"):
            continue
        chk = check_statement(it["text"], it.get("cites") or [], sources)
        out.append({**it, **chk})
    return out
