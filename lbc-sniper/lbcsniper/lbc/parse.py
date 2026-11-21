"""Normalisation des annonces brutes renvoyées par Leboncoin (API JSON ou page HTML)."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from ..models import Ad

PARIS = ZoneInfo("Europe/Paris")
_HIDDEN_ATTRIBUTES = {
    "shipping_type", "estimated_parcel_weight", "estimated_parcel_size", "is_bundleable",
    "purchase_cta_visible", "negotiation_cta_visible", "country_isocode3166", "payment_methods",
    "stock_quantity", "rating_score", "rating_count", "profile_picture_url", "is_import",
}
_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE
)


def parse_lbc_date(value: Any) -> datetime | None:
    """Les dates Leboncoin sont au format « 2026-11-21 13:45:12 », heure de Paris."""
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt).replace(tzinfo=PARIS)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=PARIS)
    except ValueError:
        return None


def _truthy(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"true", "1", "yes", "oui"}:
            return True
        if s in {"false", "0", "no", "non"}:
            return False
    return None


def normalize_ad(raw: dict) -> Ad | None:
    list_id = raw.get("list_id") or raw.get("id")
    if not list_id:
        return None
    list_id = str(list_id)

    price = None
    p = raw.get("price")
    if isinstance(p, list) and p:
        price = p[0]
    elif isinstance(p, (int, float)):
        price = p
    if price is None and isinstance(raw.get("price_cents"), (int, float)):
        price = raw["price_cents"] / 100

    images: list[str] = []
    imgs = raw.get("images") or {}
    if isinstance(imgs, dict):
        for key in ("urls_large", "urls", "urls_thumb"):
            if imgs.get(key):
                images = list(imgs[key])
                break
        if not images:
            for key in ("small_url", "thumb_url"):
                if imgs.get(key):
                    images = [imgs[key]]
                    break

    attributes: dict[str, str] = {}
    shippable: bool | None = None
    for a in raw.get("attributes") or []:
        if not isinstance(a, dict):
            continue
        key = a.get("key", "")
        if key in ("shippable", "is_shippable"):
            shippable = _truthy(a.get("value"))
            continue
        if key == "shipping_type" and a.get("value"):
            shippable = True if shippable is None else shippable
        if key in _HIDDEN_ATTRIBUTES:
            continue
        # On n'affiche que les attributs « lisibles » (avec un libellé humain).
        label = a.get("key_label")
        value = a.get("value_label")
        if label and value:
            attributes[str(label)] = str(value)
    if shippable is None:
        opts = raw.get("options") or {}
        if isinstance(opts, dict) and "shippable" in opts:
            shippable = _truthy(opts.get("shippable"))

    loc = raw.get("location") or {}
    owner = raw.get("owner") or {}
    owner_type = owner.get("type", "")
    category = raw.get("category_name") or ""
    url = raw.get("url") or f"https://www.leboncoin.fr/ad/{raw.get('category_id', 'annonce')}/{list_id}"

    return Ad(
        list_id=list_id,
        title=(raw.get("subject") or raw.get("title") or "Sans titre").strip(),
        url=url,
        price=price,
        published_at=parse_lbc_date(raw.get("first_publication_date") or raw.get("index_date")),
        body=(raw.get("body") or "").strip(),
        city=loc.get("city") or loc.get("city_label") or "",
        zipcode=str(loc.get("zipcode") or ""),
        department=loc.get("department_name") or "",
        region=loc.get("region_name") or "",
        category=category,
        owner_type={"private": "Particulier", "pro": "Professionnel"}.get(owner_type, owner_type),
        owner_name=owner.get("name") or "",
        images=images,
        attributes=attributes,
        shippable=shippable,
    )


def _find_ad_lists(node: Any, depth: int = 0) -> Iterable[list]:
    """Cherche récursivement une liste d'objets contenant 'list_id' (structure Next.js)."""
    if depth > 12:
        return
    if isinstance(node, list):
        if node and all(isinstance(x, dict) for x in node) and any("list_id" in x for x in node):
            yield node
            return
        for x in node:
            yield from _find_ad_lists(x, depth + 1)
    elif isinstance(node, dict):
        for v in node.values():
            yield from _find_ad_lists(v, depth + 1)


def ads_from_html(html: str) -> list[dict]:
    """Extrait les annonces du JSON __NEXT_DATA__ d'une page leboncoin.fr/recherche."""
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    try:
        ads = data["props"]["pageProps"]["searchData"]["ads"]
        if isinstance(ads, list):
            return ads
    except (KeyError, TypeError):
        pass
    best: list = []
    for lst in _find_ad_lists(data):
        if len(lst) > len(best):
            best = lst
    return best
