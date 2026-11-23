"""CLI commands against the local fake eBay server."""

import pytest

from rich.console import Console

from ebaywatch import cli, runtime
from ebaywatch.sources.html import HtmlSource

from .conftest import scard_page


@pytest.fixture
def cfg_path(tmp_path, monkeypatch, fake_ebay):
    monkeypatch.chdir(tmp_path)
    overrides = {c: fake_ebay.url_for(c) for c in ("fr", "uk", "de", "it", "es")}
    factory = lambda config: HtmlSource(config, base_url_override=overrides)  # noqa: E731
    monkeypatch.setattr(cli, "create_source", factory)
    monkeypatch.setattr(runtime, "create_source", factory)
    monkeypatch.setattr(cli, "console", Console(width=250, highlight=False))
    return tmp_path / "config.toml"


def run(*argv) -> int:
    return cli.main(list(argv))


def test_init_creates_config(cfg_path, capsys):
    assert run("-f", str(cfg_path), "init") == 0
    assert cfg_path.exists()
    assert run("-f", str(cfg_path), "init") == 1          # refuses to overwrite
    assert run("-f", str(cfg_path), "init", "--force") == 0


def test_search_command(cfg_path, fake_ebay, capsys):
    fake_ebay.pages["fr"] = scard_page([
        {"id": "226000000001", "title": "Lego Technic Ferrari 42143", "price": "320,00 EUR"},
        {"id": "226000000002", "title": "Lego Technic notice seule", "price": "5,00 EUR"},
    ])
    fake_ebay.pages["it"] = scard_page([
        {"id": "226000000003", "title": "Lego Technic Ferrari Daytona", "price": "299,00 EUR", "host": "www.ebay.it"},
    ])
    code = run("-f", str(cfg_path), "search", "lego technic", "-c", "fr", "it", "--exclude", "notice", "--all")
    out = capsys.readouterr().out
    assert code == 0
    assert cfg_path.exists()                               # auto-created on first use
    assert "Lego Technic Ferrari 42143" in out and "Daytona" in out
    assert "mot exclu" in out
    assert "2 annonces lues, 1 retenues" in out


def test_search_command_blocked(cfg_path, fake_ebay, capsys):
    fake_ebay.status["fr"] = 403
    assert run("-f", str(cfg_path), "search", "x", "-c", "fr") == 2
    assert "refusé" in capsys.readouterr().out


def test_search_bad_country(cfg_path, capsys):
    assert run("-f", str(cfg_path), "search", "x", "-c", "zz") == 1
    assert "Pays inconnu" in capsys.readouterr().out


def test_doctor_ok_and_failures(cfg_path, fake_ebay, capsys):
    fake_ebay.pages["fr"] = scard_page([{"id": "226000000001", "title": "iPhone 15", "price": "500,00 EUR"}])
    fake_ebay.pages["uk"] = scard_page([{"id": "226000000002", "title": "iPhone 14", "price": "£300.00",
                                         "host": "www.ebay.co.uk"}])
    assert run("-f", str(cfg_path), "doctor", "-c", "fr", "uk") == 0
    out = capsys.readouterr().out
    assert "OK" in out and "Tout fonctionne" in out

    fake_ebay.status["uk"] = 429
    fake_ebay.pages["fr"] = scard_page([])
    assert run("-f", str(cfg_path), "doctor", "-c", "fr", "uk") == 2
    out = capsys.readouterr().out
    assert "BLOQUÉ" in out and "0 annonce" in out
    assert (cfg_path.parent / "debug_www.ebay.fr.html").exists()     # page saved for debugging


def test_doctor_uses_configured_countries(cfg_path, fake_ebay, capsys):
    run("-f", str(cfg_path), "init")
    run("-f", str(cfg_path), "doctor")
    markets = {r["market"] for r in fake_ebay.requests}
    assert markets == {"fr", "uk", "de"}                  # countries of the template searches


def test_invalid_config_reports_error(cfg_path, capsys):
    cfg_path.write_text("[general]\ninterval_seconds = 3\n", encoding="utf-8")
    assert run("-f", str(cfg_path), "search", "x") == 1
    assert "interval_seconds" in capsys.readouterr().out


def test_test_notify_without_channels(cfg_path, capsys):
    run("-f", str(cfg_path), "init")
    assert run("-f", str(cfg_path), "test-notify") == 1
    assert "Aucun canal" in capsys.readouterr().out


def test_test_notify_discord(cfg_path, fake_ebay, capsys):
    run("-f", str(cfg_path), "init")
    text = cfg_path.read_text(encoding="utf-8").replace(
        'webhook_url = ""', f'webhook_url = "{fake_ebay.base_url}/discord/hook"')
    cfg_path.write_text(text, encoding="utf-8")
    assert run("-f", str(cfg_path), "test-notify") == 0
    assert len(fake_ebay.discord_posts) == 1
    assert "message envoyé" in capsys.readouterr().out


async def test_headless_run_detects_and_stops(cfg_path, fake_ebay, capsys):
    import asyncio

    from ebaywatch.config import Config

    run("-f", str(cfg_path), "init")
    config = Config.load(cfg_path)
    config.general.min_delay_per_host = 0
    config.general.interval_seconds = 1          # test only (the file enforces >= 15 s)
    config.general.database = str(cfg_path.parent / "headless.db")
    for c in ("fr", "uk", "de"):
        fake_ebay.pages[c] = scard_page([])
    task = asyncio.create_task(cli._run_headless(config))
    await asyncio.sleep(1.5)                     # baseline of the 3 countries
    fake_ebay.pages["fr"] = scard_page([{"id": "226000000009", "title": "Nintendo Switch OLED neuve",
                                         "price": "200,00 EUR"}])
    await asyncio.sleep(2.5)                     # next cycle must pick it up
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    out = capsys.readouterr().out
    assert "Surveillance démarrée (pages eBay) : 3 cible(s)" in out
    assert "initialisation" in out
    assert "Nintendo Switch OLED neuve" in out and "200,00 €" in out
    assert "https://www.ebay.fr/itm/226000000009" in out
