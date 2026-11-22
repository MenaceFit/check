"""Official eBay Browse API backend (optional, needs free developer keys).

Docs: https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search
"""

from __future__ import annotations

import asyncio
import base64
import time
from datetime import datetime

import httpx

from ..config import Config, Search
from ..markets import Market
from ..models import BuyingFormat, Condition, Listing
from .base import BlockedSourceError, SourceError

API_ROOT = "https://api.ebay.com"
TOKEN_PATH = "/identity/v1/oauth2/token"
SEARCH_PATH = "/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def build_api_params(search: Search, market: Market, config: Config) -> dict[str, str]:
    filters: list[str] = []
    if search.buying_format is BuyingFormat.BUY_IT_NOW:
        filters.append("buyingOptions:{FIXED_PRICE}")
    elif search.buying_format is BuyingFormat.AUCTION:
        filters.append("buyingOptions:{AUCTION}")
    if search.condition is Condition.NEW:
        filters.append("conditions:{NEW}")
    elif search.condition is Condition.USED:
        filters.append("conditions:{USED}")
    if search.min_price is not None or search.max_price is not None:
        low = config.convert(search.min_price, search.currency, market.currency) if search.min_price else None
        high = config.convert(search.max_price, search.currency, market.currency) if search.max_price else None
        low_s = f"{low * 0.9:.2f}" if low is not None else ""
        high_s = f"{high * 1.1:.2f}" if high is not None else ""
        filters.append(f"price:[{low_s}..{high_s}]")
        filters.append(f"priceCurrency:{market.currency}")
    params = {"q": search.keywords, "sort": "newlyListed", "limit": "50"}
    if search.category_id:
        params["category_ids"] = search.category_id
    if filters:
        params["filter"] = ",".join(filters)
    return params


class ApiSource:
    name = "api"

    def __init__(self, config: Config, client: httpx.AsyncClient | None = None, api_root: str = API_ROOT) -> None:
        if not config.api.configured:
            raise ValueError("client_id / client_secret manquants pour le backend API")
        self.config = config
        self.api_root = api_root.rstrip("/")
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(config.general.request_timeout))
        self._token: str | None = None
        self._token_expiry = 0.0
        self._lock = asyncio.Lock()

    async def _get_token(self, force: bool = False) -> str:
        async with self._lock:
            if not force and self._token and time.monotonic() < self._token_expiry - 60:
                return self._token
            creds = f"{self.config.api.client_id}:{self.config.api.client_secret}".encode()
            try:
                response = await self._client.post(
                    self.api_root + TOKEN_PATH,
                    headers={
                        "Authorization": "Basic " + base64.b64encode(creds).decode(),
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={"grant_type": "client_credentials", "scope": SCOPE},
                )
            except httpx.HTTPError as exc:
                raise SourceError(f"API eBay : échec de l'authentification ({exc.__class__.__name__})") from exc
            if response.status_code != 200:
                raise SourceError(
                    f"API eBay : identifiants refusés (HTTP {response.status_code})", status=response.status_code
                )
            payload = response.json()
            self._token = payload["access_token"]
            self._token_expiry = time.monotonic() + float(payload.get("expires_in", 7200))
            return self._token

    async def search(self, search: Search, market: Market) -> list[Listing]:
        params = build_api_params(search, market, self.config)
        for attempt in range(2):
            token = await self._get_token(force=attempt > 0)
            try:
                response = await self._client.get(
                    self.api_root + SEARCH_PATH,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-EBAY-C-MARKETPLACE-ID": market.marketplace_id,
                        "Accept-Language": market.language.split(",")[0],
                    },
                )
            except httpx.HTTPError as exc:
                raise SourceError(f"API eBay : erreur réseau ({exc.__class__.__name__})") from exc
            if response.status_code == 401 and attempt == 0:
                continue   # token expired/revoked: refresh once
            break
        status = response.status_code
        if status == 429:
            raise BlockedSourceError("API eBay : quota d'appels atteint (429)", status=429)
        if status >= 400:
            raise SourceError(f"API eBay : HTTP {status} — {response.text[:200]}", status=status)
        return [self._to_listing(item, market) for item in response.json().get("itemSummaries", []) or []]

    @staticmethod
    def _to_listing(item: dict, market: Market) -> Listing:
        legacy = str(item.get("legacyItemId") or "")
        if not legacy:
            parts = str(item.get("itemId", "")).split("|")
            legacy = parts[1] if len(parts) > 1 else str(item.get("itemId", ""))
        price = item.get("price") or item.get("currentBidPrice") or {}
        value = price.get("value")
        shipping = ""
        options = item.get("shippingOptions") or []
        if options:
            cost = options[0].get("shippingCost") or {}
            if cost.get("value") is not None:
                shipping = f"+{cost['value']} {cost.get('currency', '')} livraison".strip()
        location = item.get("itemLocation") or {}
        buying = item.get("buyingOptions") or []
        return Listing(
            item_id=legacy,
            market=market.code,
            title=item.get("title", "").strip(),
            url=market.item_url(legacy),
            price=float(value) if value is not None else None,
            currency=price.get("currency") or market.currency,
            price_text=f"{value} {price.get('currency', '')}".strip() if value is not None else "",
            shipping_text=shipping,
            image_url=(item.get("image") or {}).get("imageUrl"),
            subtitle=item.get("condition", "") or "",
            location_text=", ".join(x for x in (location.get("city"), location.get("country")) if x),
            is_auction="AUCTION" in buying,
            bids=item.get("bidCount"),
            created_at=_parse_dt(item.get("itemCreationDate")),
        )

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()
