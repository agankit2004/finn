"""Loaded by pytest before any test module, so every test uses a throwaway database and no AI key.

(Setting these inside one test file isn't enough: if another file imports finn first, the real
database in backend/data/ would be used.)"""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="finn-test-")
os.environ["FINN_DATA_DIR"] = _tmp
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/finn.db"
os.environ["GEMINI_API_KEY"] = ""
os.environ["GROQ_API_KEY"] = ""
os.environ["FINN_SAMPLE_MODE"] = "0"
