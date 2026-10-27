"""Shared HTTP client: browser-like headers, retries with backoff, and per-host politeness delay.

Exchange endpoints used here are UNOFFICIAL (they power the exchanges' own websites). We keep
request volume low (one date-range query per poll), cache everything, and back off on errors.
"""
from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlparse

import httpx

from .. import config

log = logging.getLogger("finn.http")

_MIN_INTERVAL = {  # seconds between requests to the same host
    "api.bseindia.com": 1.0,
    "www.bseindia.com": 1.0,
    "www.nseindia.com": 2.0,
    "nsearchives.nseindia.com": 1.0,
    "www.screener.in": 3.0,
    "news.google.com": 1.5,
}
_last_hit: dict[str, float] = {}
_lock = threading.Lock()


class SourceError(RuntimeError):
    """A data source failed (blocked, rate-limited, changed format, offline)."""


def _wait_turn(host: str) -> None:
    gap = _MIN_INTERVAL.get(host, 0.3)
    with _lock:
        now = time.monotonic()
        wait = _last_hit.get(host, 0) + gap - now
        _last_hit[host] = max(now, _last_hit.get(host, 0) + gap)
    if wait > 0:
        time.sleep(wait)


def make_client(**kw) -> httpx.Client:
    headers = {
        "User-Agent": config.HTTP_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-IN,en;q=0.9",
    }
    headers.update(kw.pop("headers", {}))
    return httpx.Client(headers=headers, timeout=kw.pop("timeout", 30), follow_redirects=True, **kw)


def get(client: httpx.Client, url: str, *, params=None, headers=None, retries: int = 3) -> httpx.Response:
    host = urlparse(url).netloc
    last_exc: Exception | None = None
    for attempt in range(retries):
        _wait_turn(host)
        try:
            r = client.get(url, params=params, headers=headers)
            if r.status_code in (429, 503):
                raise SourceError(f"{host} rate-limited ({r.status_code})")
            if r.status_code in (401, 403):
                raise SourceError(f"{host} refused the request ({r.status_code}); likely bot protection")
            r.raise_for_status()
            return r
        except (httpx.HTTPError, SourceError) as e:
            last_exc = e
            if isinstance(e, SourceError) and "refused" in str(e):
                break  # retrying a block just makes it worse
            time.sleep(1.5 * (2**attempt))
    raise SourceError(f"GET {url} failed: {last_exc}")
