"""Central configuration. Everything is read from environment variables (or a .env file)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


DATA_DIR = Path(os.getenv("FINN_DATA_DIR", BACKEND_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
PDF_CACHE_DIR = DATA_DIR / "pdfs"
PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# SAMPLE MODE: loads clearly-labelled synthetic data (for UI development / offline demos only).
# It always uses its own database file so sample data can never mix with real data.
SAMPLE_MODE = _bool("FINN_SAMPLE_MODE", False)

# SQLite by default (zero setup). Set DATABASE_URL=postgresql+psycopg://... for deployment.
DATABASE_URL = (f"sqlite:///{DATA_DIR / 'finn_sample.db'}" if SAMPLE_MODE
                else os.getenv("DATABASE_URL", "").strip() or f"sqlite:///{DATA_DIR / 'finn.db'}")  # empty = unset
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

# --- LLM -------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
# Aliases track Google's current Flash models; override if Google renames them.
GEMINI_FAST_MODEL = os.getenv("GEMINI_FAST_MODEL", "gemini-flash-lite-latest")
GEMINI_SMART_MODEL = os.getenv("GEMINI_SMART_MODEL", "gemini-flash-latest")
GEMINI_FALLBACK_MODELS = [
    m.strip()
    for m in os.getenv(
        # Tried in order when the main model is busy or gone (Google retired 2.x for new keys in 2026).
        "GEMINI_FALLBACK_MODELS", "gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite,gemini-flash-lite-latest"
    ).split(",")
    if m.strip()
]
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Optional: company logos from logo.dev. Use the PUBLISHABLE key (pk_...), which is meant to be visible in pages.
LOGO_DEV_TOKEN = os.getenv("LOGO_DEV_TOKEN", "").strip()

# --- Behaviour ---------------------------------------------------------------
# Run the background refresh loop inside the API process (good for local use).
RUN_SCHEDULER = _bool("FINN_RUN_SCHEDULER", True)
ANNOUNCEMENT_POLL_MINUTES = int(os.getenv("FINN_ANNOUNCEMENT_POLL_MINUTES", "30"))
ENRICH_LIMIT_PER_RUN = int(os.getenv("FINN_ENRICH_LIMIT_PER_RUN", "25"))
REFRESH_SECRET = os.getenv("FINN_REFRESH_SECRET", "").strip()
CORS_ORIGINS = [o.strip() for o in os.getenv("FINN_CORS_ORIGINS", "*").split(",") if o.strip()]
USER_NAME = os.getenv("FINN_USER_NAME", "").strip()

HTTP_USER_AGENT = os.getenv(
    "FINN_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
)


def llm_enabled() -> bool:
    return bool(GEMINI_API_KEY)
