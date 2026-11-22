"""End-to-end: real HTTP server (fake eBay + fake Discord/Telegram), real httpx, real SQLite."""

import asyncio

import httpx

from ebaywatch.config import Config
from ebaywatch.engine import Engine, NewListing, TargetState
from ebaywatch.notifiers import DiscordNotifier, Dispatcher, TelegramNotifier
from ebaywatch.sources.html import HtmlSource
from ebaywatch.store import Store

from .conftest import scard_page


def item(i: int, title: str, price: str = "150,00 EUR", host: str = "www.ebay.fr") -> dict:
    return {"id": str(226000000000 + i), "title": title, "price": price, "host": host}


async def wait_for(predicate, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached in time")


async def test_end_to_end_multi_country(fake_ebay, tmp_path):
    config = Config.from_dict({
        "general": {"interval_seconds": 60, "min_delay_per_host": 0},
        "searches": [
            {"name": "Switch OLED", "keywords": "switch oled", "countries": ["fr", "uk", "de"],
             "max_price": 300, "exclude": ["boite vide"]},
        ],
    })
    fake_ebay.pages["fr"] = scard_page([item(3, "Switch OLED blanche"), item(2, "Switch OLED rouge")])
    fake_ebay.pages["uk"] = scard_page([item(10, "Switch OLED white", "£200.00", "www.ebay.co.uk")])
    fake_ebay.pages["de"] = scard_page([])

    http = httpx.AsyncClient()
    source = HtmlSource(config, base_url_override={c: fake_ebay.url_for(c) for c in ("fr", "uk", "de")})
    dispatcher = Dispatcher([
        DiscordNotifier(f"{fake_ebay.base_url}/discord/webhook", http),
        TelegramNotifier("123:ABC", "42", http, api_root=fake_ebay.base_url),
    ])
    store = Store(tmp_path / "e2e.db")
    events = []
    engine = Engine(config, source, store, dispatcher, on_event=events.append, interval=0.15,
                    min_delay_per_host=0, jitter=0)
    await engine.start()
    try:
        # 1) Baseline on every country: existing listings must NOT be notified.
        await wait_for(lambda: all(t.state is TargetState.BASELINE for t in engine.targets))
        assert fake_ebay.discord_posts == []

        # 2) New listings appear on eBay France and Germany.
        fake_ebay.pages["fr"] = scard_page([
            item(6, "Switch OLED boite vide", "20,00 EUR"),     # excluded word
            item(5, "Switch OLED Zelda", "420,00 EUR"),         # too expensive
            item(4, "Switch OLED neuve sous blister", "289,00 EUR"),
            item(3, "Switch OLED blanche"), item(2, "Switch OLED rouge"),
        ], rewrite_after=[item(99, "Manette sans rapport")])
        fake_ebay.pages["de"] = scard_page([item(20, "Switch OLED Weiß", "199,00 EUR", "www.ebay.de")])
        await wait_for(lambda: len(fake_ebay.discord_posts) == 2 and len(fake_ebay.telegram_posts) >= 2)

        titles = sorted(p["embeds"][0]["title"] for p in fake_ebay.discord_posts)
        assert titles == ["Switch OLED Weiß", "Switch OLED neuve sous blister"]

        # 3) Nothing else for a few cycles (no duplicate alerts).
        await asyncio.sleep(0.6)
        assert len(fake_ebay.discord_posts) == 2
    finally:
        await engine.stop()
        await dispatcher.stop()
        await source.aclose()
        await http.aclose()

    new_events = [e.listing for e in events if isinstance(e, NewListing)]
    assert sorted(l.item_id for l in new_events) == ["226000000004", "226000000020"]
    de = next(l for l in new_events if l.market == "de")
    assert de.url == "https://www.ebay.de/itm/226000000020"
    assert de.image_url == "https://i.ebayimg.com/images/g/226000000020/s-l500.webp"

    # Request shape actually sent over the wire.
    fr_requests = [r for r in fake_ebay.requests if r["market"] == "fr"]
    q = fr_requests[0]["query"]
    assert q["_nkw"] == ["switch oled"] and q["_sop"] == ["10"] and q["_udhi"] == ["330"]
    assert fr_requests[0]["headers"]["Accept-Language"].startswith("fr-FR")
    uk_q = next(r for r in fake_ebay.requests if r["market"] == "uk")["query"]
    assert uk_q["_udhi"] == ["283"]                          # 300 EUR converted to GBP (+10 %)

    # Telegram used the photo endpoint.
    assert all(p["path"].endswith("/sendPhoto") for p in fake_ebay.telegram_posts)

    # 4) Restart: the database remembers everything -> no alert burst.
    store.close()
    store2 = Store(tmp_path / "e2e.db")
    assert store2.count_listings() == 2
    source2 = HtmlSource(config, base_url_override={c: fake_ebay.url_for(c) for c in ("fr", "uk", "de")})
    engine2 = Engine(config, source2, store2, None, interval=0.1, min_delay_per_host=0, jitter=0)
    results = await engine2.run_once()
    await source2.aclose()
    assert all(v == [] for v in results.values()), results


async def test_end_to_end_blocked_then_recovers(fake_ebay, tmp_path):
    config = Config.from_dict({"general": {"min_delay_per_host": 0},
                               "searches": [{"name": "S", "keywords": "lego", "countries": ["fr"]}]})
    fake_ebay.status["fr"] = 403
    source = HtmlSource(config, base_url_override={"fr": fake_ebay.url_for("fr")})
    engine = Engine(config, source, Store(":memory:"), None, interval=0.1, min_delay_per_host=0, jitter=0)
    results = await engine.run_once()
    assert "refusé" in str(results["S [FR]"])
    fake_ebay.status["fr"] = 200
    fake_ebay.pages["fr"] = scard_page([item(1, "Lego Technic")])
    results = await engine.run_once()
    assert results["S [FR]"] == []                      # baseline after recovery
    fake_ebay.pages["fr"] = scard_page([item(2, "Lego Star Wars"), item(1, "Lego Technic")])
    results = await engine.run_once()
    assert [l.title for l in results["S [FR]"]] == ["Lego Star Wars"]
    await source.aclose()


async def test_end_to_end_search_evo_layout_over_http(fake_ebay):
    """The newest eBay layout served over real HTTP, then a new card appears on top."""
    from .conftest import fixture_text

    config = Config.from_dict({"general": {"min_delay_per_host": 0},
                               "searches": [{"name": "OLED", "keywords": "switch oled", "countries": ["uk"]}]})
    page = fixture_text("ebay_uk_search_evo.html")
    fake_ebay.pages["uk"] = page
    source = HtmlSource(config, base_url_override={"uk": fake_ebay.url_for("uk")})
    engine = Engine(config, source, Store(":memory:"), None, interval=0.1, min_delay_per_host=0, jitter=0)
    assert (await engine.run_once())["OLED [UK]"] == []            # baseline: 2 listings memorised
    new_card = ('<div class="su-item-card s-item-card--search-evo"><a href="https://www.ebay.co.uk/itm/406999999999">'
                '<h3 class="su-item-card__title"><span>Switch OLED Mario edition</span></h3></a>'
                '<span class="su-item-card__price">£230.00</span></div>')
    fake_ebay.pages["uk"] = page.replace('<div class="srp-river-main">', '<div class="srp-river-main">' + new_card, 1)
    [listing] = (await engine.run_once())["OLED [UK]"]
    await source.aclose()
    assert listing.item_id == "406999999999" and listing.price == 230.0 and listing.currency == "GBP"
