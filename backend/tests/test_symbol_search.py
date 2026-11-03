from finn import universe
from finn.sources.http import SourceError


def test_search_uses_bundled_nse_list_when_exchanges_refuse(monkeypatch, tmp_path):
    def refuse(*a, **k):
        raise SourceError("403")

    monkeypatch.setattr(universe, "_CACHE", tmp_path / "symbol_master.json")
    monkeypatch.setattr(universe, "get", refuse)
    monkeypatch.setattr(universe, "_MEMO", None)
    monkeypatch.setattr(universe, "_FAILED_AT", 0.0)
    hits = universe.search("microns")
    assert {"symbol": "20MICRONS", "name": "20 Microns Limited"} in hits
    assert len(universe.search("TATA")) == 8  # partial symbol: several suggestions
    assert not (tmp_path / "symbol_master.json").exists()  # the fallback is not cached as a fresh fetch
