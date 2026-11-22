import asyncio

import pytest

from ebaywatch.config import Search
from ebaywatch.engine import Engine, HostLimiter, LogEvent, NewListing, TargetState, TargetUpdated
from ebaywatch.markets import Market
from ebaywatch.models import Listing
from ebaywatch.sources.base import BlockedSourceError, SourceError
from ebaywatch.store import Store

from .conftest import make_config


def L(item_id: str, title: str = "nintendo switch oled", price: float = 200.0, market: str = "fr") -> Listing:
    return Listing(item_id=item_id, market=market, title=title, url=f"https://x/itm/{item_id}", price=price,
                   currency="EUR")


class FakeSource:
    name = "fake"

    def __init__(self) -> None:
        self.pages: dict[str, list[Listing] | Exception] = {}
        self.calls: list[tuple[str, str]] = []

    async def search(self, search: Search, market: Market) -> list[Listing]:
        self.calls.append((search.name, market.code))
        page = self.pages.get(market.code, [])
        if isinstance(page, Exception):
            raise page
        # Return fresh copies like a real source would.
        return [Listing(**{**l.to_dict(), "found_at": l.found_at, "created_at": l.created_at}) for l in page]

    async def aclose(self) -> None:
        pass


class RecordingDispatcher:
    def __init__(self) -> None:
        self.items: list[Listing] = []

    def start(self) -> None:
        pass

    def submit(self, listing: Listing) -> None:
        self.items.append(listing)

    async def drain(self, timeout: float = 0) -> None:
        pass


def make_engine(searches=None, **general):
    config = make_config(searches, **general)
    source = FakeSource()
    dispatcher = RecordingDispatcher()
    events = []
    engine = Engine(config, source, Store(":memory:"), dispatcher, on_event=events.append, interval=0.05,
                    min_delay_per_host=0, jitter=0)
    return engine, source, dispatcher, events


async def test_baseline_then_detect_new():
    engine, source, dispatcher, events = make_engine()
    target = engine.targets[0]
    source.pages["fr"] = [L("3"), L("2"), L("1")]

    assert await engine.check_target(target) == []          # first run = baseline, no alert
    assert target.state is TargetState.BASELINE
    assert dispatcher.items == []

    source.pages["fr"] = [L("5"), L("4"), L("3"), L("2"), L("1")]
    new = await engine.check_target(target)
    assert [l.item_id for l in new] == ["4", "5"]          # chronological order (oldest first)
    assert [l.item_id for l in dispatcher.items] == ["4", "5"]
    assert all(l.search_name == "Switch" for l in new)
    assert target.state is TargetState.OK and target.new_total == 2

    assert await engine.check_target(target) == []          # nothing new the 3rd time
    assert sum(isinstance(e, NewListing) for e in events) == 2
    assert engine.store.count_listings() == 2


async def test_notify_existing_on_start():
    engine, source, dispatcher, _ = make_engine(notify_existing_on_start=True)
    source.pages["fr"] = [L("2"), L("1")]
    assert len(await engine.check_target(engine.targets[0])) == 2


async def test_filters_applied_and_rejected_not_renotified():
    searches = [{"name": "S", "keywords": "nintendo switch", "countries": ["fr"], "max_price": 250,
                 "exclude": ["boite vide"]}]
    engine, source, dispatcher, _ = make_engine(searches)
    target = engine.targets[0]
    await engine.check_target(target)                       # baseline (empty)
    source.pages["fr"] = [
        L("1", "Nintendo Switch OLED", 200),
        L("2", "Nintendo Switch OLED", 400),                # too expensive
        L("3", "Nintendo Switch boite vide", 20),           # excluded word
        L("4", "Manette Pro", 30),                          # keywords missing from title
        L("5", "NINTENDO SWITCH Lite turquoise", 150),      # case-insensitive match
    ]
    new = await engine.check_target(target)
    assert sorted(l.item_id for l in new) == ["1", "5"]
    assert await engine.check_target(target) == []


async def test_strict_title_match_can_be_disabled():
    engine, source, _, _ = make_engine(strict_title_match=False)
    target = engine.targets[0]
    await engine.check_target(target)
    source.pages["fr"] = [L("9", "Manette Pro")]
    assert [l.item_id for l in await engine.check_target(target)] == ["9"]


async def test_dedupe_across_countries():
    searches = [{"name": "S", "keywords": "switch", "countries": ["fr", "de"]}]
    engine, source, dispatcher, _ = make_engine(searches)
    fr, de = engine.targets
    await engine.check_target(fr)
    await engine.check_target(de)
    # The same international listing appears on both sites.
    source.pages["fr"] = [L("77", "switch oled")]
    source.pages["de"] = [L("77", "switch oled", market="de"), L("78", "switch lite", market="de")]
    assert [l.item_id for l in await engine.check_target(fr)] == ["77"]
    assert [l.item_id for l in await engine.check_target(de)] == ["78"]
    assert [l.item_id for l in dispatcher.items] == ["77", "78"]


async def test_new_country_gets_its_own_baseline():
    searches = [{"name": "S", "keywords": "switch", "countries": ["fr", "uk"]}]
    engine, source, dispatcher, _ = make_engine(searches)
    fr, uk = engine.targets
    await engine.check_target(fr)
    source.pages["uk"] = [L("50", "switch"), L("51", "switch")]
    assert await engine.check_target(uk) == []              # existing UK listings are not alerts
    assert dispatcher.items == []


