"""Modal screens: search form, settings, confirmation."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, SelectionList, Static, Switch
from textual.widgets.selection_list import Selection

from ..config import DEFAULT_RATES_TO_EUR, Config, ConfigError, Search
from ..markets import MARKETS

BUYING_OPTIONS = [("Tous formats", "all"), ("Achat immédiat", "bin"), ("Enchères", "auction")]
CONDITION_OPTIONS = [("Tous états", "all"), ("Neuf", "new"), ("Occasion", "used")]
CURRENCY_OPTIONS = [(c, c) for c in DEFAULT_RATES_TO_EUR]


def _fmt_number(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else str(value)


def _parse_optional_number(raw: str, label: str) -> float | None:
    raw = raw.strip().replace(",", ".").replace(" ", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{label} : « {raw} » n'est pas un nombre") from None


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [("escape", "dismiss(False)", "Annuler"), ("y", "dismiss(True)", "Oui"), ("o", "dismiss(True)", "Oui")]

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Grid(id="confirm-dialog", classes="dialog"):
            yield Label(self.question, id="confirm-question")
            yield Button("Oui", variant="error", id="yes")
            yield Button("Non", variant="primary", id="no")

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class SearchFormScreen(ModalScreen[Search | None]):
    """Create or edit a search."""

    BINDINGS = [("escape", "cancel", "Annuler"), ("ctrl+s", "save", "Enregistrer")]

    def __init__(self, search: Search | None, existing_names: set[str]) -> None:
        super().__init__()
        self.search = search
        # Names already used by *other* searches (case-insensitive).
        self.existing = {n for n in existing_names if not search or n != search.key}

    def compose(self) -> ComposeResult:
        s = self.search
        title = "Modifier la recherche" if s else "Nouvelle recherche"
        countries = set(s.countries) if s else {"fr"}
        with VerticalScroll(id="search-form", classes="dialog form"):
            yield Static(title, classes="dialog-title")
            yield Label("Nom (affiché dans les alertes)")
            yield Input(value=s.name if s else "", placeholder="ex : Switch OLED pas chère", id="f-name")
            yield Label("Mots-clés eBay *  (syntaxe eBay acceptée : -mot, \"phrase exacte\")")
            yield Input(value=s.keywords if s else "", placeholder="ex : nintendo switch oled", id="f-keywords")
            yield Label("Pays à surveiller *  (Espace pour cocher)")
            yield SelectionList[str](
                *(Selection(f"{m.code.upper()} — {m.name} ({m.host})", m.code, m.code in countries)
                  for m in MARKETS.values()),
                id="f-countries",
            )
            with Horizontal(classes="row"):
                with VerticalScroll(classes="col"):
                    yield Label("Prix min")
                    yield Input(value=_fmt_number(s.min_price) if s else "", placeholder="vide = aucun", id="f-min")
                with VerticalScroll(classes="col"):
                    yield Label("Prix max")
                    yield Input(value=_fmt_number(s.max_price) if s else "", placeholder="vide = aucun", id="f-max")
                with VerticalScroll(classes="col"):
                    yield Label("Devise des prix")
                    yield Select(CURRENCY_OPTIONS, value=s.currency if s else "EUR", allow_blank=False, id="f-currency")
            yield Label("Mots exclus (séparés par des virgules)")
            yield Input(value=", ".join(s.exclude) if s else "", placeholder="ex : boite vide, coque, hs", id="f-exclude")
            with Horizontal(classes="row"):
                with VerticalScroll(classes="col"):
                    yield Label("Format")
                    yield Select(BUYING_OPTIONS, value=s.buying_format.value if s else "all", allow_blank=False,
                                 id="f-buying")
                with VerticalScroll(classes="col"):
                    yield Label("État")
                    yield Select(CONDITION_OPTIONS, value=s.condition.value if s else "all", allow_blank=False,
                                 id="f-condition")
                with VerticalScroll(classes="col"):
                    yield Label("Catégorie eBay (n°, optionnel)")
                    yield Input(value=s.category_id if s else "", placeholder="ex : 139971", id="f-category")
            with Horizontal(classes="row switch-row"):
                yield Label("Active ")
                yield Switch(value=s.enabled if s else True, id="f-enabled")
            yield Static("", id="form-error", classes="error")
            with Horizontal(classes="buttons"):
                yield Button("Enregistrer (Ctrl+S)", variant="success", id="save")
                yield Button("Annuler (Échap)", variant="default", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#f-keywords" if not self.search else "#f-name", Input).focus()

    def _collect(self) -> Search:
        keywords = self.query_one("#f-keywords", Input).value.strip()
        name = self.query_one("#f-name", Input).value.strip() or keywords
        countries = list(self.query_one("#f-countries", SelectionList).selected)
        if not keywords:
            raise ConfigError("Les mots-clés sont obligatoires")
        if not countries:
            raise ConfigError("Coche au moins un pays")
        data = {
            "name": name,
            "keywords": keywords,
            "countries": countries,
            "min_price": _parse_optional_number(self.query_one("#f-min", Input).value, "Prix min"),
            "max_price": _parse_optional_number(self.query_one("#f-max", Input).value, "Prix max"),
            "currency": self.query_one("#f-currency", Select).value,
            "exclude": self.query_one("#f-exclude", Input).value,
            "buying_format": self.query_one("#f-buying", Select).value,
            "condition": self.query_one("#f-condition", Select).value,
            "category_id": self.query_one("#f-category", Input).value.strip(),
            "enabled": self.query_one("#f-enabled", Switch).value,
        }
        search = Search.from_dict(data)
        if search.key in self.existing:
            raise ConfigError(f"Une recherche s'appelle déjà « {search.name} »")
        return search

    def action_save(self) -> None:
        try:
            search = self._collect()
        except ConfigError as exc:
            self.query_one("#form-error", Static).update(f"⚠ {exc}")
            return
        self.dismiss(search)

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.action_cancel()


class SettingsScreen(ModalScreen[dict | None]):
    """Edit [general], [api] and [notifications]. Returns the new raw config dict."""

    BINDINGS = [("escape", "cancel", "Annuler"), ("ctrl+s", "save", "Enregistrer")]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        g = self.config.general
        n = self.config.notifications
        with VerticalScroll(id="settings-form", classes="dialog form"):
            yield Static("Paramètres", classes="dialog-title")
            with Horizontal(classes="row"):
                with VerticalScroll(classes="col"):
                    yield Label("Intervalle (secondes, ≥ 15)")
                    yield Input(value=str(g.interval_seconds), id="s-interval")
                with VerticalScroll(classes="col"):
                    yield Label("Annonces lues par page")
                    yield Select([("60", 60), ("120", 120), ("240", 240)], value=g.results_per_page,
                                 allow_blank=False, id="s-ipg")
                with VerticalScroll(classes="col"):
                    yield Label("Source")
                    yield Select([("Pages eBay (html)", "html"), ("API officielle (api)", "api")], value=g.backend,
                                 allow_blank=False, id="s-backend")
            with Horizontal(classes="row switch-row"):
                yield Label("Tous les mots-clés dans le titre ")
                yield Switch(value=g.strict_title_match, id="s-strict")
                yield Label("   Bip sonore ")
                yield Switch(value=n.sound, id="s-sound")
            yield Static("Discord", classes="section")
            yield Label("URL du webhook")
            yield Input(value=n.discord_webhook_url, placeholder="https://discord.com/api/webhooks/…", id="s-discord")
            yield Static("Telegram", classes="section")
            with Horizontal(classes="row"):
                with VerticalScroll(classes="col wide"):
                    yield Label("Token du bot")
                    yield Input(value=n.telegram_bot_token, password=True, placeholder="123456:ABC…", id="s-tg-token")
                with VerticalScroll(classes="col"):
                    yield Label("Chat ID")
                    yield Input(value=n.telegram_chat_id, placeholder="123456789", id="s-tg-chat")
            yield Static("API eBay officielle (seulement si Source = api)", classes="section")
            with Horizontal(classes="row"):
                with VerticalScroll(classes="col"):
                    yield Label("Client ID (App ID)")
                    yield Input(value=self.config.api.client_id, id="s-api-id")
                with VerticalScroll(classes="col"):
                    yield Label("Client Secret (Cert ID)")
                    yield Input(value=self.config.api.client_secret, password=True, id="s-api-secret")
            yield Static("", id="settings-error", classes="error")
            with Horizontal(classes="buttons"):
                yield Button("Enregistrer (Ctrl+S)", variant="success", id="save")
                yield Button("Annuler (Échap)", id="cancel")

    def _collect(self) -> dict:
        data = self.config.to_dict()
        interval_raw = self.query_one("#s-interval", Input).value.strip()
        try:
            interval = int(interval_raw)
        except ValueError:
            raise ConfigError(f"Intervalle : « {interval_raw} » n'est pas un nombre entier") from None
        data["general"].update(
            interval_seconds=interval,
            results_per_page=int(self.query_one("#s-ipg", Select).value),
            backend=self.query_one("#s-backend", Select).value,
            strict_title_match=self.query_one("#s-strict", Switch).value,
        )
        data["notifications"]["sound"] = self.query_one("#s-sound", Switch).value
        discord = self.query_one("#s-discord", Input).value.strip()
        if discord and not discord.startswith(("https://discord.com/api/webhooks/",
                                               "https://discordapp.com/api/webhooks/",
                                               "https://ptb.discord.com/api/webhooks/",
                                               "https://canary.discord.com/api/webhooks/")):
            raise ConfigError("L'URL Discord doit commencer par https://discord.com/api/webhooks/")
        data["notifications"]["discord"]["webhook_url"] = discord
        data["notifications"]["telegram"]["bot_token"] = self.query_one("#s-tg-token", Input).value.strip()
        data["notifications"]["telegram"]["chat_id"] = self.query_one("#s-tg-chat", Input).value.strip()
        data["api"]["client_id"] = self.query_one("#s-api-id", Input).value.strip()
        data["api"]["client_secret"] = self.query_one("#s-api-secret", Input).value.strip()
        Config.from_dict(data)   # full validation, raises ConfigError
        return data

    def action_save(self) -> None:
        try:
            data = self._collect()
        except ConfigError as exc:
            self.query_one("#settings-error", Static).update(f"⚠ {exc}")
            return
        self.dismiss(data)

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.action_cancel()
