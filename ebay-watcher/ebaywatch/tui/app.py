"""Terminal user interface (Textual)."""

from __future__ import annotations

import webbrowser
from collections import deque
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widgets import DataTable, Footer, Header, RichLog, Static, TabbedContent, TabPane

from ..config import Config, ConfigError, Search
from ..engine import Event, LogEvent, NewListing, Target, TargetState, TargetUpdated
from ..markets import get_market
from ..models import Listing
from ..notifiers import build_notifiers
from ..runtime import Runtime, build_runtime
from ..store import Store
from .screens import ApiSetupScreen, ConfirmScreen, SearchFormScreen, SettingsScreen

FEED_LIMIT = 500

_STATE_STYLE = {
    TargetState.PENDING: "dim",
    TargetState.CHECKING: "cyan",
    TargetState.OK: "green",
    TargetState.BASELINE: "blue",
    TargetState.ERROR: "yellow",
    TargetState.BLOCKED: "bold red",
}
_BUYING_LABEL = {"all": "Tous", "bin": "Achat imm.", "auction": "Enchères"}


class EngineMessage(Message):
    def __init__(self, event: Event) -> None:
        super().__init__()
        self.event = event


class EbayWatchApp(App[None]):
    TITLE = "eBay Watcher"
    SUB_TITLE = "nouvelles annonces en temps réel"
    CSS_PATH = "app.tcss"

    BINDINGS = [
        Binding("s", "toggle_engine", "Démarrer/Arrêter"),
        Binding("a", "add_search", "Ajouter"),
        Binding("e", "edit_search", "Modifier"),
        Binding("d", "delete_search", "Supprimer"),
        Binding("t", "toggle_search", "Activer/Désact."),
        Binding("o", "open_listing", "Ouvrir annonce"),
        Binding("p", "settings", "Paramètres"),
        Binding("k", "api_setup", "Clés API"),
        Binding("r", "reload", "Recharger fichier"),
        Binding("n", "test_notifications", "Tester notifs", show=False),
        Binding("1", "show_tab('feed')", "Annonces", show=False),
        Binding("2", "show_tab('searches')", "Recherches", show=False),
        Binding("3", "show_tab('log')", "Journal", show=False),
        Binding("q", "quit", "Quitter"),
    ]

    def __init__(self, config: Config, autostart: bool = True, store: Store | None = None,
                 source_factory=None) -> None:
        super().__init__()
        self.config = config
        self.autostart = autostart
        self.store = store or Store(config.database_path)
        self.source_factory = source_factory      # tests can inject a fake source
        self.runtime: Runtime | None = None
        self.feed: deque[Listing] = deque(maxlen=FEED_LIMIT)
        self.targets: dict[tuple[str, str], Target] = {}
        self.session_new = 0
        self._block_hint_shown = False

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="status")
        with TabbedContent(initial="feed"):
            with TabPane("① Annonces", id="feed"):
                yield DataTable(id="feed-table", cursor_type="row", zebra_stripes=True)
            with TabPane("② Recherches", id="searches"):
                yield DataTable(id="search-table", cursor_type="row", zebra_stripes=True)
                yield Static(
                    "A : ajouter   E : modifier   D : supprimer   T : activer/désactiver   "
                    "(le fichier config.toml est mis à jour automatiquement)",
                    classes="hint",
                )
            with TabPane("③ Journal", id="log"):
                yield RichLog(id="log-view", wrap=True, highlight=False, markup=False, max_lines=2000)
        yield DataTable(id="target-table", cursor_type="none", zebra_stripes=False)
        yield Footer()

    def on_mount(self) -> None:
        feed = self.query_one("#feed-table", DataTable)
        feed.add_column("Heure", width=8, key="time")
        feed.add_column("Pays", width=5, key="country")
        feed.add_column("Recherche", width=16, key="search")
        feed.add_column("Titre", width=60, key="title")
        feed.add_column("Prix", width=13, key="price")
        feed.add_column("Livraison", width=22, key="shipping")
        feed.add_column("Type", width=10, key="type")

        searches = self.query_one("#search-table", DataTable)
        for label, width in (("Active", 6), ("Nom", 20), ("Mots-clés", 28), ("Pays", 16), ("Prix", 16),
                             ("Format", 11), ("État", 9), ("Exclus", 30)):
            searches.add_column(label, width=width)

        targets = self.query_one("#target-table", DataTable)
        for label, width in (("Cible", 28), ("État", 14), ("Dernier contrôle", 16), ("Annonces", 8),
                             ("Nouvelles", 9), ("Détail", 60)):
            targets.add_column(label, width=width)

        for listing in self.store.recent_listings(FEED_LIMIT):
            self.feed.append(listing)
        self._refresh_feed()
        self._refresh_searches()
        self._rebuild_targets()
        self.set_interval(1.0, self._refresh_status)
        self._log("info", f"Configuration : {self.config.path or '(mémoire)'}")
        if self.autostart and any(s.enabled for s in self.config.searches):
            self.call_after_refresh(self.action_toggle_engine)
        elif not self.config.searches:
            self._log("info", "Aucune recherche : appuie sur A pour en ajouter une.")
        self._refresh_status()

    _MAIN_SCREEN_ONLY = {
        "toggle_engine", "add_search", "edit_search", "delete_search", "toggle_search", "open_listing",
        "settings", "reload", "test_notifications", "show_tab", "quit", "api_setup",
    }

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # Ignore main-screen shortcuts while a dialog is open.
        if action in self._MAIN_SCREEN_ONLY and len(self.screen_stack) > 1:
            return False
        return True

    # --------------------------------------------------------------- helpers
    def _log(self, level: str, message: str) -> None:
        style = {"warning": "yellow", "error": "bold red"}.get(level, "")
        stamp = datetime.now().strftime("%H:%M:%S")
        self.query_one("#log-view", RichLog).write(Text(f"{stamp}  {message}", style=style))

    def _refresh_status(self) -> None:
        running = self.runtime is not None and self.runtime.engine.running
        engine = self.runtime.engine if self.runtime else None
        n = self.config.notifications
        parts = [
            Text("● EN COURS" if running else "■ ARRÊTÉ", style="bold green" if running else "bold red"),
            Text(f"   {sum(1 for s in self.config.searches if s.enabled)}/{len(self.config.searches)} recherches"),
            Text(f"   {len(self.targets)} cibles"),
            Text(f"   {engine.requests if engine else 0} requêtes"),
            Text(f"   {self.session_new} nouvelles", style="bold"),
            Text("   source : API officielle" if self.config.effective_backend == "api" else "   source : pages eBay",
                 style="green" if self.config.effective_backend == "api" else ""),
            Text(f"   toutes les {int(engine.interval) if engine else self.config.general.interval_seconds} s"),
            Text("   Discord ✓" if n.discord_webhook_url else "   Discord ✗",
                 style="green" if n.discord_webhook_url else "dim"),
            Text("   Telegram ✓" if n.telegram_bot_token and n.telegram_chat_id else "   Telegram ✗",
                 style="green" if n.telegram_bot_token and n.telegram_chat_id else "dim"),
        ]
        self.query_one("#status", Static).update(Text.assemble(*parts))

    def _refresh_feed(self) -> None:
        table = self.query_one("#feed-table", DataTable)
        cursor = table.cursor_row
        table.clear()
        for index, listing in enumerate(reversed(self.feed)):
            market = get_market(listing.market)
            kind = "Enchère" if listing.is_auction else "Achat imm."
            table.add_row(
                listing.found_at.astimezone().strftime("%H:%M:%S"),
                market.code.upper(),
                Text(listing.search_name),
                Text(listing.title),
                Text(listing.display_price, style="bold"),
                Text(listing.shipping_text),
                kind,
                key=str(index),
            )
        if table.row_count:
            table.move_cursor(row=min(cursor, table.row_count - 1))

    def _refresh_searches(self) -> None:
        table = self.query_one("#search-table", DataTable)
        cursor = table.cursor_row
        table.clear()
        for s in self.config.searches:
            if s.min_price is not None or s.max_price is not None:
                low = f"{s.min_price:g}" if s.min_price is not None else "0"
                high = f"{s.max_price:g}" if s.max_price is not None else "∞"
                price = f"{low}–{high} {s.currency}"
            else:
                price = "—"
            table.add_row(
                Text("✔", style="green") if s.enabled else Text("✘", style="red"),
                Text(s.name),
                Text(s.keywords),
                " ".join(c.upper() for c in s.countries),
                price,
                _BUYING_LABEL[s.buying_format.value],
                {"all": "Tous", "new": "Neuf", "used": "Occasion"}[s.condition.value],
                Text(", ".join(s.exclude)),
                key=s.key,
            )
        if table.row_count:
            table.move_cursor(row=min(cursor, table.row_count - 1))

    def _rebuild_targets(self) -> None:
        if self.runtime is not None:
            self.targets = {(t.search.key, t.market.code): t for t in self.runtime.engine.targets}
        else:
            self.targets = {
                (s.key, code): Target(search=s, market=get_market(code))
                for s in self.config.searches if s.enabled for code in s.countries
            }
        self._refresh_targets()

    def _refresh_targets(self) -> None:
        table = self.query_one("#target-table", DataTable)
        table.clear()
        for target in self.targets.values():
            last = target.last_check.astimezone().strftime("%H:%M:%S") if target.last_check else "—"
            table.add_row(
                Text(target.label),
                Text(target.state.value, style=_STATE_STYLE[target.state]),
                last,
                str(target.last_count),
                str(target.new_total),
                Text(target.message),
            )

    def _selected_search(self) -> Search | None:
        table = self.query_one("#search-table", DataTable)
        if not self.config.searches or table.row_count == 0:
            return None
        row = max(0, min(table.cursor_row, len(self.config.searches) - 1))
        return self.config.searches[row]

    def _save_config(self) -> bool:
        try:
            if self.config.path is not None:
                self.config.save()
            return True
        except (ConfigError, OSError) as exc:
            self.notify(f"Sauvegarde impossible : {exc}", severity="error", markup=False)
            return False

    # ---------------------------------------------------------------- engine
    def _on_engine_event(self, event: Event) -> None:
        self.post_message(EngineMessage(event))

    @on(EngineMessage)
    def _handle_engine_message(self, message: EngineMessage) -> None:
        event = message.event
        if isinstance(event, NewListing):
            self.session_new += 1
            self.feed.append(event.listing)
            self._refresh_feed()
            listing = event.listing
            self.notify(f"{listing.title}\n{listing.display_price}", title=f"🆕 {listing.search_name}",
                        timeout=8, markup=False)
            if self.config.notifications.sound:
                self.bell()
        elif isinstance(event, TargetUpdated):
            self._refresh_targets()
            if (event.target.state is TargetState.BLOCKED and self.config.effective_backend == "html"
                    and not self._block_hint_shown):
                self._block_hint_shown = True
                message = ("eBay bloque la lecture de ses pages depuis ta connexion (403).\n"
                           "Solution fiable : l'API officielle eBay, gratuite. Appuie sur K pour la configurer.")
                self.notify(message, title="eBay bloque les requêtes", severity="error", timeout=60, markup=False)
                self._log("error", message.replace("\n", " "))
        elif isinstance(event, LogEvent):
            self._log(event.level, event.message)

    async def _start_engine(self) -> None:
        if self.runtime is not None:
            return
        try:
            source = self.source_factory(self.config) if self.source_factory else None
            self.runtime = build_runtime(
                self.config,
                on_event=self._on_engine_event,
                on_notify_error=lambda msg: self.post_message(EngineMessage(LogEvent("warning", msg))),
                store=self.store,
                source=source,
            )
        except (ValueError, ConfigError) as exc:
            self.notify(str(exc), severity="error", markup=False)
            self._log("error", str(exc))
            self.runtime = None
            return
        self._rebuild_targets()
        await self.runtime.engine.start()
        self._refresh_status()

    async def _stop_engine(self) -> None:
        runtime, self.runtime = self.runtime, None
        if runtime is not None:
            await runtime.aclose()
        self._rebuild_targets()
        self._refresh_status()

    async def _restart_if_running(self) -> None:
        was_running = self.runtime is not None
        await self._stop_engine()
        if was_running:
            await self._start_engine()

    # ---------------------------------------------------------------- actions
    async def action_toggle_engine(self) -> None:
        if self.runtime is None:
            if not any(s.enabled for s in self.config.searches):
                self.notify("Aucune recherche active (onglet ② Recherches, touche A ou T).", severity="warning")
                return
            await self._start_engine()
        else:
            await self._stop_engine()

    def action_show_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    @work(exclusive=True, group="dialog")
    async def action_add_search(self) -> None:
        result = await self.push_screen_wait(SearchFormScreen(None, {s.key for s in self.config.searches}))
        if result is None:
            return
        self.config.searches.append(result)
        if self._save_config():
            self.notify(f"Recherche « {result.name} » ajoutée", markup=False)
        self._refresh_searches()
        await self._restart_if_running()

    @work(exclusive=True, group="dialog")
    async def action_edit_search(self) -> None:
        search = self._selected_search()
        if search is None:
            self.notify("Sélectionne une recherche dans l'onglet ② Recherches", severity="warning")
            self.action_show_tab("searches")
            return
        result = await self.push_screen_wait(SearchFormScreen(search, {s.key for s in self.config.searches}))
        if result is None:
            return
        index = self.config.searches.index(search)
        self.config.searches[index] = result
        if result.key != search.key or result.keywords != search.keywords or result.countries != search.countries:
            # Different query: start from a fresh baseline to avoid a burst of old listings.
            self.store.reset_search(result.key)
        self._save_config()
        self._refresh_searches()
        await self._restart_if_running()

    @work(exclusive=True, group="dialog")
    async def action_delete_search(self) -> None:
        search = self._selected_search()
        if search is None:
            return
        if not await self.push_screen_wait(ConfirmScreen(f"Supprimer la recherche « {search.name} » ?")):
            return
        self.config.searches.remove(search)
        self.store.reset_search(search.key)
        self._save_config()
        self._refresh_searches()
        await self._restart_if_running()

    async def action_toggle_search(self) -> None:
        search = self._selected_search()
        if search is None:
            return
        search.enabled = not search.enabled
        self._save_config()
        self._refresh_searches()
        await self._restart_if_running()

    @work(exclusive=True, group="dialog")
    async def action_settings(self) -> None:
        data = await self.push_screen_wait(SettingsScreen(self.config))
        if data is None:
            return
        path = self.config.path
        self.config = Config.from_dict(data, path)
        self._save_config()
        self.notify("Paramètres enregistrés")
        await self._restart_if_running()
        self._refresh_status()

    @work(exclusive=True, group="dialog")
    async def action_api_setup(self) -> None:
        data = await self.push_screen_wait(ApiSetupScreen(self.config))
        if data is None:
            return
        self.config = Config.from_dict(data, self.config.path)
        self._save_config()
        self._block_hint_shown = False
        self.notify("Clés API enregistrées : le bot utilise maintenant l'API officielle eBay.")
        await self._restart_if_running()
        if self.runtime is None and any(s.enabled for s in self.config.searches):
            await self._start_engine()
        self._refresh_status()

    async def action_reload(self) -> None:
        if self.config.path is None:
            return
        try:
            new_config = Config.load(self.config.path)
        except ConfigError as exc:
            self.notify(str(exc), severity="error", timeout=10, markup=False)
            self._log("error", str(exc))
            return
        self.config = new_config
        self._refresh_searches()
        await self._restart_if_running()
        self._rebuild_targets()
        self.notify("Configuration rechargée depuis le fichier")

    def _listing_under_cursor(self) -> Listing | None:
        table = self.query_one("#feed-table", DataTable)
        if not self.feed or table.row_count == 0:
            return None
        items = list(reversed(self.feed))
        return items[max(0, min(table.cursor_row, len(items) - 1))]

    def action_open_listing(self) -> None:
        listing = self._listing_under_cursor()
        if listing is None:
            return
        try:
            webbrowser.open(listing.url, new=2)
        except Exception:  # noqa: BLE001 - fall back to Textual (works over SSH too)
            self.open_url(listing.url)

    @on(DataTable.RowSelected, "#feed-table")
    def _feed_row_selected(self) -> None:
        self.action_open_listing()

    @on(DataTable.RowSelected, "#search-table")
    def _search_row_selected(self) -> None:
        self.action_edit_search()

    @work(exclusive=True, group="notif-test")
    async def action_test_notifications(self) -> None:
        import httpx

        listing = Listing(item_id="0", market="fr", title="Test eBay Watcher — tout fonctionne ✅",
                          url="https://www.ebay.fr", price=1.0, currency="EUR", search_name="test")
        async with httpx.AsyncClient(timeout=15) as client:
            notifiers = build_notifiers(self.config.notifications, client)
            if not notifiers:
                self.notify("Aucun canal configuré (touche P)", severity="warning")
                return
            for notifier in notifiers:
                try:
                    await notifier.send(listing)
                    self.notify(f"{notifier.name} : OK ✅")
                except Exception as exc:  # noqa: BLE001
                    self.notify(f"{notifier.name} : {exc}", severity="error", markup=False)

    async def action_quit(self) -> None:
        await self._stop_engine()
        self.store.close()
        self.exit()


def run_tui(config_path: Path, autostart: bool = True) -> None:
    config = Config.load(config_path)
    EbayWatchApp(config, autostart=autostart).run()
