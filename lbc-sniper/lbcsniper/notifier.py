"""Construction des messages Discord et envoi (bot Discord ou webhook)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

import httpx

from .models import Ad, SearchConfig

log = logging.getLogger("lbcsniper.notifier")

# Signature de l'envoi par le bot : (channel_id, content, embed, ad_url) -> None
BotSender = Callable[[str, str, dict, str], Awaitable[None]]


class NotifyError(Exception):
    pass


def format_latency(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 0:
        seconds = 0
    if seconds < 90:
        return f"{seconds:.0f} s après publication"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min après publication"
    return f"{seconds / 3600:.1f} h après publication"


def build_embed(ad: Ad, cfg: SearchConfig, latency_s: float | None = None) -> dict:
    fields = set(cfg.display_fields)
    embed: dict = {
        "title": ad.title[:256],
        "url": ad.url,
        "color": int(cfg.embed_color.lstrip("#"), 16),
        "fields": [],
        "footer": {"text": f"🔎 {cfg.name[:60]} • LBC Sniper"},
    }
    if ad.published_at:
        embed["timestamp"] = ad.published_at.astimezone(timezone.utc).isoformat()

    def add(name: str, value: str, inline: bool = True):
        if value:
            embed["fields"].append({"name": name, "value": value[:1024], "inline": inline})

    if "price" in fields:
        add("💶 Prix", f"**{ad.price_label}**")
    if "location" in fields:
        add("📍 Lieu", ad.location_label)
    if "date" in fields and ad.published_at:
        ts = int(ad.published_at.timestamp())
        add("🕒 Publiée", f"<t:{ts}:T> (<t:{ts}:R>)")
    if "latency" in fields and latency_s is not None:
        add("⚡ Détectée", format_latency(latency_s))
    if "seller" in fields and (ad.owner_name or ad.owner_type):
        add("👤 Vendeur", " • ".join(x for x in (ad.owner_name, ad.owner_type) if x))
    if "category" in fields and ad.category:
        add("🗂️ Catégorie", ad.category)
    if "shipping" in fields:
        add("📦 Livraison", {True: "✅ Possible", False: "❌ Main propre"}.get(ad.shippable, "❔"))
    if "attributes" in fields and ad.attributes:
        lines = [f"**{k}** : {v}" for k, v in list(ad.attributes.items())[:8]]
        add("🧾 Caractéristiques", "\n".join(lines), inline=False)
    if "description" in fields and ad.body:
        body = ad.body if len(ad.body) <= 350 else ad.body[:347].rstrip() + "…"
        embed["description"] = body
    if ad.images:
        if "image" in fields:
            embed["image"] = {"url": ad.images[0]}
        if "thumbnail" in fields:
            embed["thumbnail"] = {"url": ad.images[0]}
    return embed


class Notifier:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.bot_sender: Optional[BotSender] = None
        self._http = httpx.AsyncClient(timeout=10.0, transport=transport)
        self.sent = 0
        self.failed = 0

    async def close(self) -> None:
        await self._http.aclose()

    async def send(
        self,
        ad: Ad,
        cfg: SearchConfig,
        latency_s: float | None,
        defaults: dict | None = None,
    ) -> str:
        """Envoie l'annonce. Renvoie la destination utilisée ('bot' ou 'webhook')."""
        defaults = defaults or {}
        embed = build_embed(ad, cfg, latency_s)
        content = cfg.mention.strip()
        channel = cfg.discord_channel_id or defaults.get("default_channel_id", "")
        webhook = cfg.webhook_url or defaults.get("default_webhook_url", "")
        try:
            if channel and self.bot_sender:
                await self.bot_sender(str(channel), content, embed, ad.url)
                self.sent += 1
                return "bot"
            if webhook:
                await self._send_webhook(webhook, content, embed)
                self.sent += 1
                return "webhook"
        except Exception as exc:
            self.failed += 1
            raise NotifyError(str(exc)) from exc
        self.failed += 1
        if channel and not self.bot_sender:
            raise NotifyError("salon Discord configuré mais le bot n'est pas connecté")
        raise NotifyError("aucune destination Discord (salon ou webhook) configurée")

    async def send_text(self, channel_or_webhook: str, text: str) -> None:
        """Message simple (alertes du moteur)."""
        if channel_or_webhook.startswith("http"):
            await self._post_webhook(channel_or_webhook, {"content": text[:2000]})
        elif self.bot_sender:
            await self.bot_sender(channel_or_webhook, text[:2000], {}, "")

    async def _send_webhook(self, url: str, content: str, embed: dict) -> None:
        payload = {"username": "LBC Sniper", "embeds": [embed]}
        if content:
            payload["content"] = content
            payload["allowed_mentions"] = {"parse": ["everyone", "roles", "users"]}
        await self._post_webhook(url, payload)

    async def _post_webhook(self, url: str, payload: dict) -> None:
        for attempt in range(4):
            resp = await self._http.post(url, json=payload)
            if resp.status_code == 429:
                try:
                    retry = float(resp.json().get("retry_after", 1))
                except ValueError:
                    retry = 1.0
                await asyncio.sleep(min(retry, 10) + 0.05)
                continue
            if resp.status_code >= 400:
                raise NotifyError(f"webhook HTTP {resp.status_code} : {resp.text[:200]}")
            return
        raise NotifyError("webhook : trop de limitations Discord (429)")


def latency_seconds(ad: Ad, now: datetime | None = None) -> float | None:
    if not ad.published_at:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - ad.published_at).total_seconds()
