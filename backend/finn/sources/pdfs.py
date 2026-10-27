"""Download, cache and parse filing PDFs. Page numbers are preserved for citations."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pymupdf

from .. import config
from .http import SourceError, get, make_client

log = logging.getLogger("finn.pdfs")
MAX_BYTES = 45 * 1024 * 1024


def _cache_path(url: str) -> Path:
    return config.PDF_CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".pdf")


def download(url: str) -> tuple[Path, str]:
    """Return (local_path, sha256). Cached forever; filings don't change once filed."""
    path = _cache_path(url)
    if path.exists() and path.stat().st_size > 0:
        return path, hashlib.sha256(path.read_bytes()).hexdigest()
    candidates = [url]
    if "/AttachLive/" in url:
        candidates.append(url.replace("/AttachLive/", "/AttachHis/"))
    elif "/AttachHis/" in url:
        candidates.append(url.replace("/AttachHis/", "/AttachLive/"))
    headers = {"Referer": "https://www.bseindia.com/", "Accept": "application/pdf,*/*"}
    last: Exception | None = None
    with make_client(headers=headers, timeout=60) as c:
        for u in candidates:
            try:
                r = get(c, u, retries=2)
            except SourceError as e:
                last = e
                continue
            data = r.content
            if len(data) > MAX_BYTES:
                raise SourceError(f"PDF too large ({len(data) // 1_000_000} MB)")
            if not data.startswith(b"%PDF"):
                last = SourceError("Response was not a PDF")
                continue
            path.write_bytes(data)
            return path, hashlib.sha256(data).hexdigest()
    raise SourceError(f"Could not download {url}: {last}")


def page_texts(path: Path, max_pages: int | None = None) -> list[str]:
    with pymupdf.open(path) as doc:
        n = doc.page_count if max_pages is None else min(doc.page_count, max_pages)
        return [doc[i].get_text("text") for i in range(n)]


def page_count(path: Path) -> int:
    with pymupdf.open(path) as doc:
        return doc.page_count


def is_scanned(texts: list[str]) -> bool:
    if not texts:
        return True
    avg = sum(len(t.strip()) for t in texts) / len(texts)
    return avg < 80


def subset_pdf(path: Path, pages: list[int]) -> bytes:
    """Return a new PDF containing only the given 0-based pages (to keep LLM inputs small)."""
    with pymupdf.open(path) as src:
        out = pymupdf.open()
        for p in pages:
            if 0 <= p < src.page_count:
                out.insert_pdf(src, from_page=p, to_page=p)
        data = out.tobytes()
        out.close()
        return data
