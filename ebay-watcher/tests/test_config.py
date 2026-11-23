import tomllib

import pytest

from ebaywatch.cli import template_text
from ebaywatch.config import Config, ConfigError, Search
from ebaywatch.models import BuyingFormat, Condition


def test_template_is_valid_and_complete():
    data = tomllib.loads(template_text())
    config = Config.from_dict(data)
    assert config.general.backend == "auto"
    assert config.effective_backend == "html"          # no keys in the template
    assert config.general.api_daily_limit == 5000
    assert len(config.searches) == 2
    switch = config.searches[0]
    assert switch.countries == ["fr", "uk", "de"]
    assert switch.min_price == 120 and switch.max_price == 260
    assert "boite vide" in switch.exclude
    assert config.searches[1].enabled is False
    assert config.searches[1].buying_format is BuyingFormat.BUY_IT_NOW


def test_round_trip(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(template_text(), encoding="utf-8")
    config = Config.load(path)
    config.searches.append(Search.from_dict({
        "name": "Test é", "keywords": "lego 42143", "countries": ["it", "es"], "max_price": 300,
        "condition": "new", "exclude": ["notice"],
    }))
    config.notifications.discord_webhook_url = "https://discord.com/api/webhooks/1/abc"
    config.save()
    reloaded = Config.load(path)
    assert [s.name for s in reloaded.searches] == ["Switch OLED", "PS5 Slim", "Test é"]
    assert reloaded.searches[2].condition is Condition.NEW
    assert reloaded.searches[2].min_price is None
    assert reloaded.notifications.discord_webhook_url.endswith("/abc")
    assert not (tmp_path / "config.toml.tmp").exists()


def test_country_aliases_and_dedup():
    s = Search.from_dict({"keywords": "x", "countries": ["FR", "gb", "angleterre", "de"]})
    assert s.countries == ["fr", "uk", "de"]
    assert s.name == "x"


def test_countries_as_comma_string():
    assert Search.from_dict({"keywords": "x", "countries": "fr, uk"}).countries == ["fr", "uk"]


@pytest.mark.parametrize(
    ("search", "message"),
    [
        ({"keywords": ""}, "keywords"),
        ({"keywords": "x", "countries": ["zz"]}, "Pays inconnu"),
        ({"keywords": "x", "min_price": 50, "max_price": 10}, "min_price"),
        ({"keywords": "x", "buying_format": "lol"}, "buying_format"),
        ({"keywords": "x", "condition": "broken"}, "condition"),
        ({"keywords": "x", "min_price": "abc"}, "nombre"),
        ({"keywords": "x", "currency": "XYZ"}, "devise"),
        ({"keywords": "x", "category_id": "abc"}, "category_id"),
    ],
)
def test_invalid_search(search, message):
    with pytest.raises(ConfigError, match=message):
        Search.from_dict(search)


@pytest.mark.parametrize(
    ("general", "message"),
    [
        ({"interval_seconds": 5}, "interval_seconds"),
        ({"backend": "selenium"}, "backend"),
        ({"results_per_page": 50}, "results_per_page"),
        ({"max_concurrency": 0}, "max_concurrency"),
    ],
)
def test_invalid_general(general, message):
    with pytest.raises(ConfigError, match=message):
        Config.from_dict({"general": general})


def test_api_backend_requires_keys(monkeypatch):
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
    with pytest.raises(ConfigError, match="client_id"):
        Config.from_dict({"general": {"backend": "api"}})
    monkeypatch.setenv("EBAY_CLIENT_ID", "id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")
    assert Config.from_dict({"general": {"backend": "api"}}).api.configured


def test_duplicate_names_rejected():
    with pytest.raises(ConfigError, match="double"):
        Config.from_dict({"searches": [{"name": "A", "keywords": "x"}, {"name": "a", "keywords": "y"}]})


def test_toml_syntax_error(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[general\ninterval = ", encoding="utf-8")
    with pytest.raises(ConfigError, match="syntaxe"):
        Config.load(path)


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="introuvable"):
        Config.load(tmp_path / "nope.toml")


def test_currency_conversion():
    config = Config()
    assert config.convert(100, "EUR", "EUR") == 100
    assert config.convert(100, "GBP", "EUR") == pytest.approx(117)
    assert config.convert(117, "EUR", "GBP") == pytest.approx(100)


def test_database_path_relative_to_config(tmp_path):
    path = tmp_path / "sub" / "config.toml"
    path.parent.mkdir()
    path.write_text(template_text(), encoding="utf-8")
    config = Config.load(path)
    assert config.database_path == (tmp_path / "sub" / "ebaywatch.db").resolve()
