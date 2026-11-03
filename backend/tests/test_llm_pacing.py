import time

from finn.ai import llm


def test_pacing_is_per_model(monkeypatch):
    monkeypatch.setattr(llm, "_last", {})
    llm._pace("model-a")
    t = time.monotonic()
    llm._pace("model-b")  # a different model must not wait for model-a's slot
    assert time.monotonic() - t < 0.5


def test_used_up_quota_survives_a_restart(monkeypatch):
    monkeypatch.setattr(llm, "_quota_until", {})
    monkeypatch.setattr(llm, "_quota_loaded", True)
    llm._save_quota("gemini-x", time.time() + 3600)
    # simulate a fresh process: memory empty, quotas read back from the database
    monkeypatch.setattr(llm, "_quota_until", {})
    monkeypatch.setattr(llm, "_quota_loaded", False)
    monkeypatch.setattr(llm.config, "GEMINI_SMART_MODEL", "gemini-x")
    assert "gemini-x" not in llm._models_for("smart")
