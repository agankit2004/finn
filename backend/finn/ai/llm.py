"""LLM access: Google Gemini (free tier) with optional Groq fallback for text-only tasks.

Design choices for cost:
  * Every response is cached by a hash of (model tier, prompt version, inputs). A filing is
    processed at most once, ever.
  * "fast" tier (Flash-Lite class) for bulk classification/extraction; "smart" tier (Flash class)
    only for research synthesis.
  * Every call is logged to llm_calls so the app can show its own token bill.
  * All outputs are JSON, validated by the caller. Arithmetic is never delegated to the model.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import threading
import time

import httpx

from .. import config
from ..db import LlmCache, LlmCall, session_scope

log = logging.getLogger("finn.llm")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_MIN_INTERVAL = float(os.getenv("FINN_LLM_MIN_INTERVAL", "4.5"))  # free-tier friendly pacing
_lock = threading.Lock()
_last = 0.0
_dead_models: set[str] = set()


class ModelBusy(RuntimeError):
    """Gemini 503: this model is overloaded right now."""


class LlmUnavailable(RuntimeError):
    pass


def _pace() -> None:
    global _last
    with _lock:
        wait = _last + _MIN_INTERVAL - time.monotonic()
        _last = max(time.monotonic(), _last + _MIN_INTERVAL)
    if wait > 0:
        time.sleep(wait)


def _parse_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if m:
            return json.loads(m.group(1))
        raise


def _models_for(tier: str) -> list[str]:
    first = config.GEMINI_SMART_MODEL if tier == "smart" else config.GEMINI_FAST_MODEL
    seq = [first] + [m for m in config.GEMINI_FALLBACK_MODELS if m != first]
    return [m for m in seq if m not in _dead_models] or seq


def _log_call(purpose: str, model: str, usage: dict, cache_hit: bool, ok: bool = True) -> None:
    try:
        with session_scope() as s:
            s.add(LlmCall(purpose=purpose, model=model, cache_hit=cache_hit, ok=ok,
                          input_tokens=int(usage.get("in", 0)), output_tokens=int(usage.get("out", 0))))
    except Exception:  # never let bookkeeping break the pipeline
        log.exception("could not log llm call")


def _gemini(model: str, system: str, prompt: str, pdf: bytes | None, temperature: float) -> tuple[str, dict]:
    parts: list[dict] = [{"text": prompt}]
    if pdf:
        parts.append({"inline_data": {"mime_type": "application/pdf", "data": base64.b64encode(pdf).decode()}})
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
    }
    r = httpx.post(
        GEMINI_URL.format(model=model), json=body, timeout=180,
        headers={"x-goog-api-key": config.GEMINI_API_KEY},
    )
    if r.status_code == 404:
        raise FileNotFoundError(model)
    if r.status_code == 429:  # rate limit: passes after a pause, so back off and retry
        raise TimeoutError(r.text[:300])
    if r.status_code == 503:  # "high demand" on this model: another model is usually free right now
        raise ModelBusy(r.text[:300])
    if r.status_code in (400, 401, 403) and ("API_KEY_INVALID" in r.text or "API key not valid" in r.text
                                             or "PERMISSION_DENIED" in r.text):
        raise KeyError("Gemini API key is invalid or not allowed to use this API")
    if r.status_code >= 400:
        raise LlmUnavailable(f"Gemini {r.status_code}: {r.text[:300]}")
    data = r.json()
    cands = data.get("candidates") or []
    if not cands or not cands[0].get("content", {}).get("parts"):
        reason = (cands[0].get("finishReason") if cands else None) or data.get("promptFeedback")
        raise LlmUnavailable(f"Gemini returned no content ({reason})")
    text = "".join(p.get("text", "") for p in cands[0]["content"]["parts"])
    um = data.get("usageMetadata", {})
    return text, {"in": um.get("promptTokenCount", 0), "out": um.get("candidatesTokenCount", 0)}


def _groq(system: str, prompt: str, temperature: float) -> tuple[str, dict]:
    r = httpx.post(
        GROQ_URL, timeout=120,
        headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
        json={
            "model": config.GROQ_MODEL, "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        },
    )
    if r.status_code >= 400:
        raise LlmUnavailable(f"Groq {r.status_code}: {r.text[:300]}")
    d = r.json()
    u = d.get("usage", {})
    return d["choices"][0]["message"]["content"], {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)}


def generate_json(
    purpose: str,
    system: str,
    prompt: str,
    *,
    tier: str = "fast",
    pdf: bytes | None = None,
    version: str = "v1",
    temperature: float = 0.1,
    use_cache: bool = True,
):
    """Return parsed JSON from the model. Raises LlmUnavailable if no provider can answer."""
    key = hashlib.sha256(
        json.dumps([purpose, version, tier, system, prompt, hashlib.sha256(pdf).hexdigest() if pdf else None]).encode()
    ).hexdigest()
    if use_cache:
        with session_scope() as s:
            hit = s.get(LlmCache, key)
            if hit:
                _log_call(purpose, "cache", {}, cache_hit=True)
                return hit.response["data"]

    if not config.GEMINI_API_KEY and not (config.GROQ_API_KEY and pdf is None):
        raise LlmUnavailable("No LLM key configured (set GEMINI_API_KEY in backend/.env)")

    errors: list[str] = []
    result = None
    if config.GEMINI_API_KEY:
        for model in _models_for(tier):
            for attempt in range(3):
                _pace()
                try:
                    text, usage = _gemini(model, system, prompt, pdf, temperature)
                    result = _parse_json(text)
                    _log_call(purpose, model, usage, cache_hit=False)
                    break
                except KeyError as e:  # bad key: no point trying other models
                    _log_call(purpose, model, {}, cache_hit=False, ok=False)
                    raise LlmUnavailable(str(e).strip("'")) from e
                except FileNotFoundError:
                    _dead_models.add(model)
                    errors.append(f"{model}: not found")
                    break
                except ModelBusy:  # one quick retry, then move on to the next model
                    errors.append(f"{model}: busy")
                    if attempt >= 1:
                        break
                    time.sleep(3)
                except TimeoutError as e:  # 429: back off and retry the same model
                    errors.append(f"{model}: rate limited")
                    time.sleep(10 * (attempt + 1))
                    if attempt == 2:
                        log.warning("rate limit persists on %s: %s", model, e)
                except (json.JSONDecodeError, ValueError) as e:
                    errors.append(f"{model}: bad JSON ({e})")
                    _log_call(purpose, model, {}, cache_hit=False, ok=False)
                except (LlmUnavailable, httpx.HTTPError) as e:
                    errors.append(f"{model}: {e}")
                    _log_call(purpose, model, {}, cache_hit=False, ok=False)
                    break
            if result is not None:
                break
    if result is None and config.GROQ_API_KEY and pdf is None:
        try:
            text, usage = _groq(system, prompt, temperature)
            result = _parse_json(text)
            _log_call(purpose, f"groq:{config.GROQ_MODEL}", usage, cache_hit=False)
        except Exception as e:
            errors.append(f"groq: {e}")
    if result is None:
        raise LlmUnavailable("; ".join(errors[-4:]) or "LLM unavailable")
    with session_scope() as s:
        if not s.get(LlmCache, key):
            s.add(LlmCache(key=key, response={"data": result}))
    return result