async def test_run_loop_backoff_and_recovery():
    engine, source, dispatcher, events = make_engine()
    target = engine.targets[0]
    source.pages["fr"] = SourceError("HTTP 500")
    await engine.start()
    await asyncio.sleep(0.2)
    assert target.state is TargetState.ERROR and target.failures >= 1
    assert any(isinstance(e, LogEvent) and "HTTP 500" in e.message for e in events)
    source.pages["fr"] = [L("1")]
    await asyncio.sleep(0.6)                 # backoff 0.05, 0.1, 0.2 ... then recovers
    assert target.failures == 0
    assert target.state in (TargetState.BASELINE, TargetState.OK)
    source.pages["fr"] = [L("2"), L("1")]
    await asyncio.sleep(0.3)
    await engine.stop()
    assert [l.item_id for l in dispatcher.items] == ["2"]
    assert not engine.running and all(t.done() for t in engine._tasks) or engine._tasks == []


async def test_blocked_uses_long_backoff():
    engine, source, _, _ = make_engine()
    target = engine.targets[0]
    source.pages["fr"] = BlockedSourceError("403")
    await engine.start()
    await asyncio.sleep(0.1)
    await engine.stop()
    assert target.state is TargetState.BLOCKED
    assert "nouvel essai dans 120 s" in target.message
    assert len(source.calls) == 1            # no hammering while blocked


async def test_unexpected_exception_does_not_kill_loop():
    engine, source, _, _ = make_engine()
    target = engine.targets[0]
    source.pages["fr"] = ZeroDivisionError("bug")
    await engine.start()
    await asyncio.sleep(0.15)
    source.pages["fr"] = []
    await asyncio.sleep(0.5)
    await engine.stop()
    assert len(source.calls) >= 2
    assert target.failures == 0
    assert target.state in (TargetState.BASELINE, TargetState.OK)


async def test_on_event_exception_is_contained():
    engine, source, _, _ = make_engine()

    def boom(event):
        raise RuntimeError("ui bug")

    engine.on_event = boom
    source.pages["fr"] = [L("1")]
    await engine.check_target(engine.targets[0])           # must not raise


async def test_disabled_searches_have_no_targets():
    searches = [{"name": "A", "keywords": "a", "countries": ["fr", "uk"]},
                {"name": "B", "keywords": "b", "enabled": False}]
    engine, *_ = make_engine(searches)
    assert [(t.search.name, t.market.code) for t in engine.targets] == [("A", "fr"), ("A", "uk")]


async def test_run_once_reports_errors_per_target():
    searches = [{"name": "A", "keywords": "a", "countries": ["fr", "uk"]}]
    engine, source, _, _ = make_engine(searches)
    source.pages["uk"] = BlockedSourceError("403")
    results = await engine.run_once()
    assert results["A [FR]"] == []
    assert isinstance(results["A [UK]"], BlockedSourceError)


async def test_concurrency_limit_respected():
    searches = [{"name": f"S{i}", "keywords": "x", "countries": ["fr", "uk", "de"]} for i in range(4)]
    engine, source, _, _ = make_engine(searches, max_concurrency=2)
    active = 0
    peak = 0

    async def slow_search(search, market):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return []

    source.search = slow_search
    await engine.run_once()
    assert peak == 2


async def test_host_limiter_spacing():
    limiter = HostLimiter(0.05)
    loop = asyncio.get_running_loop()
    stamps = []

    async def hit():
        await limiter.wait("www.ebay.fr")
        stamps.append(loop.time())

    await asyncio.gather(*(hit() for _ in range(4)))
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(g >= 0.045 for g in gaps), gaps


async def test_target_updated_events_emitted():
    engine, source, _, events = make_engine()
    await engine.check_target(engine.targets[0])
    states = [e.target.state for e in events if isinstance(e, TargetUpdated)]
    assert TargetState.BASELINE in states


@pytest.mark.parametrize("failures,expected", [(1, 0.05), (2, 0.1), (3, 0.2)])
def test_backoff_growth(failures, expected):
    engine, *_ = make_engine()
    target = engine.targets[0]
    target.failures = failures - 1
    assert engine._backoff(target, blocked=False) == pytest.approx(expected)


async def test_sponsored_old_listing_buried_in_results_is_ignored():
    engine, source, dispatcher, _ = make_engine()
    target = engine.targets[0]
    source.pages["fr"] = [L(str(i)) for i in range(10, 0, -1)]          # 10..1 known
    await engine.check_target(target)
    source.pages["fr"] = [
        L("12"), L("11"),                     # genuinely new, at the top
        L("10"), L("9"), L("8"),
        L("500"),                             # unknown but below 3 known ones -> sponsored insertion
        L("7"), L("6"),
    ]
    new = await engine.check_target(target)
    assert [l.item_id for l in new] == ["11", "12"]
    assert await engine.check_target(target) == []                      # and never re-alerted later


async def test_slightly_late_listing_is_still_alerted():
    engine, source, dispatcher, _ = make_engine()
    target = engine.targets[0]
    source.pages["fr"] = [L("3"), L("2"), L("1")]
    await engine.check_target(target)
    # "21" was indexed a bit late: it shows up just below one newer known listing.
    source.pages["fr"] = [L("20"), L("4"), L("21"), L("3"), L("2"), L("1")]
    await engine.check_target(target)                                     # 20, 4, 21 new
    source.pages["fr"] = [L("22"), L("20"), L("4"), L("23"), L("21"), L("3")]
    new = await engine.check_target(target)
    assert sorted(l.item_id for l in new) == ["22", "23"]                 # 23 is below only 2 known


async def test_sponsored_guard_can_be_disabled():
    engine, source, _, _ = make_engine(sponsored_guard=0)
    target = engine.targets[0]
    source.pages["fr"] = [L(str(i)) for i in range(10, 0, -1)]
    await engine.check_target(target)
    source.pages["fr"] = [L("10"), L("9"), L("8"), L("7"), L("500")]
    assert [l.item_id for l in await engine.check_target(target)] == ["500"]
