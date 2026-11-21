"""Modèles de données : configuration d'une recherche et annonce normalisée."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

DISPLAY_FIELDS = {
    "price": "Prix",
    "location": "Localisation",
    "date": "Date de publication",
    "latency": "Délai de détection",
    "seller": "Vendeur",
    "category": "Catégorie",
    "shipping": "Livraison",
    "description": "Description",
    "attributes": "Caractéristiques",
    "image": "Grande image",
    "thumbnail": "Miniature",
}
DEFAULT_DISPLAY = ["price", "location", "date", "latency", "seller", "shipping", "image"]


class Location(BaseModel):
    type: Literal["city", "department", "region"] = "city"
    label: str = ""
    city: str = ""
    zipcode: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    radius_km: Optional[float] = None
    default_radius: Optional[int] = None
    department_id: str = ""
    region_id: str = ""


class ExtraFilter(BaseModel):
    """Champ personnalisé : n'importe quel filtre Leboncoin (enum ou plage)."""

    key: str
    kind: Literal["enum", "range"] = "enum"
    values: list[str] = Field(default_factory=list)
    min: Optional[float] = None
    max: Optional[float] = None


class SearchConfig(BaseModel):
    name: str = "Nouvelle recherche"
    enabled: bool = True

    # --- Filtres envoyés à Leboncoin ---
    keywords: str = ""
    title_only: bool = False
    category: str = ""
    locations: list[Location] = Field(default_factory=list)
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    owner_type: Literal["all", "private", "pro"] = "all"
    shippable_only: bool = False
    extra_filters: list[ExtraFilter] = Field(default_factory=list)

    # --- Filtres appliqués localement (après réception) ---
    exclude_words: list[str] = Field(default_factory=list)
    required_words: list[str] = Field(default_factory=list)
    required_mode: Literal["all", "any"] = "any"
    max_age_minutes: Optional[int] = None

    # --- Discord ---
    discord_channel_id: str = ""
    webhook_url: str = ""
    mention: str = ""
    embed_color: str = "#ff6e14"
    display_fields: list[str] = Field(default_factory=lambda: list(DEFAULT_DISPLAY))

    # --- Moteur ---
    interval_seconds: int = 30
    notify_existing_on_start: bool = False
    limit: int = 35

    @field_validator("exclude_words", "required_words", mode="before")
    @classmethod
    def _split_words(cls, v):
        if isinstance(v, str):
            v = [w for w in (x.strip() for x in v.replace("\n", ",").split(",")) if w]
        return v

    @field_validator("display_fields")
    @classmethod
    def _known_fields(cls, v):
        return [f for f in v if f in DISPLAY_FIELDS]

    @field_validator("limit")
    @classmethod
    def _limit(cls, v):
        return max(1, min(int(v), 100))

    @field_validator("embed_color")
    @classmethod
    def _color(cls, v):
        v = (v or "#ff6e14").strip()
        if not v.startswith("#"):
            v = "#" + v
        try:
            int(v[1:7], 16)
        except ValueError:
            return "#ff6e14"
        return v[:7]


class Ad(BaseModel):
    list_id: str
    title: str
    url: str
    price: Optional[float] = None
    published_at: Optional[datetime] = None
    body: str = ""
    city: str = ""
    zipcode: str = ""
    department: str = ""
    region: str = ""
    category: str = ""
    owner_type: str = ""
    owner_name: str = ""
    images: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)
    shippable: Optional[bool] = None

    @property
    def price_label(self) -> str:
        if self.price is None:
            return "Prix non indiqué"
        if float(self.price).is_integer():
            return f"{int(self.price):,} €".replace(",", " ")
        return f"{self.price:,.2f} €".replace(",", " ").replace(".", ",")

    @property
    def location_label(self) -> str:
        parts = [p for p in (self.city, self.zipcode) if p]
        label = " ".join(parts)
        if self.department and self.department not in label:
            label = f"{label} ({self.department})" if label else self.department
        return label or "—"
