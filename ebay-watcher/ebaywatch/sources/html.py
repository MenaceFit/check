"""Scraping backend: reads eBay's public search result pages."""

from __future__ import annotations

import math
from urllib.parse import urlencode

import httpx

from ..config import Config, Search
from ..markets import Market
from ..models import BuyingFormat, Condition, Listing
from ..parser import BlockedError, parse_search_page
from .base import BlockedSourceError, SourceError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

SORT_NEWLY_LISTED = "10"
_CONDITION_PARAM = {Condition.NEW: "1000|1500", Condition.USED: "3000"}


def build_search_params(search: Search, market: Market, config: Config) -> dict[str, str]:
    params: dict[str, str] = {
        "_nkw": search.keywords,
        "_sop": SORT_NEWLY_LISTED,
        "_ipg": str(config.general.results_per_page),
        "rt": "nc",
    }
    if search.category_id:
        params["_sacat"] = search.category_id
    if search.buying_format is BuyingFormat.BUY_IT_NOW:
        params["LH_BIN"] = "1"
    elif search.buying_format is BuyingFormat.AUCTION:
        params["LH_Auction"] = "1"
    if search.condition in _CONDITION_PARAM:
        params["LH_ItemCondition"] = _CONDITION_PARAM[search.condition]
    # Server-side price range, converted to the site's currency and widened a bit
    # (rates are approximate): the exact filter is re-applied client-side.
    if search.min_price is not None:
        low = config.convert(search.min_price, search.currency, market.currency) * 0.9
        params["_udlo"] = str(max(0, math.floor(low)))
    if search.max_price is not None:
        high = config.convert(search.max_price, search.currency, market.currency) * 1.1
        params["_udhi"] = str(math.ceil(high))
    return params


def build_search_url(search: Search, market: Market, config: Config, base_url: str | None = None) -> str:
    base = (base_url or market.base_url).rstrip("/")
    return f"{base}/sch/i.html?{urlencode(build_search_params(search, market, config))}"


class HtmlSource:
    name = "html"

    def __init__(
        self,
        config: Config,
        client: httpx.AsyncClient | None = None,
        base_url_override: dict[str, str] | None = None,
    ) -> None:
        self.config = config
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(config.general.request_timeout),
            follow_redirects=True,
            http2=False,
        )
        self._override = base_url_override or {}
        self.last_html: dict[str, str] = {}      # market code -> last page body (for diagnostics)

    def _headers(self, market: Market) -> dict[str, str]:
        return {
            "User-Agent": self.config.general.user_agent or DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": market.language,
            "Upgrade-Insecure-Requests": "1",
        }

    async def search(self, search: Search, market: Market) -> list[Listing]:
        url = build_search_url(search, market, self.config, self._override.get(market.code))
        try:
            response = await self._client.get(url, headers=self._headers(market))
        except httpx.TimeoutException as exc:
            raise SourceError(f"délai dépassé ({market.host})") from exc
        except httpx.HTTPError as exc:
            raise SourceError(f"erreur réseau ({market.host}) : {exc.__class__.__name__}") from exc

        status = response.status_code
        final_url = str(response.url)
        if status in (403, 429) or "splashui" in final_url:
            raise BlockedSourceError(
                f"eBay a refusé la requête ({status}) — trop de requêtes ou IP bloquée", status=status
            )
        if status >= 400:
            raise SourceError(f"HTTP {status} sur {market.host}", status=status)
        self.last_html[market.code] = response.text
        try:
            result = parse_search_page(response.text, market)
        except BlockedError as exc:
            raise BlockedSourceError(str(exc), status=status) from exc
        return result.listings

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()
