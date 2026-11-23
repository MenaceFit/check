"""eBay marketplaces (one per country) and their properties."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Market:
    code: str            # short code used in the config file ("fr", "uk", ...)
    name: str            # human readable name
    host: str            # web host, e.g. "www.ebay.fr"
    currency: str        # ISO currency of the site
    language: str        # Accept-Language header value
    marketplace_id: str  # Browse API X-EBAY-C-MARKETPLACE-ID
    flag: str            # emoji flag for display

    @property
    def base_url(self) -> str:
        return f"https://{self.host}"

    def item_url(self, item_id: str) -> str:
        return f"{self.base_url}/itm/{item_id}"


_MARKETS: tuple[Market, ...] = (
    Market("fr", "France", "www.ebay.fr", "EUR", "fr-FR,fr;q=0.9,en;q=0.6", "EBAY_FR", "🇫🇷"),
    Market("uk", "Royaume-Uni", "www.ebay.co.uk", "GBP", "en-GB,en;q=0.9", "EBAY_GB", "🇬🇧"),
    Market("de", "Allemagne", "www.ebay.de", "EUR", "de-DE,de;q=0.9,en;q=0.6", "EBAY_DE", "🇩🇪"),
    Market("it", "Italie", "www.ebay.it", "EUR", "it-IT,it;q=0.9,en;q=0.6", "EBAY_IT", "🇮🇹"),
    Market("es", "Espagne", "www.ebay.es", "EUR", "es-ES,es;q=0.9,en;q=0.6", "EBAY_ES", "🇪🇸"),
    Market("us", "États-Unis", "www.ebay.com", "USD", "en-US,en;q=0.9", "EBAY_US", "🇺🇸"),
    Market("be", "Belgique (FR)", "www.befr.ebay.be", "EUR", "fr-BE,fr;q=0.9,en;q=0.6", "EBAY_BE", "🇧🇪"),
    Market("nl", "Pays-Bas", "www.ebay.nl", "EUR", "nl-NL,nl;q=0.9,en;q=0.6", "EBAY_NL", "🇳🇱"),
    Market("at", "Autriche", "www.ebay.at", "EUR", "de-AT,de;q=0.9,en;q=0.6", "EBAY_AT", "🇦🇹"),
    Market("ch", "Suisse", "www.ebay.ch", "CHF", "de-CH,de;q=0.9,fr;q=0.8,en;q=0.6", "EBAY_CH", "🇨🇭"),
    Market("ie", "Irlande", "www.ebay.ie", "EUR", "en-IE,en;q=0.9", "EBAY_IE", "🇮🇪"),
    Market("pl", "Pologne", "www.ebay.pl", "PLN", "pl-PL,pl;q=0.9,en;q=0.6", "EBAY_PL", "🇵🇱"),
    Market("ca", "Canada", "www.ebay.ca", "CAD", "en-CA,en;q=0.9,fr;q=0.8", "EBAY_CA", "🇨🇦"),
    Market("au", "Australie", "www.ebay.com.au", "AUD", "en-AU,en;q=0.9", "EBAY_AU", "🇦🇺"),
)

MARKETS: dict[str, Market] = {m.code: m for m in _MARKETS}

# Accepted aliases in the config file.
_ALIASES = {
    "gb": "uk", "en": "uk", "england": "uk", "angleterre": "uk", "royaume-uni": "uk",
    "france": "fr", "allemagne": "de", "germany": "de", "italie": "it", "italy": "it",
    "espagne": "es", "spain": "es", "usa": "us", "com": "us", "belgique": "be",
}


def get_market(code: str) -> Market:
    key = code.strip().lower()
    key = _ALIASES.get(key, key)
    try:
        return MARKETS[key]
    except KeyError:
        valid = ", ".join(MARKETS)
        raise ValueError(f"Pays inconnu « {code} ». Pays valides : {valid}") from None


def normalize_market_code(code: str) -> str:
    return get_market(code).code
