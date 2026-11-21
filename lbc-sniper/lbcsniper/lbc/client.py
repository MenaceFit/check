"""Client HTTP Leboncoin : API JSON en priorité, page HTML en secours.

Une seule connexion HTTP/2 persistante est partagée par toutes les recherches (latence
minimale), avec un limiteur global de requêtes pour ne pas se faire bloquer.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

import httpx

from ..config import Settings
from ..models import SearchConfig
from .parse import ads_from_html
from .query import build_payload, build_web_url

log = logging.getLogger("lbcsniper.client")


class LbcError(Exception):
    """Erreur générique lors d'une recherche."""


class LbcBlocked(LbcError):
    """Leboncoin refuse la requête (403/429 ou page captcha) : il faut ralentir."""


class RateLimiter:
    """Fenêtre glissante : au plus `per_minute` requêtes sur 60 secondes, tous moteurs confondus."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._stamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._stamps and now - self._stamps[0] >= 60:
                    self._stamps.popleft()
                if len(self._stamps) < self.per_minute:
                    self._stamps.append(now)
                    return
                await asyncio.sleep(60 - (now - self._stamps[0]) + 0.01)

    @property
    def used_last_minute(self) -> int:
        now = time.monotonic()
        return sum(1 for t in self._stamps if now - t < 60)


class LbcClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.mode = "auto"  # auto | api | html
        self.limiter = RateLimiter(settings.max_requests_per_minute)
        self.total_requests = 0
        self.last_latency_ms: float | None = None
        self._api_failures = 0
        self._api_paused_until = 0.0
        self._http = httpx.AsyncClient(
            http2=transport is None,
            transport=transport,
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=True,
            headers={
                "User-Agent": settings.user_agent,
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            },
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def search(self, cfg: SearchConfig) -> list[dict]:
        """Renvoie les annonces brutes, de la plus récente à la plus ancienne."""
        mode = self.mode
        if mode == "html":
            return await self._search_html(cfg)
        # Mode auto : après 3 échecs de l'API, on passe 10 min par la page web
        # (évite de doubler chaque requête quand l'API est indisponible).
        if mode == "auto" and time.monotonic() < self._api_paused_until:
            return await self._search_html(cfg)
        try:
            ads = await self._search_api(cfg)
            self._api_failures = 0
            return ads
        except LbcError:
            if mode == "api":
                raise
            self._api_failures += 1
            if self._api_failures >= 3:
                self._api_paused_until = time.monotonic() + 600
                self._api_failures = 0
                log.warning("API Leboncoin indisponible : passage par la page web pendant 10 min")
            return await self._search_html(cfg)

    async def _request(self, method: str, url: str, **kw) -> httpx.Response:
        await self.limiter.acquire()
        t0 = time.perf_counter()
        try:
            resp = await self._http.request(method, url, **kw)
        except httpx.HTTPError as exc:
            raise LbcError(f"Erreur réseau : {exc.__class__.__name__}") from exc
        finally:
            self.total_requests += 1
        self.last_latency_ms = (time.perf_counter() - t0) * 1000
        if resp.status_code in (403, 429):
            raise LbcBlocked(f"Leboncoin a refusé la requête (HTTP {resp.status_code})")
        if resp.status_code >= 400:
            raise LbcError(f"HTTP {resp.status_code}")
        return resp

    async def _search_api(self, cfg: SearchConfig) -> list[dict]:
        resp = await self._request(
            "POST",
            self.settings.lbc_api_url,
            json=build_payload(cfg),
            headers={
                "api_key": self.settings.lbc_api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": self.settings.lbc_web_url,
                "Referer": self.settings.lbc_web_url + "/",
            },
        )
        try:
            data = resp.json()
        except ValueError as exc:
            if "captcha" in resp.text.lower() or "datadome" in resp.text.lower():
                raise LbcBlocked("Leboncoin demande un captcha") from exc
            raise LbcError("Réponse API illisible") from exc
        ads = data.get("ads") or []
        return ads if isinstance(ads, list) else []

    async def _search_html(self, cfg: SearchConfig) -> list[dict]:
        url = build_web_url(cfg, self.settings.lbc_web_url)
        resp = await self._request(
            "GET",
            url,
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        )
        html = resp.text
        ads = ads_from_html(html)
        if not ads and ("captcha-delivery" in html or "Vous avez été bloqué" in html):
            raise LbcBlocked("Leboncoin demande un captcha (page HTML)")
        return ads
