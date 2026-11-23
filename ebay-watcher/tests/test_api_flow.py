"""The official-API path end to end, over real HTTP against a local fake eBay API."""

import asyncio

import httpx
import pytest

from ebaywatch import cli, runtime
from ebaywatch.config import Config
from ebaywatch.engine import Engine
from ebaywatch.notifiers import DiscordNotifier, Dispatcher
from ebaywatch.sources import api as api_mod
from ebaywatch.sources import create_source
from ebaywatch.sources.api import ApiSource, verify_credentials
from ebaywatch.sources.html import HtmlSource
from ebaywatch.store import Store

from .conftest import api_item


def api_config(**general) -> Config:
    return Config.from_dict({
        "general": {"min_delay_per_host": 0, **general},
        "api": {"client_id": "Me-ebaywatc-PRD-123456789-abcdef12", "client_secret": "secret"},
        "searches": [{"name": "Switch", "keywords": "switch oled", "countries": ["fr", "de"], "max_price": 300}],
    })


def test_auto_backend_selection(monkeypatch):
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
    assert isinstance(create_source(Config.from_dict({})), HtmlSource)
    assert isinstance(create_source(api_config()), ApiSource)
    forced_html = api_config(backend="html")
    assert isinstance(create_source(forced_html), HtmlSource)


def test_sandbox_keys_rejected_with_clear_message():
    config = Config.from_dict({"api": {"client_id": "Me-ebaywatc-SBX-1234-abcd", "client_secret": "x"}})
    assert config.api.is_sandbox
    with pytest.raises(ValueError, match="SANDBOX"):
        ApiSource(config)


def test_belgium_uses_documented_marketplace_id():
    from ebaywatch.markets import get_market

    be = get_market("be")
    assert be.marketplace_id == "EBAY_BE" and be.language.startswith("fr-BE")


async def test_end_to_end_api_engine_with_discord(fake_ebay, tmp_path):
    config = api_config()
    fake_ebay.api_items["EBAY_FR"] = [api_item("226000000002", "Switch OLED blanche"),
                                      api_item("226000000001", "Switch OLED rouge")]
    fake_ebay.api_items["EBAY_DE"] = []
    http = httpx.AsyncClient()
    source = ApiSource(config, api_root=fake_ebay.base_url)
    dispatcher = Dispatcher([DiscordNotifier(f"{fake_ebay.base_url}/discord/x", http)])
    engine = Engine(config, source, Store(tmp_path / "api.db"), dispatcher, interval=0.15,
                    min_delay_per_host=0, jitter=0)
    await engine.start()
    try:
        await asyncio.sleep(0.5)                                  # baselines FR + DE
        assert fake_ebay.discord_posts == []
        fake_ebay.api_items["EBAY_FR"].insert(0, api_item("226000000003", "Switch OLED neuve", "249.00"))
        fake_ebay.api_items["EBAY_FR"].insert(0, api_item("226000000004", "Switch OLED Zelda", "450.00"))  # > max
        fake_ebay.api_items["EBAY_DE"].insert(0, api_item("226000000005", "Switch OLED Weiß", "199.00"))
        for _ in range(100):
            if len(fake_ebay.discord_posts) >= 2:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.4)
        await dispatcher.drain(5)
    finally:
        await engine.stop()
        await dispatcher.stop()
        await source.aclose()
        await http.aclose()
    titles = sorted(p["embeds"][0]["title"] for p in fake_ebay.discord_posts)
    assert titles == ["Switch OLED Weiß", "Switch OLED neuve"]
    assert fake_ebay.api_token_calls == 1                        # token cached across calls
    req = fake_ebay.api_requests[0]
    assert req["query"]["sort"] == ["newlyListed"]
    assert "price:[..330.00]" in req["query"]["filter"][0] and "priceCurrency:EUR" in req["query"]["filter"][0]
    markets = {r["headers"]["X-EBAY-C-MARKETPLACE-ID"] for r in fake_ebay.api_requests}
    assert markets == {"EBAY_FR", "EBAY_DE"}


