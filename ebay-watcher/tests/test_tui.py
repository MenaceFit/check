"""Drives the real Textual interface headlessly (keyboard input, dialogs, config file writes)."""

import asyncio

from textual.widgets import DataTable, Input, Select, SelectionList, Static

from ebaywatch.cli import template_text
from ebaywatch.config import Config
from ebaywatch.tui.app import EbayWatchApp
from ebaywatch.tui.screens import ConfirmScreen, SearchFormScreen, SettingsScreen

from .test_engine import FakeSource, L


def setup_app(tmp_path, autostart=True):
    path = tmp_path / "config.toml"
    path.write_text(template_text(), encoding="utf-8")
    config = Config.load(path)
    sources = []

    def factory(cfg):
        src = FakeSource()
        sources.append(src)
        return src

    app = EbayWatchApp(config, autostart=autostart, source_factory=factory)
    return app, path, sources


async def settle(pilot, n=3):
    for _ in range(n):
        await pilot.pause()


async def test_autostart_and_live_feed(tmp_path):
    app, path, sources = setup_app(tmp_path)
    async with app.run_test(size=(180, 50)) as pilot:
        await settle(pilot)
        assert app.runtime is not None and app.runtime.engine.running
        # template: 1 enabled search on fr/uk/de
        assert len(app.runtime.engine.targets) == 3
        status = str(app.query_one("#status", Static).render())
        assert "EN COURS" in status

        engine = app.runtime.engine
        source = sources[-1]
        fr = engine.targets[0]
        await asyncio.sleep(0.2)                      # initial (baseline) checks run
        source.pages["fr"] = [L("226000000001", "Nintendo Switch OLED neuve", 199.0)]
        await engine.check_target(fr)
        await settle(pilot, 5)

        feed = app.query_one("#feed-table", DataTable)
        assert feed.row_count == 1
        row = feed.get_row_at(0)
        assert "Nintendo Switch OLED neuve" in str(row[3])
        assert app.session_new == 1

        # Stop / start with "s"
        await pilot.press("s")
        await settle(pilot)
        assert app.runtime is None
        await pilot.press("s")
        await settle(pilot)
        assert app.runtime is not None
        await pilot.press("q")
        await settle(pilot)
    # history persisted
    reopened, *_ = setup_app(tmp_path, autostart=False)
    assert len(reopened.store.recent_listings()) == 1


async def test_add_search_via_form_writes_config(tmp_path):
    app, path, _ = setup_app(tmp_path, autostart=False)
    async with app.run_test(size=(180, 60)) as pilot:
        await pilot.press("a")
        await settle(pilot)
        form = app.screen
        assert isinstance(form, SearchFormScreen)
        form.query_one("#f-keywords", Input).value = "lego technic 42143"
        form.query_one("#f-name", Input).value = "Lego Ferrari"
        countries = form.query_one("#f-countries", SelectionList)
        countries.select("it")
        countries.select("es")
        form.query_one("#f-min", Input).value = "abc"
        await pilot.press("ctrl+s")
        await settle(pilot)
        assert isinstance(app.screen, SearchFormScreen)          # validation error keeps the form open
        assert "Prix min" in str(form.query_one("#form-error", Static).render())

        form.query_one("#f-min", Input).value = ""
        form.query_one("#f-max", Input).value = "350,5"
        form.query_one("#f-exclude", Input).value = "notice, boite abîmée"
        form.query_one("#f-condition", Select).value = "new"
        await pilot.press("ctrl+s")
        await settle(pilot)
        assert not isinstance(app.screen, SearchFormScreen)

    saved = Config.load(path)
    lego = saved.get_search("lego ferrari")
    assert lego is not None
    assert lego.keywords == "lego technic 42143"
    assert lego.countries == ["fr", "it", "es"]
    assert lego.max_price == 350.5 and lego.min_price is None
    assert lego.exclude == ["notice", "boite abîmée"]
    assert lego.condition.value == "new"
    assert len(saved.searches) == 3


async def test_duplicate_name_rejected(tmp_path):
    app, path, _ = setup_app(tmp_path, autostart=False)
    async with app.run_test(size=(180, 60)) as pilot:
        await pilot.press("a")
        await settle(pilot)
        form = app.screen
        form.query_one("#f-keywords", Input).value = "x"
        form.query_one("#f-name", Input).value = "switch oled"     # same as template (case-insensitive)
        await pilot.press("ctrl+s")
        await settle(pilot)
        assert "existe" in str(form.query_one("#form-error", Static).render()) or \
               "déjà" in str(form.query_one("#form-error", Static).render())
        await pilot.press("escape")
        await settle(pilot)
        assert not isinstance(app.screen, SearchFormScreen)
    assert len(Config.load(path).searches) == 2


