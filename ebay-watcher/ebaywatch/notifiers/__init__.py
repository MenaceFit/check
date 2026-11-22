"""Notification channels (Discord, Telegram) with a retrying dispatcher."""

from __future__ import annotations

import asyncio
import html
import logging
from collections.abc import Callable
from datetime import timezone
from typing import Protocol

import httpx

from ..config import NotificationSettings
from ..markets import get_market
from ..models import Listing

log = logging.getLogger(__name__)


class NotifierError(RuntimeError):
    def __init__(self, message: str, retry_after: float | None = None, permanent: bool = False) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.permanent = permanent


class Notifier(Protocol):
    name: str

    async def send(self, listing: Listing) -> None: ...


def _summary_lines(listing: Listing) -> list[str]:
    lines = [f"💶 {listing.display_price}"]
    if listing.shipping_text:
        lines.append(f"🚚 {listing.shipping_text}")
    if listing.is_auction:
        lines.append("🔨 Enchère" + (f" — {listing.bids} enchère(s)" if listing.bids is not None else ""))
    if listing.subtitle:
        lines.append(f"ℹ️ {listing.subtitle}")
    if listing.location_text:
        lines.append(f"📍 {listing.location_text}")
    return lines


class DiscordNotifier:
    name = "discord"

    def __init__(self, webhook_url: str, client: httpx.AsyncClient) -> None:
        self.webhook_url = webhook_url
        self.client = client

    def build_payload(self, listing: Listing) -> dict:
        market = get_market(listing.market)
        embed: dict = {
            "title": listing.title[:256],
            "url": listing.url,
            "description": "\n".join(_summary_lines(listing))[:4000],
            "color": 0x0064D2,
            "footer": {"text": f"{market.flag} eBay {market.name} • {listing.search_name}"[:2048]},
            "timestamp": listing.found_at.astimezone(timezone.utc).isoformat(),
        }
        if listing.image_url:
            embed["thumbnail"] = {"url": listing.image_url}
        return {"username": "eBay Watcher", "embeds": [embed]}

    async def send(self, listing: Listing) -> None:
        try:
            response = await self.client.post(self.webhook_url, json=self.build_payload(listing))
        except httpx.HTTPError as exc:
            raise NotifierError(f"Discord : erreur réseau {exc.__class__.__name__}") from exc
        if response.status_code == 429:
            retry = 2.0
            try:
                retry = float(response.json().get("retry_after", retry))
            except Exception:  # noqa: BLE001 - body may not be JSON
                pass
            raise NotifierError("Discord : limite de débit", retry_after=retry)
        if response.status_code in (400, 401, 403, 404):
            raise NotifierError(f"Discord : webhook invalide (HTTP {response.status_code})", permanent=True)
        if response.status_code >= 300:
            raise NotifierError(f"Discord : HTTP {response.status_code}")


