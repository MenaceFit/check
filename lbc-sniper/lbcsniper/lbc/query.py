"""Conversion entre URL de recherche Leboncoin, configuration et requête API.

Le plus simple pour l'utilisateur : faire sa recherche sur leboncoin.fr, copier l'URL,
la coller dans le dashboard. Tous les paramètres (y compris les filtres spécifiques à une
catégorie : kilométrage, état, marque...) sont convertis en « champs personnalisés ».
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, quote, urlencode, urlparse

from ..models import ExtraFilter, Location, SearchConfig

# Paramètres d'URL qui ne sont pas des filtres.
_IGNORED = {"page", "sort", "order", "kst", "from", "c", "u_car_brand", "u_car_model"}
_RANGE_RE = re.compile(r"^(min|-?\d+(?:\.\d+)?)?-(max|-?\d+(?:\.\d+)?)?$")


def _num(s: str | None):
    if s in (None, "", "min", "max"):
        return None
    f = float(s)
    return int(f) if f.is_integer() else f


def parse_range(value: str):
    m = _RANGE_RE.match(value.strip())
    if not m:
        return None
    return _num(m.group(1)), _num(m.group(2))


def parse_location(token: str) -> Location | None:
    token = token.strip()
    if not token:
        return None
    if re.fullmatch(r"d_\w+", token):
        return Location(type="department", department_id=token[2:], label=f"Département {token[2:]}")
    if re.fullmatch(r"r_\w+", token):
        return Location(type="region", region_id=token[2:], label=f"Région {token[2:]}")
    # Ville : "Paris__48.86_2.33_9256_10000" ou "Lyon_69003__45.75_4.82_5000"
    if "__" in token:
        name_part, coords = token.split("__", 1)
        city, _, zipcode = name_part.partition("_")
        nums = coords.split("_")
        loc = Location(type="city", city=city.replace("-", " ") if city else "", zipcode=zipcode)
        try:
            loc.lat = float(nums[0])
            loc.lng = float(nums[1])
            if len(nums) > 2 and nums[2]:
                loc.default_radius = int(float(nums[2]))
            if len(nums) > 3 and nums[3]:
                loc.radius_km = round(float(nums[3]) / 1000, 1)
        except (ValueError, IndexError):
            pass
        loc.label = f"{loc.city} {loc.zipcode}".strip()
        return loc
    return Location(type="city", city=token, label=token)


def config_from_url(url: str, base: SearchConfig | None = None) -> SearchConfig:
    """Crée (ou complète) une configuration à partir d'une URL leboncoin.fr/recherche?..."""
    parsed = urlparse(url.strip())
    params = dict(parse_qsl(parsed.query, keep_blank_values=False))
    cfg = (base or SearchConfig()).model_copy(deep=True)
    cfg.extra_filters = []
    cfg.locations = []

    if "text" in params:
        cfg.keywords = params.pop("text")
        if not base or base.name in ("", "Nouvelle recherche"):
            cfg.name = cfg.keywords[:60] or cfg.name
    if params.pop("search_in", "") == "subject":
        cfg.title_only = True
    if "category" in params:
        cfg.category = params.pop("category")
    if "locations" in params:
        for tok in params.pop("locations").split(","):
            loc = parse_location(tok)
            if loc:
                cfg.locations.append(loc)
    if "price" in params:
        rng = parse_range(params.pop("price"))
        if rng:
            cfg.price_min, cfg.price_max = (int(x) if x is not None else None for x in rng)
    owner = params.pop("owner_type", "")
    if owner in ("private", "pro"):
        cfg.owner_type = owner
    if params.pop("shippable", "") in ("1", "true"):
        cfg.shippable_only = True

    for key, value in params.items():
        if key in _IGNORED or not value:
            continue
        rng = parse_range(value)
        if rng and (rng[0] is not None or rng[1] is not None):
            cfg.extra_filters.append(ExtraFilter(key=key, kind="range", min=rng[0], max=rng[1]))
        else:
            cfg.extra_filters.append(
                ExtraFilter(key=key, kind="enum", values=[v for v in value.split(",") if v])
            )
    return cfg


