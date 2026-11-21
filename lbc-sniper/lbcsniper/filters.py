"""Filtres appliqués localement sur chaque annonce reçue."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

from .models import Ad, SearchConfig


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower())


def _contains(haystack: str, word: str) -> bool:
    w = _norm(word).strip()
    if not w:
        return False
    # Mot entier si le terme est alphanumérique, sinon simple sous-chaîne.
    if re.fullmatch(r"[\w ]+", w):
        return re.search(rf"(?<!\w){re.escape(w)}(?!\w)", haystack) is not None
    return w in haystack


def check_ad(ad: Ad, cfg: SearchConfig, now: datetime | None = None) -> tuple[bool, str]:
    """Renvoie (accepté, raison du rejet)."""
    text = _norm(f"{ad.title} {ad.body}")

    for w in cfg.exclude_words:
        if _contains(text, w):
            return False, f"mot exclu « {w} »"

    if cfg.required_words:
        hits = [_contains(text, w) for w in cfg.required_words]
        if cfg.required_mode == "all" and not all(hits):
            return False, "il manque un mot obligatoire"
        if cfg.required_mode == "any" and not any(hits):
            return False, "aucun mot obligatoire"

    if ad.price is not None:
        if cfg.price_min is not None and ad.price < cfg.price_min:
            return False, "prix trop bas"
        if cfg.price_max is not None and ad.price > cfg.price_max:
            return False, "prix trop élevé"

    if cfg.owner_type == "private" and ad.owner_type == "Professionnel":
        return False, "vendeur pro"
    if cfg.owner_type == "pro" and ad.owner_type == "Particulier":
        return False, "vendeur particulier"

    if cfg.shippable_only and ad.shippable is False:
        return False, "pas de livraison"

    if cfg.max_age_minutes and ad.published_at:
        now = now or datetime.now(timezone.utc)
        age = (now - ad.published_at).total_seconds() / 60
        if age > cfg.max_age_minutes:
            return False, "annonce trop ancienne"

    return True, ""
