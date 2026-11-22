"""Soak test: many targets over real HTTP, random new listings -> each one alerted exactly once."""

import asyncio
import random

import httpx

from ebaywatch.config import Config
from ebaywatch.engine import Engine, NewListing
from ebaywatch.notifiers import DiscordNotifier, Dispatcher
from ebaywatch.sources.html import HtmlSource
from ebaywatch.store import Store

from .conftest import scard_page

COUNTRIES = ["fr", "uk", "de", "it", "es", "us"]


async def test_soak_no_miss_no_duplicate(fake_ebay, tmp_path):
    rng = random.Random(1234)
    searches = [{"name": f"S{i}", "keywords": f"produit{i}", "countries": COUNTRIES} for i in range(4)]
    config = Config.from_dict({"general": {"min_delay_per_host": 0, "max_concurrency": 6}, "searches": searches})

    # One page per (market); every page holds items for all searches, newest first.
    live: dict[str, list[dict]] = {c: [] for c in COUNTRIES}
    next_id = [226100000000]

    def publish(market: str, search_index: int) -> str:
        next_id[0] += 1
        iid = str(next_id[0])
        live[market].insert(0, {"id": iid, "title": f"produit{search_index} annonce {iid}", "price": "50,00 EUR"})
        del live[market][60:]                      # eBay shows only the first page
        return iid

    def render() -> None:
        for c in COUNTRIES:
            fake_ebay.pages[c] = scard_page(live[c])

    for c in COUNTRIES:                             # pre-existing listings (must stay silent)
        for _ in range(30):
            publish(c, rng.randrange(4))
    render()

    http = httpx.AsyncClient()
    source = HtmlSource(config, base_url_override={c: fake_ebay.url_for(c) for c in COUNTRIES})
    dispatcher = Dispatcher([DiscordNotifier(f"{fake_ebay.base_url}/discord/x", http)])
    alerts: list[str] = []

    def on_event(event):
        if isinstance(event, NewListing):
            alerts.append(event.listing.item_id)

    engine = Engine(config, source, Store(tmp_path / "soak.db"), dispatcher, on_event=on_event,
                    interval=0.25, min_delay_per_host=0, jitter=0.2)
    published: list[str] = []
    await engine.start()
    try:
        await asyncio.sleep(1.0)                    # baselines
        assert alerts == []
        for _ in range(40):                         # ~4 s of random activity
            for _ in range(rng.randrange(0, 4)):
                published.append(publish(rng.choice(COUNTRIES), rng.randrange(4)))
            render()
            await asyncio.sleep(0.1)
        await asyncio.sleep(1.5)                    # let every target do a final pass
        await dispatcher.drain(10)
    finally:
        await engine.stop()
        await dispatcher.stop()
        await source.aclose()
        await http.aclose()

    assert len(published) > 30
    # Each listing is matched by exactly one search (titles contain "produitN").
    assert sorted(alerts) == sorted(published), "missed or duplicated alerts"
    assert len(fake_ebay.discord_posts) == len(published)
    assert engine.requests > 100
    errors = [t for t in engine.targets if t.failures]
    assert not errors