async def test_verify_credentials_ok_and_bad(fake_ebay):
    fake_ebay.api_items["EBAY_FR"] = [api_item("226000000001", "iPhone 15 128 Go")]
    ok, message = await verify_credentials(api_config(), api_root=fake_ebay.base_url)
    assert ok and "1 annonces reçues" in message and "iPhone 15" in message

    bad = Config.from_dict({"api": {"client_id": "Me-x-PRD-1", "client_secret": "wrong"},
                            "searches": [{"keywords": "x", "countries": ["fr"]}]})
    ok, message = await verify_credentials(bad, api_root=fake_ebay.base_url)
    assert not ok and "identifiants refusés" in message and "client authentication failed" in message

    sandbox = Config.from_dict({"api": {"client_id": "Me-x-SBX-1", "client_secret": "secret"}})
    ok, message = await verify_credentials(sandbox, api_root=fake_ebay.base_url)
    assert not ok and "SANDBOX" in message


def test_quota_aware_interval():
    searches = [{"name": f"S{i}", "keywords": "x", "countries": ["fr", "uk", "de"]} for i in range(3)]
    config = Config.from_dict({"general": {"interval_seconds": 30}, "searches": searches,
                               "api": {"client_id": "a-PRD-b", "client_secret": "c"}})
    engine = Engine(config, ApiSource(config), Store(":memory:"), None)
    # 9 targets * 86400 / (5000 * 0.95) = 163.7 -> 164 s
    assert engine.interval == 164 and "quota" in engine.quota_note
    html_engine = Engine(config, HtmlSource(config), Store(":memory:"), None)
    assert html_engine.interval == 30


# ------------------------------------------------------------------ CLI
@pytest.fixture
def cfg(tmp_path, monkeypatch, fake_ebay):
    from rich.console import Console

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "console", Console(width=250, highlight=False))
    real_verify = api_mod.verify_credentials
    monkeypatch.setattr(api_mod, "verify_credentials",
                        lambda config, client=None, api_root=None: real_verify(config, client, fake_ebay.base_url))
    monkeypatch.setattr(runtime, "create_source", lambda c: create_source(c))
    return tmp_path / "config.toml"


def test_setup_api_command_saves_only_valid_keys(cfg, fake_ebay, capsys):
    fake_ebay.api_items["EBAY_FR"] = [api_item("226000000001", "iPhone 15")]
    assert cli.main(["-f", str(cfg), "setup-api", "--client-id", "Me-x-PRD-1", "--client-secret", "wrong"]) == 2
    assert "Rien n'a été enregistré" in capsys.readouterr().out
    assert Config.load(cfg).api.client_id == ""

    assert cli.main(["-f", str(cfg), "setup-api", "--client-id", "Me-x-PRD-1", "--client-secret", "secret"]) == 0
    out = capsys.readouterr().out
    assert "Connexion OK" in out
    saved = Config.load(cfg)
    assert saved.api.client_id == "Me-x-PRD-1" and saved.effective_backend == "api"
    assert len(saved.searches) == 2                           # searches untouched


def test_setup_api_interactive_prompt(cfg, fake_ebay, monkeypatch, capsys):
    fake_ebay.api_items["EBAY_FR"] = [api_item("226000000001", "iPhone 15")]
    answers = iter(["Me-x-PRD-1", "secret"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert cli.main(["-f", str(cfg), "setup-api"]) == 0
    assert "developer.ebay.com" in capsys.readouterr().out


def test_doctor_blocked_points_to_setup_api(cfg, fake_ebay, monkeypatch, capsys):
    overrides = {"fr": fake_ebay.url_for("fr")}
    monkeypatch.setattr(cli, "create_source", lambda c: HtmlSource(c, base_url_override=overrides))
    fake_ebay.status["fr"] = 403
    assert cli.main(["-f", str(cfg), "doctor", "-c", "fr"]) == 2
    out = capsys.readouterr().out
    assert "BLOQUÉ" in out and "setup-api" in out
