"""Point d'entrée : python -m lbcsniper"""
from __future__ import annotations

import asyncio
import contextlib
import logging

import uvicorn

from .config import load_settings
from .db import Database
from .engine import Engine
from .events import BusLogHandler, EventBus
from .lbc.client import LbcClient
from .notifier import Notifier
from .web.app import create_app

log = logging.getLogger("lbcsniper")


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.client").setLevel(logging.ERROR)  # avertissements « voice » inutiles

    bus = EventBus()
    logging.getLogger().addHandler(BusLogHandler(bus))
    db = await Database.open(settings.database_path)
    client = LbcClient(settings)
    notifier = Notifier()
    engine = Engine(settings, db, client, notifier, bus)

    bot = None
    bot_task = None
    if settings.discord_token:
        from .bot import SniperBot

        bot = SniperBot(engine, settings.discord_guild_id)
        notifier.bot_sender = bot.send_ad

        async def run_bot():
            try:
                await bot.start(settings.discord_token)
            except Exception as exc:  # token invalide, réseau...
                log.error("Bot Discord arrêté : %s", exc)
                notifier.bot_sender = None

        bot_task = asyncio.create_task(run_bot())
    else:
        log.warning("DISCORD_TOKEN absent : seuls les webhooks Discord fonctionneront.")

    await engine.start()
    app = create_app(engine, bot)
    server = uvicorn.Server(
        uvicorn.Config(app, host=settings.dashboard_host, port=settings.dashboard_port, log_level="warning")
    )
    url = f"http://{'localhost' if settings.is_local_only else settings.dashboard_host}:{settings.dashboard_port}"
    print(f"\n  LBC Sniper démarré  →  dashboard : {url}\n  (Ctrl+C pour arrêter)\n")
    try:
        await server.serve()
    finally:
        await engine.stop()
        if bot is not None:
            with contextlib.suppress(Exception):
                await bot.close()
        if bot_task:
            bot_task.cancel()
        await client.close()
        await notifier.close()
        await db.close()


def run() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())


if __name__ == "__main__":
    run()
