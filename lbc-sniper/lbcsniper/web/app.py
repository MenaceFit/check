"""Dashboard web (FastAPI) : configuration des recherches, flux en direct, statistiques."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from ..lbc.client import LbcError
from ..lbc.query import build_payload, build_web_url, config_from_url
from ..models import DISPLAY_FIELDS, Ad, SearchConfig
from ..notifier import NotifyError

if TYPE_CHECKING:
    from ..engine import Engine

STATIC = Path(__file__).parent / "static"
COOKIE = "lbcsniper_session"
SESSION_DAYS = 30


class LoginBody(BaseModel):
    password: str


class UrlBody(BaseModel):
    url: str
    base: Optional[SearchConfig] = None


def _sign(secret: str, expiry: int) -> str:
    mac = hmac.new(secret.encode(), str(expiry).encode(), hashlib.sha256).hexdigest()
    return f"{expiry}.{mac}"


def _valid(secret: str, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    exp, _, _ = token.partition(".")
    if not exp.isdigit() or int(exp) < time.time():
        return False
    return hmac.compare_digest(_sign(secret, int(exp)), token)


def create_app(engine: "Engine", bot: Any = None) -> FastAPI:
    settings = engine.settings
    app = FastAPI(title="LBC Sniper", version=__version__, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    public = {"/api/login", "/api/me"}

    @app.middleware("http")
    async def auth(request: Request, call_next):
        path = request.url.path
        if (
            settings.dashboard_password
            and path.startswith("/api/")
            and path not in public
            and not _valid(settings.secret_key, request.cookies.get(COOKIE))
        ):
            return JSONResponse({"detail": "Non authentifié"}, status_code=401)
        return await call_next(request)

    # ------------------------------------------------------------------ pages
    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html")

    # ------------------------------------------------------------------- auth
    @app.get("/api/me")
    async def me(request: Request):
        required = bool(settings.dashboard_password)
        return {
            "auth_required": required,
            "authenticated": (not required) or _valid(settings.secret_key, request.cookies.get(COOKIE)),
        }

    @app.post("/api/login")
    async def login(body: LoginBody, response: Response):
        if not settings.dashboard_password or not hmac.compare_digest(
            body.password.encode(), settings.dashboard_password.encode()
        ):
            await asyncio.sleep(1)  # ralentit les tentatives en force brute
            raise HTTPException(401, "Mot de passe incorrect")
        expiry = int(time.time()) + SESSION_DAYS * 86400
        response.set_cookie(
            COOKIE, _sign(settings.secret_key, expiry), max_age=SESSION_DAYS * 86400,
            httponly=True, samesite="strict",
        )
        return {"ok": True}

    @app.post("/api/logout")
    async def logout(response: Response):
        response.delete_cookie(COOKIE)
        return {"ok": True}

    # ------------------------------------------------------------------- meta
    @app.get("/api/meta")
    async def meta():
        bot_info = {"configured": bool(settings.discord_token), "connected": False, "user": None, "channels": []}
        if bot is not None:
            bot_info["connected"] = bool(getattr(bot, "is_ready", lambda: False)())
            if bot_info["connected"]:
                bot_info["user"] = str(bot.user)
                bot_info["channels"] = bot.text_channels()
                bot_info["invite_url"] = (
                    f"https://discord.com/oauth2/authorize?client_id={bot.user.id}"
                    "&permissions=19456&scope=bot%20applications.commands"
                )
        return {
            "version": __version__,
            "display_fields": DISPLAY_FIELDS,
            "min_interval": settings.min_interval,
            "max_requests_per_minute": settings.max_requests_per_minute,
            "bot": bot_info,
        }

    # -------------------------------------------------------------- searches
    async def _search_out(sid: int, cfg: SearchConfig, counts: dict) -> dict:
        w = engine.watchers.get(sid)
        return {
            "id": sid,
            "config": cfg.model_dump(mode="json"),
            "status": w.status() if w else {"state": "disabled" if not cfg.enabled else "stopped"},
            "counts": counts.get(sid, {"found": 0, "notified": 0, "avg_latency_s": None}),
            "web_url": build_web_url(cfg),
        }

    @app.get("/api/searches")
    async def list_searches():
        counts = await engine.db.counts()
        return [await _search_out(sid, cfg, counts) for sid, cfg in await engine.db.list_searches()]

    @app.get("/api/searches/{sid}")
    async def get_search(sid: int):
        cfg = await engine.db.get_search(sid)
        if not cfg:
            raise HTTPException(404, "Recherche introuvable")
        return await _search_out(sid, cfg, await engine.db.counts())

    def _clamp(cfg: SearchConfig) -> SearchConfig:
        cfg.interval_seconds = max(settings.min_interval, int(cfg.interval_seconds))
        return cfg

    @app.post("/api/searches")
    async def create_search(cfg: SearchConfig):
        sid = await engine.db.create_search(_clamp(cfg))
        await engine.reload(sid)
        return {"id": sid}

    @app.put("/api/searches/{sid}")
    async def update_search(sid: int, cfg: SearchConfig):
        old = await engine.db.get_search(sid)
        if not old:
            raise HTTPException(404, "Recherche introuvable")
        await engine.db.update_search(sid, _clamp(cfg))
        # Si les critères Leboncoin changent, on repart d'une liste vierge pour éviter un flot d'alertes.
        if build_payload(old) != build_payload(cfg):
            await engine.db.reset_seen(sid)
        await engine.reload(sid)
        return {"id": sid}

    @app.delete("/api/searches/{sid}")
    async def delete_search(sid: int):
        if not await engine.db.delete_search(sid):
            raise HTTPException(404, "Recherche introuvable")
        await engine.reload(sid)
        return {"ok": True}

    @app.post("/api/searches/{sid}/toggle")
    async def toggle_search(sid: int):
        cfg = await engine.db.get_search(sid)
        if not cfg:
            raise HTTPException(404, "Recherche introuvable")
        cfg.enabled = not cfg.enabled
        await engine.db.update_search(sid, cfg)
        await engine.reload(sid)
        return {"enabled": cfg.enabled}

    @app.post("/api/searches/{sid}/duplicate")
    async def duplicate_search(sid: int):
        cfg = await engine.db.get_search(sid)
        if not cfg:
            raise HTTPException(404, "Recherche introuvable")
        cfg.name = f"{cfg.name} (copie)"
        cfg.enabled = False
        new_id = await engine.db.create_search(cfg)
        await engine.reload(new_id)
        return {"id": new_id}

    @app.post("/api/searches/{sid}/run")
    async def run_now(sid: int):
        if not await engine.run_now(sid):
            raise HTTPException(409, "Recherche inactive")
        return engine.watchers[sid].status()

    @app.post("/api/searches/{sid}/reset")
    async def reset_seen(sid: int):
        await engine.db.reset_seen(sid)
        await engine.reload(sid)
        return {"ok": True}

    @app.post("/api/searches/{sid}/test-notification")
    async def test_notification(sid: int):
        cfg = await engine.db.get_search(sid)
        if not cfg:
            raise HTTPException(404, "Recherche introuvable")
        ad = await engine.db.last_ad(sid) or _demo_ad()
        ad = ad.model_copy(update={"title": f"[TEST] {ad.title}"})
        try:
            dest = await engine.notifier.send(ad, cfg, 3.0, engine.settings_cache)
        except NotifyError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True, "via": dest}

    @app.post("/api/preview")
    async def preview(cfg: SearchConfig):
        try:
            results = await engine.preview(cfg)
        except LbcError as exc:
            raise HTTPException(502, str(exc))
        return {"count": len(results), "results": results, "web_url": build_web_url(cfg)}

    @app.post("/api/parse-url")
    async def parse_url(body: UrlBody):
        if "leboncoin.fr" not in body.url:
            raise HTTPException(400, "Collez une URL leboncoin.fr")
        return config_from_url(body.url, body.base).model_dump(mode="json")

    @app.post("/api/build-url")
    async def build_url(cfg: SearchConfig):
        return {"url": build_web_url(cfg), "payload": build_payload(cfg)}

    # ------------------------------------------------------------ ads / logs
    @app.get("/api/ads")
    async def ads(limit: int = 100, search_id: Optional[int] = None, notified: bool = False):
        return await engine.db.recent_ads(min(limit, 500), search_id, notified)

    @app.get("/api/status")
    async def status():
        return engine.status()

    @app.get("/api/logs")
    async def logs():
        return list(engine.bus.logs)[-300:]

    # -------------------------------------------------------------- settings
    @app.get("/api/settings")
    async def get_settings():
        return await engine.db.get_settings()

    @app.put("/api/settings")
    async def put_settings(values: dict):
        if "source_mode" in values and values["source_mode"] not in ("auto", "api", "html"):
            raise HTTPException(400, "source_mode invalide")
        out = await engine.db.set_settings(values)
        await engine.refresh_settings()
        engine.bus.publish("settings", out)
        return out

    # --------------------------------------------------------- import/export
    @app.get("/api/export")
    async def export():
        data = [cfg.model_dump(mode="json") for _, cfg in await engine.db.list_searches()]
        return JSONResponse(
            {"version": __version__, "exported_at": datetime.now(timezone.utc).isoformat(), "searches": data},
            headers={"Content-Disposition": 'attachment; filename="lbc-sniper-recherches.json"'},
        )

    @app.post("/api/import")
    async def import_(payload: dict):
        items = payload.get("searches", [])
        created = []
        for item in items:
            cfg = _clamp(SearchConfig.model_validate(item))
            sid = await engine.db.create_search(cfg)
            await engine.reload(sid)
            created.append(sid)
        return {"created": created}

    # ------------------------------------------------------------- live (SSE)
    @app.get("/api/stream")
    async def stream(request: Request):
        q = engine.bus.subscribe()

        async def gen():
            try:
                yield "retry: 3000\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(q.get(), timeout=15)
                        yield f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
            finally:
                engine.bus.unsubscribe(q)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def _demo_ad() -> Ad:
    return Ad(
        list_id="0",
        title="Exemple — PC Gamer RTX 3070 / Ryzen 5 5600X / 16 Go",
        url="https://www.leboncoin.fr/",
        price=650,
        published_at=datetime.now(timezone.utc),
        body="Ceci est un message de test envoyé depuis le dashboard LBC Sniper.",
        city="Lyon",
        zipcode="69003",
        department="Rhône",
        category="Ordinateurs",
        owner_type="Particulier",
        owner_name="Vendeur test",
        attributes={"État": "Très bon état"},
        shippable=True,
    )