async def test_edit_toggle_delete(tmp_path):
    app, path, _ = setup_app(tmp_path, autostart=False)
    async with app.run_test(size=(180, 60)) as pilot:
        await pilot.press("2")
        await settle(pilot)
        table = app.query_one("#search-table", DataTable)
        table.focus()
        table.move_cursor(row=1)                                   # "PS5 Slim" (disabled)
        await pilot.press("t")
        await settle(pilot)
        assert Config.load(path).searches[1].enabled is True

        await pilot.press("e")
        await settle(pilot)
        form = app.screen
        assert isinstance(form, SearchFormScreen)
        assert form.query_one("#f-keywords", Input).value == "ps5 slim"
        form.query_one("#f-keywords", Input).value = "ps5 slim digital"
        await pilot.press("ctrl+s")
        await settle(pilot)
        assert Config.load(path).searches[1].keywords == "ps5 slim digital"

        await pilot.press("d")
        await settle(pilot)
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("y")
        await settle(pilot)
    saved = Config.load(path)
    assert [s.name for s in saved.searches] == ["Switch OLED"]


async def test_shortcuts_ignored_inside_dialog(tmp_path):
    app, path, _ = setup_app(tmp_path, autostart=False)
    async with app.run_test(size=(180, 60)) as pilot:
        await pilot.press("a")
        await settle(pilot)
        form = app.screen
        form.query_one("#f-countries", SelectionList).focus()
        await pilot.press("d", "p", "s", "a")                     # must not trigger app actions
        await settle(pilot)
        assert app.screen is form
        assert app.runtime is None


async def test_settings_validation_and_save(tmp_path):
    app, path, _ = setup_app(tmp_path, autostart=False)
    async with app.run_test(size=(180, 60)) as pilot:
        await pilot.press("p")
        await settle(pilot)
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        screen.query_one("#s-interval", Input).value = "5"
        await pilot.press("ctrl+s")
        await settle(pilot)
        assert "interval" in str(screen.query_one("#settings-error", Static).render())

        screen.query_one("#s-interval", Input).value = "30"
        screen.query_one("#s-discord", Input).value = "https://example.com/hook"
        await pilot.press("ctrl+s")
        await settle(pilot)
        assert "discord" in str(screen.query_one("#settings-error", Static).render()).lower()

        screen.query_one("#s-discord", Input).value = "https://discord.com/api/webhooks/123/abc"
        screen.query_one("#s-tg-token", Input).value = "123:ABC"
        screen.query_one("#s-tg-chat", Input).value = "42"
        await pilot.press("ctrl+s")
        await settle(pilot)
        assert not isinstance(app.screen, SettingsScreen)
        status = str(app.query_one("#status", Static).render())
        assert "Discord ✓" in status and "Telegram ✓" in status and "30 s" in status

    saved = Config.load(path)
    assert saved.general.interval_seconds == 30
    assert saved.notifications.discord_webhook_url.endswith("/abc")
    assert saved.notifications.telegram_chat_id == "42"
    assert len(saved.searches) == 2                                # searches untouched


async def test_reload_after_manual_edit(tmp_path):
    app, path, _ = setup_app(tmp_path, autostart=False)
    async with app.run_test(size=(180, 60)) as pilot:
        text = path.read_text(encoding="utf-8").replace('keywords = "ps5 slim"', 'keywords = "ps5 pro"')
        path.write_text(text, encoding="utf-8")
        await pilot.press("r")
        await settle(pilot)
        assert app.config.searches[1].keywords == "ps5 pro"

        path.write_text("[general\nbroken", encoding="utf-8")
        await pilot.press("r")
        await settle(pilot)
        assert app.config.searches[1].keywords == "ps5 pro"       # bad file: previous config kept


async def test_no_search_message(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[general]\ninterval_seconds = 60\n", encoding="utf-8")
    app = EbayWatchApp(Config.load(path), autostart=True, source_factory=lambda c: FakeSource())
    async with app.run_test(size=(160, 40)) as pilot:
        await settle(pilot)
        assert app.runtime is None
        await pilot.press("s")
        await settle(pilot)
        assert app.runtime is None
