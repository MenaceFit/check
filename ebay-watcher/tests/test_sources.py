import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from ebaywatch.config import Config, Search
from ebaywatch.markets import get_market
from ebaywatch.sources.api import ApiSource, build_api_params
from ebaywatch.sources.base import BlockedSourceError, SourceError
from ebaywatch.sources.html import HtmlSource, build_search_url

from .conftest import fixture_text, make_config


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


# ------------------------------------------------------------------ URL building
def test_search_url_basic():
    config = make_config()
    search = Search.from_dict({"keywords": "nintendo switch oled", "countries": ["fr"]})
    url = build_search_url(search, get_market("fr"), config)
    assert url.startswith("https://www.ebay.fr/sch/i.html?")
    q = _query(url)
    assert q == {"_nkw": "nintendo switch oled", "_sop": "10", "_ipg": "60", "rt": "nc"}


def test_search_url_filters_and_currency_conversion():
    config = make_config()
    search = Search.from_dict({
        "keywords": "ps5", "countries": ["uk"], "min_price": 100, "max_price": 300, "currency": "EUR",
        "buying_format": "bin", "condition": "used", "category_id": "139971",
    })
    q = _query(build_search_url(search, get_market("uk"), config))
    assert q["LH_BIN"] == "1"
    assert q["LH_ItemCondition"] == "3000"
    assert q["_sacat"] == "139971"
    # 100 EUR ≈ 85 GBP, widened by 10 % -> 76 ; 300 EUR ≈ 256 GBP * 1.1 -> 283
    assert q["_udlo"] == "76"
    assert q["_udhi"] == "283"


def test_search_url_auction_new():
    config = make_config()
    search = Search.from_dict({"keywords": "x", "buying_format": "auction", "condition": "new"})
    q = _query(build_search_url(search, get_market("de"), config))
    assert q["LH_Auction"] == "1" and "LH_BIN" not in q
    assert q["LH_ItemCondition"] == "1000|1500"


# ------------------------------------------------------------------ HTML source
def _html_source(handler) -> HtmlSource:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    return HtmlSource(make_config(), client=client)


async def test_html_source_parses_and_sends_locale_headers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.url.host
        seen["lang"] = request.headers["accept-language"]
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, text=fixture_text("ebay_uk_sitem.html"))

    source = _html_source(handler)
    listings = await source.search(Search.from_dict({"keywords": "ps5"}), get_market("uk"))
    assert [l.item_id for l in listings] == ["296543210987", "176655443322"]
    assert seen["host"] == "www.ebay.co.uk"
    assert seen["lang"].startswith("en-GB")
    assert "Mozilla/5.0" in seen["ua"]


@pytest.mark.parametrize("status", [403, 429])
async def test_html_source_blocked_status(status):
    source = _html_source(lambda r: httpx.Response(status, text="nope"))
    with pytest.raises(BlockedSourceError):
        await source.search(Search.from_dict({"keywords": "x"}), get_market("fr"))


async def test_html_source_challenge_page():
    source = _html_source(lambda r: httpx.Response(200, text=fixture_text("ebay_challenge.html")))
    with pytest.raises(BlockedSourceError):
        await source.search(Search.from_dict({"keywords": "x"}), get_market("fr"))


async def test_html_source_redirect_to_splash_is_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/splashui"):
            return httpx.Response(200, text="<html>checking your browser</html>")
        return httpx.Response(302, headers={"Location": "https://www.ebay.fr/splashui/challenge?x=1"})

    with pytest.raises(BlockedSourceError):
        await _html_source(handler).search(Search.from_dict({"keywords": "x"}), get_market("fr"))


