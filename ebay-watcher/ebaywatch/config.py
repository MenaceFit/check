"""Configuration file (TOML) loading, validation and saving."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

from .markets import MARKETS, normalize_market_code
from .models import BuyingFormat, Condition

DEFAULT_CONFIG_NAME = "config.toml"
MIN_INTERVAL = 15

# Approximate conversion rates to EUR, used only for cross-country price filters.
DEFAULT_RATES_TO_EUR: dict[str, float] = {
    "EUR": 1.0, "GBP": 1.17, "USD": 0.92, "CHF": 1.05, "CAD": 0.67, "AUD": 0.60, "PLN": 0.23,
}


class ConfigError(ValueError):
    """Raised when the configuration file is invalid."""


def _as_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    raise ConfigError(f"« {field_name} » doit être une liste")


def _as_float(value: Any, field_name: str) -> float | None:
    if value in (None, "", 0, 0.0):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"« {field_name} » doit être un nombre (reçu {value!r})") from None
    if number < 0:
        raise ConfigError(f"« {field_name} » ne peut pas être négatif")
    return number


@dataclass(slots=True)
class Search:
    name: str
    keywords: str
    countries: list[str] = field(default_factory=lambda: ["fr"])
    min_price: float | None = None
    max_price: float | None = None
    currency: str = "EUR"
    exclude: list[str] = field(default_factory=list)
    buying_format: BuyingFormat = BuyingFormat.ALL
    condition: Condition = Condition.ALL
    category_id: str = ""
    enabled: bool = True

    @property
    def key(self) -> str:
        """Stable identifier used for de-duplication in the database."""
        return self.name.strip().casefold()

    @classmethod
    def from_dict(cls, data: dict[str, Any], index: int = 0) -> "Search":
        where = f"recherche n°{index + 1}"
        keywords = str(data.get("keywords", "")).strip()
        if not keywords:
            raise ConfigError(f"{where} : « keywords » est obligatoire")
        name = str(data.get("name") or keywords).strip()
        countries = _as_list(data.get("countries", ["fr"]), "countries") or ["fr"]
        try:
            countries = list(dict.fromkeys(normalize_market_code(c) for c in countries))
        except ValueError as exc:
            raise ConfigError(f"{where} ({name}) : {exc}") from None
        try:
            buying = BuyingFormat(str(data.get("buying_format", "all")).lower())
        except ValueError:
            raise ConfigError(f"{name} : buying_format doit être all, bin ou auction") from None
        try:
            condition = Condition(str(data.get("condition", "all")).lower())
        except ValueError:
            raise ConfigError(f"{name} : condition doit être all, new ou used") from None
        min_price = _as_float(data.get("min_price"), "min_price")
        max_price = _as_float(data.get("max_price"), "max_price")
        if min_price is not None and max_price is not None and min_price > max_price:
            raise ConfigError(f"{name} : min_price ({min_price}) > max_price ({max_price})")
        currency = str(data.get("currency", "EUR")).upper()
        if currency not in DEFAULT_RATES_TO_EUR:
            raise ConfigError(f"{name} : devise inconnue {currency}")
        category = str(data.get("category_id", "") or "").strip()
        if category and not category.isdigit():
            raise ConfigError(f"{name} : category_id doit être un nombre")
        return cls(
            name=name,
            keywords=keywords,
            countries=countries,
            min_price=min_price,
            max_price=max_price,
            currency=currency,
            exclude=_as_list(data.get("exclude"), "exclude"),
            buying_format=buying,
            condition=condition,
            category_id=category,
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "keywords": self.keywords,
            "countries": list(self.countries),
            "enabled": self.enabled,
            "buying_format": self.buying_format.value,
            "condition": self.condition.value,
            "currency": self.currency,
            "exclude": list(self.exclude),
        }
        if self.min_price is not None:
            d["min_price"] = self.min_price
        if self.max_price is not None:
            d["max_price"] = self.max_price
        if self.category_id:
            d["category_id"] = self.category_id
        return d


@dataclass(slots=True)
class GeneralSettings:
    interval_seconds: int = 60
    backend: str = "html"                 # "html" (scraping) or "api" (official Browse API)
    results_per_page: int = 60
    max_concurrency: int = 3
    min_delay_per_host: float = 2.0       # politeness delay between two requests to one host
    request_timeout: float = 20.0
    strict_title_match: bool = True       # every keyword must appear in the title
    notify_existing_on_start: bool = False
    # An unseen listing shown BELOW this many already-known listings is not new
    # (eBay sorts by newest first): it is a sponsored/promoted insertion. 0 = disabled.
    sponsored_guard: int = 3
    database: str = "ebaywatch.db"
    user_agent: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GeneralSettings":
        s = cls()
        try:
            s.interval_seconds = int(data.get("interval_seconds", s.interval_seconds))
            s.results_per_page = int(data.get("results_per_page", s.results_per_page))
            s.max_concurrency = int(data.get("max_concurrency", s.max_concurrency))
            s.min_delay_per_host = float(data.get("min_delay_per_host", s.min_delay_per_host))
            s.request_timeout = float(data.get("request_timeout", s.request_timeout))
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"[general] valeur numérique invalide : {exc}") from None
        s.backend = str(data.get("backend", s.backend)).lower()
        s.strict_title_match = bool(data.get("strict_title_match", s.strict_title_match))
        s.notify_existing_on_start = bool(data.get("notify_existing_on_start", s.notify_existing_on_start))
        try:
            s.sponsored_guard = int(data.get("sponsored_guard", s.sponsored_guard))
        except (TypeError, ValueError):
            raise ConfigError("[general] sponsored_guard doit être un nombre entier") from None
        if s.sponsored_guard < 0:
            raise ConfigError("[general] sponsored_guard ne peut pas être négatif")
        s.database = str(data.get("database", s.database))
        s.user_agent = str(data.get("user_agent", "") or "")
        if s.backend not in ("html", "api"):
            raise ConfigError("[general] backend doit être « html » ou « api »")
        if s.interval_seconds < MIN_INTERVAL:
            raise ConfigError(f"[general] interval_seconds doit être ≥ {MIN_INTERVAL}")
        if s.results_per_page not in (60, 120, 240):
            raise ConfigError("[general] results_per_page doit valoir 60, 120 ou 240")
        if not 1 <= s.max_concurrency <= 10:
            raise ConfigError("[general] max_concurrency doit être entre 1 et 10")
        return s

    def to_dict(self) -> dict[str, Any]:
        return {
            "interval_seconds": self.interval_seconds,
            "backend": self.backend,
            "results_per_page": self.results_per_page,
            "max_concurrency": self.max_concurrency,
            "min_delay_per_host": self.min_delay_per_host,
            "request_timeout": self.request_timeout,
            "strict_title_match": self.strict_title_match,
            "notify_existing_on_start": self.notify_existing_on_start,
            "sponsored_guard": self.sponsored_guard,
            "database": self.database,
            "user_agent": self.user_agent,
        }


@dataclass(slots=True)
class ApiSettings:
    client_id: str = ""
    client_secret: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


@dataclass(slots=True)
class NotificationSettings:
    sound: bool = True
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NotificationSettings":
        discord = data.get("discord", {}) or {}
        telegram = data.get("telegram", {}) or {}
        return cls(
            sound=bool(data.get("sound", True)),
            discord_webhook_url=str(discord.get("webhook_url", "") or "").strip(),
            telegram_bot_token=str(telegram.get("bot_token", "") or "").strip(),
            telegram_chat_id=str(telegram.get("chat_id", "") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sound": self.sound,
            "discord": {"webhook_url": self.discord_webhook_url},
            "telegram": {"bot_token": self.telegram_bot_token, "chat_id": self.telegram_chat_id},
        }


@dataclass(slots=True)
class Config:
    general: GeneralSettings = field(default_factory=GeneralSettings)
    api: ApiSettings = field(default_factory=ApiSettings)
    notifications: NotificationSettings = field(default_factory=NotificationSettings)
    searches: list[Search] = field(default_factory=list)
    rates_to_eur: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_RATES_TO_EUR))
    path: Path | None = None

    # ----------------------------------------------------------------- loading
    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Path | None = None) -> "Config":
        general = GeneralSettings.from_dict(data.get("general", {}) or {})
        api_data = data.get("api", {}) or {}
        api = ApiSettings(
            client_id=str(api_data.get("client_id", "") or os.environ.get("EBAY_CLIENT_ID", "")).strip(),
            client_secret=str(api_data.get("client_secret", "") or os.environ.get("EBAY_CLIENT_SECRET", "")).strip(),
        )
        if general.backend == "api" and not api.configured:
            raise ConfigError("backend = « api » mais [api] client_id / client_secret sont vides")
        notifications = NotificationSettings.from_dict(data.get("notifications", {}) or {})
        raw_searches = data.get("searches", []) or []
        if not isinstance(raw_searches, list):
            raise ConfigError("[[searches]] doit être une liste de recherches")
        searches = [Search.from_dict(s, i) for i, s in enumerate(raw_searches)]
        names = [s.key for s in searches]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ConfigError(f"Noms de recherche en double : {', '.join(sorted(dupes))}")
        rates = dict(DEFAULT_RATES_TO_EUR)
        for cur, rate in (data.get("rates_to_eur", {}) or {}).items():
            try:
                rates[str(cur).upper()] = float(rate)
            except (TypeError, ValueError):
                raise ConfigError(f"[rates_to_eur] taux invalide pour {cur}") from None
        return cls(general, api, notifications, searches, rates, path)

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "Config":
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"Fichier de configuration introuvable : {p}")
        try:
            with p.open("rb") as fh:
                data = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{p.name} : erreur de syntaxe TOML : {exc}") from None
        return cls.from_dict(data, p.resolve())

    # ----------------------------------------------------------------- saving
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "general": self.general.to_dict(),
            "api": {"client_id": self.api.client_id, "client_secret": self.api.client_secret},
            "notifications": self.notifications.to_dict(),
        }
        custom_rates = {k: v for k, v in self.rates_to_eur.items() if DEFAULT_RATES_TO_EUR.get(k) != v}
        if custom_rates:
            data["rates_to_eur"] = custom_rates
        data["searches"] = [s.to_dict() for s in self.searches]
        return data

    def save(self, path: str | os.PathLike[str] | None = None) -> Path:
        target = Path(path) if path else self.path
        if target is None:
            raise ConfigError("Aucun chemin de sauvegarde")
        # Validate what we are about to write by round-tripping it.
        Config.from_dict(self.to_dict())
        body = tomli_w.dumps(self.to_dict())
        header = (
            "# Configuration eBay Watcher — modifiable à la main ou depuis l'interface.\n"
            "# Documentation de chaque option : ebaywatch/data/config.example.toml et README.md\n\n"
        )
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(header + body, encoding="utf-8")
        os.replace(tmp, target)       # atomic on every OS
        self.path = target.resolve()
        return self.path

    # ----------------------------------------------------------------- helpers
    def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        if from_currency == to_currency:
            return amount
        src = self.rates_to_eur.get(from_currency)
        dst = self.rates_to_eur.get(to_currency)
        if not src or not dst:
            return amount
        return amount * src / dst

    def get_search(self, name: str) -> Search | None:
        key = name.strip().casefold()
        return next((s for s in self.searches if s.key == key), None)

    @property
    def database_path(self) -> Path:
        db = Path(self.general.database)
        if not db.is_absolute() and self.path is not None:
            db = self.path.parent / db
        return db


def all_market_codes() -> list[str]:
    return list(MARKETS)
