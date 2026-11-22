"""Polling engine: schedules every (search × country) target and detects new listings."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .config import Config, Search
from .filters import ListingFilter
from .markets import Market, get_market
from .models import Listing
from .notifiers import Dispatcher
from .sources.base import BlockedSourceError, Source, SourceError
from .store import Store

log = logging.getLogger(__name__)

MAX_BACKOFF = 15 * 60
MAX_BLOCK_BACKOFF = 30 * 60


class TargetState(str, Enum):
    PENDING = "en attente"
    CHECKING = "vérification…"
    OK = "ok"
    BASELINE = "initialisé"
    ERROR = "erreur"
    BLOCKED = "bloqué"


@dataclass(slots=True)
class Target:
    search: Search
    market: Market
    state: TargetState = TargetState.PENDING
    message: str = ""
    last_check: datetime | None = None
    last_count: int = 0
    new_total: int = 0
    failures: int = 0
    checks: int = 0
    next_run: float = 0.0
    last_duration: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.search.name} [{self.market.code.upper()}]"


# ---------------------------------------------------------------- events
@dataclass(slots=True)
class TargetUpdated:
    target: Target


@dataclass(slots=True)
class NewListing:
    listing: Listing
    target: Target


@dataclass(slots=True)
class LogEvent:
    level: str
    message: str
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


Event = TargetUpdated | NewListing | LogEvent


class HostLimiter:
    """Guarantees a minimum delay between two requests sent to the same host."""

    def __init__(self, min_delay: float) -> None:
        self.min_delay = min_delay
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    async def wait(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            elapsed = time.monotonic() - self._last.get(host, 0.0)
            if elapsed < self.min_delay:
                await asyncio.sleep(self.min_delay - elapsed)
            self._last[host] = time.monotonic()


class Engine:
    def __init__(
        self,
        config: Config,
        source: Source,
        store: Store,
        dispatcher: Dispatcher | None = None,
        on_event: Callable[[Event], None] | None = None,
        interval: float | None = None,
        min_delay_per_host: float | None = None,
        jitter: float = 0.15,
    ) -> None:
        self.config = config
        self.source = source
        self.store = store
        self.dispatcher = dispatcher
        self.on_event = on_event or (lambda e: None)
        self.interval = float(interval if interval is not None else config.general.interval_seconds)
        self.jitter = jitter
        self.limiter = HostLimiter(
            config.general.min_delay_per_host if min_delay_per_host is None else min_delay_per_host
        )
        self.semaphore = asyncio.Semaphore(config.general.max_concurrency)
        self.targets: list[Target] = self._build_targets(config)
        self._filters = {s.key: ListingFilter(s, config) for s in config.searches}
        self._tasks: list[asyncio.Task] = []
        self.running = False
        self.requests = 0
        self.new_total = 0
        self.started_at: float | None = None

    @staticmethod
    def _build_targets(config: Config) -> list[Target]:
        return [
            Target(search=s, market=get_market(code))
            for s in config.searches
            if s.enabled
            for code in s.countries
        ]

    # --------------------------------------------------------------- events
    def _emit(self, event: Event) -> None:
        try:
            self.on_event(event)
        except Exception:  # noqa: BLE001 - a UI bug must never kill the engine
            log.exception("on_event callback failed")

    def _log(self, level: str, message: str) -> None:
        getattr(log, level if level in ("info", "warning", "error") else "info")(message)
        self._emit(LogEvent(level, message))

    # ------------------------------------------------------------ one check
    async def check_target(self, target: Target) -> list[Listing]:
        """Run one check of a target. Returns the new listings found."""
        async with self.semaphore:
            await self.limiter.wait(target.market.host)
            target.state = TargetState.CHECKING
            self._emit(TargetUpdated(target))
            started = time.monotonic()
            self.requests += 1
            try:
                listings = await self.source.search(target.search, target.market)
            finally:
                target.last_duration = time.monotonic() - started
                target.checks += 1
                target.last_check = datetime.now(timezone.utc)
        return self._process(target, listings)

    def _process(self, target: Target, listings: list[Listing]) -> list[Listing]:
        search = target.search
        key = search.key
        target.last_count = len(listings)
        target.failures = 0
        ids = [item.item_id for item in listings]
        flt = self._filters.get(key) or ListingFilter(search, self.config)

        if not self.store.is_baselined(key, target.market.code):
            self.store.mark_baselined(key, target.market.code)
            if not self.config.general.notify_existing_on_start:
                self.store.mark_seen(key, ids)
                target.state = TargetState.BASELINE
                target.message = f"{len(listings)} annonces existantes mémorisées"
                self._emit(TargetUpdated(target))
                self._log("info", f"{target.label} : initialisation, {len(listings)} annonces existantes ignorées")
                return []

        unseen = set(self.store.unseen(key, ids))
        self.store.mark_seen(key, ids)

        # eBay lists newest first, so a genuinely new listing shows up ABOVE the
        # listings we already know. An unknown one buried below several known ones
        # is a sponsored insertion (old listing promoted into the results).
        guard = self.config.general.sponsored_guard
        buried: set[str] = set()
        if guard:
            known_above = 0
            for item in listings:
                if item.item_id in unseen:
                    if known_above >= guard:
                        buried.add(item.item_id)
                else:
                    known_above += 1
            if buried:
                log.debug("%s: %d sponsored/old listing(s) ignored", target.label, len(buried))

        fresh: list[Listing] = []
        # eBay returns newest first; notify in chronological order.
        for item in reversed(listings):
            if item.item_id not in unseen or item.item_id in buried:
                continue
            decision = flt.check(item)
            if not decision.accepted:
                log.debug("%s rejected %s: %s", target.label, item.item_id, decision.reason)
                continue
            item.search_name = search.name
            item.found_at = datetime.now(timezone.utc)
            fresh.append(item)
            self.store.add_listing(key, item)
            if self.dispatcher is not None:
                self.dispatcher.submit(item)
            self._emit(NewListing(item, target))

        target.new_total += len(fresh)
        self.new_total += len(fresh)
        target.state = TargetState.OK
        if fresh:
            target.message = f"{len(fresh)} nouvelle(s)"
        elif not listings:
            target.message = "0 annonce reçue (recherche trop précise ?)"
        else:
            target.message = "rien de nouveau"
        self._emit(TargetUpdated(target))
        if fresh:
            self._log("info", f"{target.label} : {len(fresh)} nouvelle(s) annonce(s)")
        return fresh

    def _backoff(self, target: Target, blocked: bool) -> float:
        target.failures += 1
        if blocked:
            return min(max(120.0, self.interval * 2 ** target.failures), MAX_BLOCK_BACKOFF)
        return min(self.interval * 2 ** (target.failures - 1), MAX_BACKOFF)

    def _next_delay(self) -> float:
        return self.interval * random.uniform(1 - self.jitter, 1 + self.jitter)

    # ---------------------------------------------------------------- loops
    async def _run_target(self, target: Target, initial_delay: float) -> None:
        await asyncio.sleep(initial_delay)
        while self.running:
            delay = self._next_delay()
            try:
                await self.check_target(target)
            except asyncio.CancelledError:
                raise
            except BlockedSourceError as exc:
                delay = self._backoff(target, blocked=True)
                target.state = TargetState.BLOCKED
                target.message = f"{exc} — nouvel essai dans {int(delay)} s"
                self._emit(TargetUpdated(target))
                self._log("warning", f"{target.label} : {target.message}")
            except SourceError as exc:
                delay = self._backoff(target, blocked=False)
                target.state = TargetState.ERROR
                target.message = f"{exc} — nouvel essai dans {int(delay)} s"
                self._emit(TargetUpdated(target))
                self._log("warning", f"{target.label} : {target.message}")
            except Exception as exc:  # noqa: BLE001 - keep the loop alive no matter what
                delay = self._backoff(target, blocked=False)
                target.state = TargetState.ERROR
                target.message = f"erreur inattendue : {exc!r}"
                self._emit(TargetUpdated(target))
                log.exception("Unexpected error on %s", target.label)
                self._log("error", f"{target.label} : {target.message}")
            target.next_run = time.monotonic() + delay
            await asyncio.sleep(delay)

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.started_at = time.monotonic()
        if self.dispatcher is not None:
            self.dispatcher.start()
        if not self.targets:
            self._log("warning", "Aucune recherche active : ajoutez une recherche ou activez-en une.")
        # Spread the first checks so we do not hammer eBay at start-up.
        spread = min(self.interval / 2, 2.0 * len(self.targets))
        for index, target in enumerate(self.targets):
            initial = spread * index / max(1, len(self.targets))
            target.next_run = time.monotonic() + initial
            self._tasks.append(asyncio.create_task(self._run_target(target, initial), name=target.label))
        self._log("info", f"Surveillance démarrée : {len(self.targets)} cible(s), intervalle {int(self.interval)} s")

    async def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self.dispatcher is not None:
            await self.dispatcher.drain(timeout=10)
        self._log("info", "Surveillance arrêtée")

    async def run_once(self) -> dict[str, list[Listing] | Exception]:
        """Check every target once (used by the CLI ``once`` command and tests)."""
        results: dict[str, list[Listing] | Exception] = {}

        async def one(target: Target) -> None:
            try:
                results[target.label] = await self.check_target(target)
            except Exception as exc:  # noqa: BLE001
                target.state = TargetState.ERROR
                target.message = str(exc)
                results[target.label] = exc

        await asyncio.gather(*(one(t) for t in self.targets))
        return results