async def test_html_source_server_error():
    source = _html_source(lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(SourceError) as info:
        await source.search(Search.from_dict({"keywords": "x"}), get_market("fr"))
    assert not isinstance(info.value, BlockedSourceError)
    assert info.value.status == 500


async def test_html_source_network_error():
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(SourceError, match="réseau"):
        await _html_source(handler).search(Search.from_dict({"keywords": "x"}), get_market("fr"))


async def test_html_source_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(SourceError, match="délai"):
        await _html_source(handler).search(Search.from_dict({"keywords": "x"}), get_market("fr"))


# ------------------------------------------------------------------- API source
def _api_config() -> Config:
    return Config.from_dict({"general": {"backend": "api"}, "api": {"client_id": "id", "client_secret": "sec"}})


API_ITEMS = {
    "total": 2,
    "itemSummaries": [
        {
            "itemId": "v1|226789012345|0", "legacyItemId": "226789012345",
            "title": "Nintendo Switch OLED", "price": {"value": "249.00", "currency": "EUR"},
            "image": {"imageUrl": "https://i.ebayimg.com/images/g/a/s-l225.jpg"},
            "itemWebUrl": "https://www.ebay.fr/itm/226789012345?tracking=1",
            "condition": "Occasion", "buyingOptions": ["FIXED_PRICE", "BEST_OFFER"],
            "itemCreationDate": "2026-11-22T10:15:30.000Z",
            "itemLocation": {"city": "Lyon", "country": "FR"},
            "shippingOptions": [{"shippingCost": {"value": "8.90", "currency": "EUR"}}],
        },
        {
            "itemId": "v1|389012345678|0", "title": "Switch OLED rouge",
            "currentBidPrice": {"value": "120.50", "currency": "EUR"}, "buyingOptions": ["AUCTION"],
            "bidCount": 4,
        },
    ],
}


async def test_api_source_token_cache_and_parsing():
    calls = {"token": 0, "search": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            calls["token"] += 1
            assert request.headers["authorization"].startswith("Basic ")
            assert b"grant_type=client_credentials" in request.content
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
        calls["search"] += 1
        assert request.headers["authorization"] == "Bearer tok"
        assert request.headers["x-ebay-c-marketplace-id"] == "EBAY_FR"
        assert request.url.params["sort"] == "newlyListed"
        return httpx.Response(200, json=API_ITEMS)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    source = ApiSource(_api_config(), client=client)
    search = Search.from_dict({"keywords": "switch oled"})
    first = await source.search(search, get_market("fr"))
    await source.search(search, get_market("fr"))
    assert calls == {"token": 1, "search": 2}

    a, b = first
    assert a.item_id == "226789012345" and a.price == 249.0 and a.currency == "EUR"
    assert a.url == "https://www.ebay.fr/itm/226789012345"
    assert a.shipping_text == "+8.90 EUR livraison"
    assert a.location_text == "Lyon, FR"
    assert a.created_at is not None and a.created_at.year == 2026
    assert not a.is_auction
    assert b.item_id == "389012345678" and b.price == 120.5 and b.is_auction and b.bids == 4


async def test_api_source_refreshes_token_on_401():
    tokens = iter(["old", "new"])
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": next(tokens), "expires_in": 7200})
        seen_auth.append(request.headers["authorization"])
        if request.headers["authorization"] == "Bearer old":
            return httpx.Response(401, json={})
        return httpx.Response(200, json={"itemSummaries": []})

    source = ApiSource(_api_config(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await source.search(Search.from_dict({"keywords": "x"}), get_market("de")) == []
    assert seen_auth == ["Bearer old", "Bearer new"]


async def test_api_source_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
        return httpx.Response(429, json={})

    source = ApiSource(_api_config(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(BlockedSourceError):
        await source.search(Search.from_dict({"keywords": "x"}), get_market("fr"))

    bad = ApiSource(_api_config(), client=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "invalid_client"}))))
    with pytest.raises(SourceError, match="identifiants"):
        await bad.search(Search.from_dict({"keywords": "x"}), get_market("fr"))


def test_api_params_filters():
    config = _api_config()
    search = Search.from_dict({"keywords": "ps5", "min_price": 100, "max_price": 200, "buying_format": "auction",
                               "condition": "new", "category_id": "139971"})
    params = build_api_params(search, get_market("uk"), config)
    assert params["q"] == "ps5" and params["sort"] == "newlyListed" and params["category_ids"] == "139971"
    f = params["filter"]
    assert "buyingOptions:{AUCTION}" in f and "conditions:{NEW}" in f and "priceCurrency:GBP" in f
    assert "price:[" in f and ".." in f
    json.dumps(params)
