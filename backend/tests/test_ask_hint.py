from types import SimpleNamespace

from finn.research import ask


def test_greetings_get_a_hint_without_calling_the_model():
    company = SimpleNamespace(name="Vodafone Idea Limited", nse_symbol="IDEA")
    for q in ["hi", "Hello!", "ok", "?"]:
        out = ask.ask(None, company, q)  # no DB session needed: it must return before retrieval
        assert "Vodafone Idea Limited" in out["answer"][0]["text"]
        assert out["follow_ups"]
