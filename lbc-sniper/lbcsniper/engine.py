"""Moteur de surveillance : une tâche asyncio par recherche, en parallèle."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timezone
from typing import Optional

from .config import Settings
from .db import Database
from .events import EventBus
from .filters import check_ad
from .lbc.client import LbcBlocked, LbcClient, LbcError
from .lbc.parse import normalize_ad
from .models import Ad, SearchConfig
from .notifier import Notifier, NotifyError, latency_seconds

log = logging.getLogger("lbcsniper.engine")


class Watcher:
    def __init__(self, manager: "Engine", search_id: int, cfg: SearchConfig):
        self.m = manager
        self.id = search_id
        self.cfg = cfg
        self.task: Optional[asyncio.Task] = None
        self.seen: set[str] = set()
        self.primed = False
        self.runs = 0
        self.errors = 0
        self.consecutive_errors = 0
        self.new_ads = 0
        self.last_run: Optional[str] = None
        self.last_ok: Optional[str] = None
        self.last_error: str = ""
        self.last_duration_ms: Optional[float] = None
        self.next_run_at: Optional[float] = None
        self.alerted = False

    @property
    def interval(self) -> int:
        return max(self.m.settings.min_interval, int(self.cfg.interval_seconds))

    def status(self) -> dict:
        nxt = None
        if self.next_run_at:
            nxt = max(0, round(self.next_run_at - time.monotonic(), 1))
        state = "ok"
        if not self.cfg.enabled:
            state = "disabled"
        elif self.m.paused:
            state = "paused"
        elif self.consecutive_errors:
            state = "error"
        elif not self.last_ok:
            state = "starting"
        return {
            "id": self.id,
            "name": self.cfg.name,
            "state": state,
            "runs": self.runs,
            "errors": self.errors,
            "new_ads": self.new_ads,
            "last_run": self.last_run,
            "last_ok": self.last_ok,
            "last_error": self.last_error,
            "last_duration_ms": self.last_duration_ms,
            "next_run_in": nxt,
            "interval": self.interval,
            "seen": len(self.seen),
        }

    def start(self) -> None:
        self.task = asyncio.create_task(self._loop(), name=f"watcher-{self.id}")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass

    async def _loop(self) -> None:
        self.seen = await self.m.db.load_seen(self.id)
        self.primed = bool(self.seen)
        # Petit décalage initial pour ne pas lancer toutes les recherches à la même milliseconde.
        await asyncio.sleep(random.uniform(0, 1.5))
        while True:
            if self.m.paused:
                self.next_run_at = None
                await asyncio.sleep(1)
                continue
            delay = await self.run_once()
            self.next_run_at = time.monotonic() + delay
            await asyncio.sleep(delay)

    async def run_once(self) -> float:
        """Exécute une recherche et renvoie le délai avant la suivante."""
        t0 = time.perf_counter()
        self.runs += 1
        self.last_run = datetime.now(timezone.utc).isoformat()
        try:
            raws = await self.m.client.search(self.cfg)
        except LbcBlocked as exc:
            return await self._on_error(str(exc), blocked=True)
        except LbcError as exc:
            return await self._on_error(str(exc), blocked=False)
        except Exception as exc:  # pragma: no cover - sécurité
            log.exception("Erreur inattendue pour %s", self.cfg.name)
            return await self._on_error(f"{exc.__class__.__name__}: {exc}", blocked=False)

        self.last_duration_ms = round((time.perf_counter() - t0) * 1000)
        if self.consecutive_errors:
            self.m.bus.log("INFO", f"« {self.cfg.name} » fonctionne de nouveau.", self.id)
        self.consecutive_errors = 0
        self.last_error = ""
        self.alerted = False
        self.last_ok = self.last_run
        await self._process(raws)
        self.m.bus.publish("status", self.status())
        return self.interval + random.uniform(0, self.interval * 0.15)

    async def _on_error(self, message: str, blocked: bool) -> float:
        self.errors += 1
        self.consecutive_errors += 1
        self.last_error = message
        cap = 900 if blocked else 300
        delay = min(self.interval * (2 ** min(self.consecutive_errors, 6)), cap)
        self.m.bus.log(
            "WARNING",
            f"« {self.cfg.name} » : {message}. Nouvel essai dans {delay:.0f} s.",
            self.id,
        )
        self.m.bus.publish("status", self.status())
        if self.consecutive_errors >= 3 and not self.alerted:
            self.alerted = True
            await self.m.alert(
                f"⚠️ **LBC Sniper** — la recherche « {self.cfg.name} » échoue depuis "
                f"{self.consecutive_errors} tentatives : {message}"
            )
        return delay

    async def _process(self, raws: list[dict]) -> None:
        ads: list[Ad] = [a for a in (normalize_ad(r) for r in raws) if a]
        new = [a for a in ads if a.list_id not in self.seen]
        if not new:
            return
        self.seen.update(a.list_id for a in new)
        await self.m.db.add_seen(self.id, [a.list_id for a in new])

        if not self.primed:
            self.primed = True
            if not self.cfg.notify_existing_on_start:
                self.m.bus.log(
                    "INFO",
                    f"« {self.cfg.name} » : {len(new)} annonces existantes mémorisées. "
                    "Seules les nouvelles seront notifiées.",
                    self.id,
                )
                return

        # L'API renvoie du plus récent au plus ancien : on notifie dans l'ordre chronologique.
        for ad in reversed(new):
            accepted, reason = check_ad(ad, self.cfg)
            latency = latency_seconds(ad)
            if accepted:
                self.new_ads += 1
                asyncio.create_task(self._deliver(ad, latency))
            else:
                await self._record(ad, latency, False, f"filtrée : {reason}")

    async def _deliver(self, ad: Ad, latency: float | None) -> None:
        reason = ""
        notified = False
        try:
            await self.m.notifier.send(ad, self.cfg, latency, self.m.settings_cache)
            notified = True
        except NotifyError as exc:
            reason = f"envoi Discord impossible : {exc}"
            self.m.bus.log("ERROR", f"« {self.cfg.name} » : {reason}", self.id)
        await self._record(ad, latency, notified, reason)

    async def _record(self, ad: Ad, latency: float | None, notified: bool, reason: str) -> None:
        row_id = await self.m.db.add_ad(self.id, ad, latency, notified, reason)
        self.m.bus.publish(
            "ad",
            {
                "id": row_id,
                "search_id": self.id,
                "search_name": self.cfg.name,
                "ad": ad.model_dump(mode="json"),
                "latency_s": latency,
                "notified": notified,
                "reject_reason": reason,
                "found_at": datetime.now(timezone.utc).isoformat(),
            },
        )


class Engine:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        client: LbcClient,
        notifier: Notifier,
        bus: EventBus,
    ):
        self.settings = settings
        self.db = db
        self.client = client
        self.notifier = notifier
        self.bus = bus
        self.watchers: dict[int, Watcher] = {}
        self.settings_cache: dict = {}
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._maintenance: Optional[asyncio.Task] = None

    @property
    def paused(self) -> bool:
        return bool(self.settings_cache.get("paused"))

    async def start(self) -> None:
        await self.refresh_settings()
        for sid, cfg in await self.db.list_searches():
            self._spawn(sid, cfg)
        self._maintenance = asyncio.create_task(self._maintenance_loop())
        self.bus.log("INFO", f"Moteur démarré avec {len(self.watchers)} recherche(s) active(s).")

    async def stop(self) -> None:
        if self._maintenance:
            self._maintenance.cancel()
        for w in list(self.watchers.values()):
            await w.stop()
        self.watchers.clear()

    async def refresh_settings(self) -> dict:
        self.settings_cache = await self.db.get_settings()
        self.client.mode = self.settings_cache.get("source_mode", "auto")
        return self.settings_cache

    def _spawn(self, sid: int, cfg: SearchConfig) -> None:
        if not cfg.enabled:
            return
        w = Watcher(self, sid, cfg)
        self.watchers[sid] = w
        w.start()

    async def reload(self, sid: int) -> None:
        old = self.watchers.pop(sid, None)
        if old:
            await old.stop()
        cfg = await self.db.get_search(sid)
        if cfg:
            self._spawn(sid, cfg)
        self.bus.publish("searches", {"reload": sid})

    async def run_now(self, sid: int) -> bool:
        w = self.watchers.get(sid)
        if not w:
            return False
        await w.run_once()
        return True

    async def preview(self, cfg: SearchConfig) -> list[dict]:
        """Lance la recherche une fois, sans rien notifier ni mémoriser."""
        raws = await self.client.search(cfg)
        out = []
        for raw in raws:
            ad = normalize_ad(raw)
            if not ad:
                continue
            ok, reason = check_ad(ad, cfg)
            out.append(
                {
                    "ad": ad.model_dump(mode="json"),
                    "accepted": ok,
                    "reason": reason,
                    "age_s": latency_seconds(ad),
                }
            )
        return out

    async def alert(self, text: str) -> None:
        dest = self.settings_cache.get("alert_channel_id") or self.settings_cache.get(
            "default_webhook_url", ""
        )
        if not dest:
            return
        try:
            await self.notifier.send_text(str(dest), text)
        except Exception as exc:
            log.warning("Alerte Discord impossible : %s", exc)

    def status(self) -> dict:
        return {
            "started_at": self.started_at,
            "paused": self.paused,
            "watchers": {sid: w.status() for sid, w in self.watchers.items()},
            "requests_total": self.client.total_requests,
            "requests_last_minute": self.client.limiter.used_last_minute,
            "requests_limit_per_minute": self.client.limiter.per_minute,
            "last_http_latency_ms": round(self.client.last_latency_ms)
            if self.client.last_latency_ms
            else None,
            "notifications_sent": self.notifier.sent,
            "notifications_failed": self.notifier.failed,
        }

    async def _maintenance_loop(self) -> None:
        while True:
            await asyncio.sleep(600)
            try:
                await self.db.prune(int(self.settings_cache.get("keep_ads", 3000)))
            except Exception as exc:  # pragma: no cover
                log.warning("Nettoyage de la base impossible : %s", exc)
