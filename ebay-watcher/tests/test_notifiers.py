import asyncio

import httpx
import pytest

from ebaywatch.config import NotificationSettings
from ebaywatch.models import Listing
from ebaywatch.notifiers import (
    DiscordNotifier,
    Dispatcher,
    NotifierError,
    TelegramNotifier,
    build_notifiers,
)


def listing(**kw) -> Listing:
    base = dict(item_id="226789012345", market="fr", title="Switch <OLED> & co", url="https://www.ebay.fr/itm/226789012345",
                price=249.0, currency="EUR", shipping_text="+8,90 EUR livraison", image_url="https://i.ebayimg.com/a.jpg",
                search_name="Switch", subtitle="Occasion")
    base.update(kw)
    return Listing(**base)


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_discord_payload():
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(204)

    notifier = DiscordNotifier("https://discord.com/api/webhooks/1/x", client(handler))
    await notifier.send(listing())
    payload = notifier.build_payload(listing())
    embed = payload["embeds"][0]
    assert embed["title"] == "Switch <OLED> & co"
    assert embed["url"].endswith("/itm/226789012345")
    assert "249,00 €" in embed["description"]
    assert embed["thumbnail"]["url"] == "https://i.ebayimg.com/a.jpg"
    assert "eBay France" in embed["footer"]["text"]
    assert len(sent) == 1


async def test_discord_rate_limit_and_invalid():
    n = DiscordNotifier("https://discord.com/api/webhooks/1/x", client(lambda r: httpx.Response(429, json={"retry_after": 1.5})))
    with pytest.raises(NotifierError) as info:
        await n.send(listing())
    assert info.value.retry_after == 1.5 and not info.value.permanent

    n = DiscordNotifier("https://discord.com/api/webhooks/1/x", client(lambda r: httpx.Response(404, json={})))
    with pytest.raises(NotifierError) as info:
        await n.send(listing())
    assert info.value.permanent


async def test_telegram_photo_then_fallback_to_text():
    calls = []

    def handler(request):
        method = request.url.path.rsplit("/", 1)[-1]
        calls.append(method)
        if method == "sendPhoto":
            return httpx.Response(400, json={"ok": False, "description": "wrong file identifier"})
        return httpx.Response(200, json={"ok": True})

    notifier = TelegramNotifier("123:ABC", "42", client(handler))
    await notifier.send(listing())
    assert calls == ["sendPhoto", "sendMessage"]
    text = notifier.build_text(listing())
    assert "&lt;OLED&gt; &amp; co" in text              # HTML escaped
    assert 'href="https://www.ebay.fr/itm/226789012345"' in text


async def test_telegram_without_image_and_errors():
    calls = []

    def ok(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"ok": True})

    await TelegramNotifier("t", "1", client(ok)).send(listing(image_url=None))
    assert calls == ["/bott/sendMessage"]

    bad = TelegramNotifier("t", "1", client(lambda r: httpx.Response(401, json={"description": "Unauthorized"})))
    with pytest.raises(NotifierError) as info:
        await bad.send(listing(image_url=None))
    assert info.value.permanent

    limited = TelegramNotifier("t", "1", client(
        lambda r: httpx.Response(429, json={"parameters": {"retry_after": 7}})))
    with pytest.raises(NotifierError) as info:
        await limited.send(listing(image_url=None))
    assert info.value.retry_after == 7


def test_build_notifiers():
    async def run():
        async with httpx.AsyncClient() as c:
            assert build_notifiers(NotificationSettings(), c) == []
            both = build_notifiers(NotificationSettings(discord_webhook_url="https://discord.com/api/webhooks/1/x",
                                                        telegram_bot_token="t", telegram_chat_id="1"), c)
            assert [n.name for n in both] == ["discord", "telegram"]
            only_token = build_notifiers(NotificationSettings(telegram_bot_token="t"), c)
            assert only_token == []

    asyncio.run(run())


class FlakyNotifier:
    name = "flaky"

    def __init__(self, failures: int, permanent: bool = False) -> None:
        self.failures = failures
        self.permanent = permanent
        self.attempts = 0
        self.delivered: list[str] = []

    async def send(self, l: Listing) -> None:
        self.attempts += 1
        if self.attempts <= self.failures:
            raise NotifierError("temporary", retry_after=0, permanent=self.permanent)
        self.delivered.append(l.item_id)


async def test_dispatcher_retries_then_succeeds():
    flaky = FlakyNotifier(failures=2)
    errors = []
    dispatcher = Dispatcher([flaky], on_error=errors.append)
    dispatcher.start()
    dispatcher.submit(listing(item_id="1"))
    dispatcher.submit(listing(item_id="2"))
    await dispatcher.drain(5)
    await dispatcher.stop()
    assert flaky.delivered == ["1", "2"]
    assert dispatcher.sent == 2 and errors == []


async def test_dispatcher_gives_up_and_disables_permanent():
    always = FlakyNotifier(failures=99)
    errors = []
    dispatcher = Dispatcher([always], on_error=errors.append, sleep=lambda s: asyncio.sleep(0))
    dispatcher.start()
    dispatcher.submit(listing())
    await dispatcher.drain(5)
    assert always.attempts == Dispatcher.MAX_ATTEMPTS and dispatcher.failed == 1 and errors

    perm = FlakyNotifier(failures=99, permanent=True)
    other = FlakyNotifier(failures=0)
    other.name = "other"
    d2 = Dispatcher([perm, other], on_error=errors.append)
    d2.start()
    d2.submit(listing(item_id="a"))
    d2.submit(listing(item_id="b"))
    await d2.drain(5)
    await d2.stop()
    assert perm.attempts == 1                 # disabled after the first permanent error
    assert other.delivered == ["a", "b"]      # other channels keep working
    await dispatcher.stop()


async def test_dispatcher_survives_unexpected_exception():
    class Broken:
        name = "broken"

        async def send(self, l):
            raise KeyError("x")

    ok = FlakyNotifier(0)
    d = Dispatcher([Broken(), ok], on_error=lambda m: None)
    d.start()
    d.submit(listing(item_id="z"))
    await d.drain(5)
    await d.stop()
    assert ok.delivered == ["z"]
