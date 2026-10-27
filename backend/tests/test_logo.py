from types import SimpleNamespace

from finn import api, config


def test_logo_uses_logo_dev_only_with_a_publishable_key(monkeypatch):
    c = SimpleNamespace(website="https://www.ril.com/")
    monkeypatch.setattr(config, "LOGO_DEV_TOKEN", "pk_test")
    assert api._logo(c) == "https://img.logo.dev/ril.com?token=pk_test&size=128&format=png&fallback=404"
    monkeypatch.setattr(config, "LOGO_DEV_TOKEN", "sk_secret")  # a secret key must never reach the page
    assert "google.com/s2/favicons?domain=ril.com" in api._logo(c)
    assert api._logo(SimpleNamespace(website="")) is None
