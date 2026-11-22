"""Wires config + source + store + notifications + engine together."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx

from .config import Config
from .engine import Engine, Event
from .notifiers import Dispatcher, build_notifiers
from .sources import create_source
from .sources.base import Source
from .store import Store


@dataclass
class Runtime:
    config: Config
    store: Store
    source: Source
    dispatcher: Dispatcher
    engine: Engine
    http: httpx.AsyncClient

    async def aclose(self) -> None:
        await self.engine.stop()
        await self.dispatcher.stop()
        await self.source.aclose()
        await self.http.aclose()


def build_runtime(
    config: Config,
    on_event: Callable[[Event], None] | None = None,
    on_notify_error: Callable[[str], None] | None = None,
    store: Store | None = None,
    source: Source | None = None,
) -> Runtime:
    store = store or Store(config.database_path)
    source = source or create_source(config)
    http = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
    dispatcher = Dispatcher(build_notifiers(config.notifications, http), on_error=on_notify_error)
    engine = Engine(config, source, store, dispatcher, on_event=on_event)
    return Runtime(config, store, source, dispatcher, engine, http)
