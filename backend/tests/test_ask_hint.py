from types import SimpleNamespace

from finn.research import ask


def test_greetings_get_a_hint_without_calling_the_model():
    company = SimpleNamespace(name="Vodafone Idea Limited", nse_symbol="IDEA")
    for q in ["hi", "Hello!", "ok", "?"]:
        out = ask.ask(None, company, q)  # no DB session needed: it must return before retrieval
        assert "Vodafone Idea Limited" in out["answer"][0]["text"]
        assert out["follow_ups"]


def test_not_in_sources_is_an_honest_answer_not_unverified():
    found = [{"text": "The provided sources do not contain information about the founder of Asian Paints.", "cites": []}]
    assert ask._is_not_found(found)
    assert ask._is_not_found([{"text": "There is no mention of a buyback in the sources.", "cites": []}])
    # a real claim, or one with a number or a citation, still goes through the grounding check
    assert not ask._is_not_found([{"text": "Revenue did not grow; it fell 3%.", "cites": []}])
    assert not ask._is_not_found([{"text": "The report does not mention a buyback.", "cites": ["S1"]}])
    assert not ask._is_not_found([{"text": "Paint demand was weak in rural markets.", "cites": []}])
    assert not ask._is_not_found([])