def _location_payload(loc: Location) -> dict:
    if loc.type == "department":
        return {"locationType": "department", "department_id": loc.department_id}
    if loc.type == "region":
        return {"locationType": "region", "region_id": loc.region_id}
    item: dict = {"locationType": "city", "label": loc.label or loc.city, "city": loc.city}
    if loc.zipcode:
        item["zipcode"] = loc.zipcode
    if loc.lat is not None and loc.lng is not None:
        area: dict = {"lat": loc.lat, "lng": loc.lng}
        area["default_radius"] = loc.default_radius or 10000
        if loc.radius_km:
            area["radius"] = int(loc.radius_km * 1000)
        item["area"] = area
    return item


def build_payload(cfg: SearchConfig) -> dict:
    """Corps JSON pour l'API de recherche Leboncoin (tri du plus récent au plus ancien)."""
    filters: dict = {"enums": {"ad_type": ["offer"]}, "ranges": {}}
    if cfg.category:
        filters["category"] = {"id": str(cfg.category)}
    if cfg.keywords:
        kw: dict = {"text": cfg.keywords}
        if cfg.title_only:
            kw["type"] = "subject"
        filters["keywords"] = kw
    if cfg.locations:
        filters["location"] = {"locations": [_location_payload(l) for l in cfg.locations]}
    price: dict = {}
    if cfg.price_min is not None:
        price["min"] = cfg.price_min
    if cfg.price_max is not None:
        price["max"] = cfg.price_max
    if price:
        filters["ranges"]["price"] = price
    if cfg.shippable_only:
        filters["enums"]["shippable"] = ["true"]
    for f in cfg.extra_filters:
        if not f.key:
            continue
        if f.kind == "range":
            r = {k: v for k, v in (("min", f.min), ("max", f.max)) if v is not None}
            if r:
                filters["ranges"][f.key] = r
        elif f.values:
            filters["enums"][f.key] = [str(v) for v in f.values]
    if not filters["ranges"]:
        del filters["ranges"]

    payload = {
        "limit": cfg.limit,
        "limit_alu": 0,
        "filters": filters,
        "sort_by": "time",
        "sort_order": "desc",
        "offset": 0,
    }
    if cfg.owner_type != "all":
        payload["owner_type"] = cfg.owner_type
    return payload


def _location_param(loc: Location) -> str:
    if loc.type == "department":
        return f"d_{loc.department_id}"
    if loc.type == "region":
        return f"r_{loc.region_id}"
    name = loc.city + (f"_{loc.zipcode}" if loc.zipcode else "")
    if loc.lat is None or loc.lng is None:
        return name
    parts = [str(loc.lat), str(loc.lng), str(loc.default_radius or 10000)]
    if loc.radius_km:
        parts.append(str(int(loc.radius_km * 1000)))
    return f"{name}__{'_'.join(parts)}"


def _fmt(v) -> str:
    if v is None:
        return ""
    return str(int(v)) if float(v).is_integer() else str(v)


def build_web_url(cfg: SearchConfig, base_url: str = "https://www.leboncoin.fr") -> str:
    """URL leboncoin.fr équivalente (lien « ouvrir sur Leboncoin » + mode HTML de secours)."""
    params: list[tuple[str, str]] = []
    if cfg.category:
        params.append(("category", str(cfg.category)))
    if cfg.keywords:
        params.append(("text", cfg.keywords))
    if cfg.title_only:
        params.append(("search_in", "subject"))
    if cfg.locations:
        params.append(("locations", ",".join(_location_param(l) for l in cfg.locations)))
    if cfg.price_min is not None or cfg.price_max is not None:
        lo = _fmt(cfg.price_min) if cfg.price_min is not None else "min"
        hi = _fmt(cfg.price_max) if cfg.price_max is not None else "max"
        params.append(("price", f"{lo}-{hi}"))
    if cfg.owner_type != "all":
        params.append(("owner_type", cfg.owner_type))
    if cfg.shippable_only:
        params.append(("shippable", "1"))
    for f in cfg.extra_filters:
        if f.kind == "range" and (f.min is not None or f.max is not None):
            lo = _fmt(f.min) if f.min is not None else "min"
            hi = _fmt(f.max) if f.max is not None else "max"
            params.append((f.key, f"{lo}-{hi}"))
        elif f.values:
            params.append((f.key, ",".join(f.values)))
    params += [("sort", "time"), ("order", "desc")]
    return f"{base_url}/recherche?{urlencode(params, quote_via=quote, safe=',_')}"
