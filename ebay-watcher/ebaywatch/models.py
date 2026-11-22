"""Core data structures."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum


class BuyingFormat(str, Enum):
    ALL = "all"
    BUY_IT_NOW = "bin"
    AUCTION = "auction"


class Condition(str, Enum):
    ALL = "all"
    NEW = "new"
    USED = "used"


@dataclass(slots=True)
class Listing:
    item_id: str
    market: str                 # market code ("fr", "uk", ...)
    title: str
    url: str
    price: float | None = None
    currency: str | None = None
    price_text: str = ""
    shipping_text: str = ""
    image_url: str | None = None
    subtitle: str = ""          # condition / short description shown by eBay
    location_text: str = ""
    is_auction: bool = False
    bids: int | None = None
    created_at: datetime | None = None   # only known with the API backend
    found_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    search_name: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        for key in ("created_at", "found_at"):
            if d[key] is not None:
                d[key] = d[key].isoformat()
        return d

    @property
    def display_price(self) -> str:
        if self.price is None:
            return self.price_text or "?"
        symbol = {"EUR": "€", "GBP": "£", "USD": "$", "CHF": "CHF ", "CAD": "C$", "AUD": "A$", "PLN": "zł "}.get(
            self.currency or "", f"{self.currency} " if self.currency else ""
        )
        amount = f"{self.price:,.2f}".replace(",", " ")
        if symbol in ("€",):
            return f"{amount.replace('.', ',')} €"
        return f"{symbol}{amount}"