class TelegramNotifier:
    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str, client: httpx.AsyncClient,
                 api_root: str = "https://api.telegram.org") -> None:
        self.base = f"{api_root.rstrip('/')}/bot{bot_token}"
        self.chat_id = chat_id
        self.client = client

    def build_text(self, listing: Listing) -> str:
        market = get_market(listing.market)
        parts = [
            f"<b>{html.escape(listing.title)}</b>",
            *(html.escape(line) for line in _summary_lines(listing)),
            f"{market.flag} eBay {html.escape(market.name)} • {html.escape(listing.search_name)}",
            f'<a href="{html.escape(listing.url, quote=True)}">Voir l\'annonce</a>',
        ]
        return "\n".join(parts)

    async def _call(self, method: str, payload: dict) -> httpx.Response:
        try:
            return await self.client.post(f"{self.base}/{method}", json=payload)
        except httpx.HTTPError as exc:
            raise NotifierError(f"Telegram : erreur réseau {exc.__class__.__name__}") from exc

    @staticmethod
    def _raise_for(response: httpx.Response) -> None:
        if response.status_code == 200:
            return
        retry_after = None
        description = ""
        try:
            body = response.json()
            description = body.get("description", "")
            retry_after = (body.get("parameters") or {}).get("retry_after")
        except Exception:  # noqa: BLE001
            pass
        if response.status_code == 429:
            raise NotifierError("Telegram : limite de débit", retry_after=float(retry_after or 3))
        if response.status_code in (401, 403, 404):
            raise NotifierError(f"Telegram : token ou chat_id invalide ({description})", permanent=True)
        raise NotifierError(f"Telegram : HTTP {response.status_code} {description}")

    async def send(self, listing: Listing) -> None:
        text = self.build_text(listing)
        if listing.image_url and len(text) <= 1024:
            response = await self._call(
                "sendPhoto",
                {"chat_id": self.chat_id, "photo": listing.image_url, "caption": text, "parse_mode": "HTML"},
            )
            if response.status_code == 200:
                return
            if response.status_code != 400:   # 400 = image refused by Telegram -> fall back to text
                self._raise_for(response)
        response = await self._call(
            "sendMessage",
            {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False},
        )
        self._raise_for(response)


def build_notifiers(settings: NotificationSettings, client: httpx.AsyncClient) -> list[Notifier]:
    notifiers: list[Notifier] = []
    if settings.discord_webhook_url:
        notifiers.append(DiscordNotifier(settings.discord_webhook_url, client))
    if settings.telegram_bot_token and settings.telegram_chat_id:
        notifiers.append(TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id, client))
    return notifiers


class Dispatcher:
    """Sends notifications in the background, in order, with retries.

    Notifications never block the scraping loop.
    """

    MAX_ATTEMPTS = 4

    def __init__(self, notifiers: list[Notifier], on_error: Callable[[str], None] | None = None,
                 sleep: Callable[[float], object] = asyncio.sleep) -> None:
        self.notifiers = notifiers
        self.on_error = on_error or (lambda msg: log.warning(msg))
        self._queue: asyncio.Queue[Listing | None] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._sleep = sleep
        self._disabled: set[str] = set()
        self.sent = 0
        self.failed = 0

    def start(self) -> None:
        if self._task is None and self.notifiers:
            self._task = asyncio.create_task(self._worker(), name="notification-dispatcher")

    def submit(self, listing: Listing) -> None:
        if self.notifiers:
            self._queue.put_nowait(listing)

    async def _deliver(self, notifier: Notifier, listing: Listing) -> None:
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                await notifier.send(listing)
                self.sent += 1
                return
            except NotifierError as exc:
                if exc.permanent:
                    self._disabled.add(notifier.name)
                    self.failed += 1
                    self.on_error(f"{exc} — canal {notifier.name} désactivé jusqu'au redémarrage")
                    return
                if attempt == self.MAX_ATTEMPTS:
                    self.failed += 1
                    self.on_error(f"{exc} — notification abandonnée après {attempt} essais")
                    return
                await self._sleep(exc.retry_after if exc.retry_after is not None else 2 ** attempt)
            except Exception as exc:  # noqa: BLE001 - never let the worker die
                self.failed += 1
                self.on_error(f"{notifier.name} : erreur inattendue {exc!r}")
                return

    async def _worker(self) -> None:
        while True:
            listing = await self._queue.get()
            try:
                if listing is None:
                    return
                for notifier in self.notifiers:
                    if notifier.name not in self._disabled:
                        await self._deliver(notifier, listing)
            finally:
                self._queue.task_done()

    async def drain(self, timeout: float = 30) -> None:
        """Wait until every queued notification has been processed."""
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._queue.join(), timeout)
        except asyncio.TimeoutError:
            pass

    async def stop(self) -> None:
        if self._task is None:
            return
        await self._queue.put(None)
        try:
            await asyncio.wait_for(self._task, 10)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._task.cancel()
        self._task = None
