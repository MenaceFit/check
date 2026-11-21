import asyncio
import copy
import json

import httpx
import pytest
import respx

from lbcsniper.db import Database
from lbcsniper.engine import Engine
from lbcsniper.events import EventBus
from lbcsniper.lbc.client import LbcClient
from lbcsniper.models import SearchConfig
from lbcsniper.notifier import Notifier

API = "https://api.leboncoin.fr/finder/search"
HOOK = "https://discord.com/api/webhooks/1/abc"


async def make_engine(settings):
    db = await Database.open(settings.database_path)
    bus = EventBus()
    engine = Engine(settings, db, LbcClient(settings), Notifier(), bus)
    await engine.refresh_settings()
    return engine


async def close(engine):
    await engine.stop()
    await engine.client.close()
    await engine.notifier.close()
    await engine.db.close()


@respx.mock
async def test_first_run_seeds_then_notifies_new_ads(settings, api_response):
    engine = await make_engine(settings)
    older = copy.deepcopy(api_response)
    older["ads"] = older["ads"][1:]  # premier passage : 2 annonces existantes
    route = respx.post(API).mock(side_effect=[httpx.Response(200, json=older), httpx.Response(200, json=api_response)])
    hook = respx.post(HOOK).mock(return_value=httpx.Response(204))

    cfg = SearchConfig(name="PC", keywords="pc gamer", webhook_url=HOOK, exclude_words=["hs"], mention="@everyone")
    sid = await engine.db.create_search(cfg)
    from lbcsniper.engine import Watcher

    w = Watcher(engine, sid, cfg)
    w.seen = await engine.db.load_seen(sid)

    await w.run_once()  # amorçage : aucune alerte
    assert hook.call_count == 0 and len(w.seen) == 2

    await w.run_once()  # une nouvelle annonce publiée
    await asyncio.sleep(0.05)
    assert hook.call_count == 1
    sent = json.loads(hook.calls[0].request.content)
    assert sent["embeds"][0]["title"].startswith("PC Gamer RTX 3070")
    assert sent["content"] == "@everyone"

    # La requête envoyée à Leboncoin contient bien la clé API et le tri par date
    req = route.calls[0].request
    assert req.headers["api_key"] and json.loads(req.content)["sort_by"] == "time"

    ads = await engine.db.recent_ads()
    assert ads[0]["notified"] is True and ads[0]["latency_s"] is not None
    # Rien n'est renvoyé une deuxième fois
    respx.post(API).mock(return_value=httpx.Response(200, json=api_response))
    await w.run_once()
    await asyncio.sleep(0.05)
    assert hook.call_count == 1
    await close(engine)


@respx.mock
async def test_filtered_ads_are_recorded_not_sent(settings, api_response):
    engine = await make_engine(settings)
    respx.post(API).mock(return_value=httpx.Response(200, json=api_response))
    hook = respx.post(HOOK).mock(return_value=httpx.Response(204))
    cfg = SearchConfig(name="x", webhook_url=HOOK, exclude_words=["hs"], notify_existing_on_start=True)
    sid = await engine.db.create_search(cfg)
    from lbcsniper.engine import Watcher

    w = Watcher(engine, sid, cfg)
    await w.run_once()
    await asyncio.sleep(0.05)
    assert hook.call_count == 2  # 3 annonces, 1 exclue (« HS »)
    ads = await engine.db.recent_ads()
    rejected = [a for a in ads if not a["notified"]]
    assert len(rejected) == 1 and "exclu" in rejected[0]["reject_reason"]
    await close(engine)


@respx.mock
async def test_blocked_backoff_and_html_fallback(settings, api_response):
    engine = await make_engine(settings)
    respx.post(API).mock(return_value=httpx.Response(403, text="blocked"))
    html = '<script id="__NEXT_DATA__">' + json.dumps({"props": {"pageProps": {"searchData": {"ads": api_response["ads"]}}}}) + "</script>"
    web = respx.get(url__startswith="https://www.leboncoin.fr/recherche").mock(return_value=httpx.Response(200, text=html))
    cfg = SearchConfig(name="x", interval_seconds=10)
    sid = await engine.db.create_search(cfg)
    from lbcsniper.engine import Watcher

    w = Watcher(engine, sid, cfg)
    delay = await w.run_once()  # mode auto : l'API est bloquée -> la page HTML prend le relais
    assert web.call_count == 1 and len(w.seen) == 3 and 10 <= delay <= 11.6

    engine.client.mode = "api"
    delay = await w.run_once()
    assert w.consecutive_errors == 1 and "403" in w.last_error and delay == 20
    delay = await w.run_once()
    assert delay == 40  # attente exponentielle
    await close(engine)


@respx.mock
async def test_dashboard_api(settings, api_response, monkeypatch):
    from lbcsniper.web.app import create_app

    engine = await make_engine(settings)
    respx.post(API).mock(return_value=httpx.Response(200, json=api_response))
    hook = respx.post(HOOK).mock(return_value=httpx.Response(204))
    app = create_app(engine)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        assert (await c.get("/")).status_code == 200
        assert (await c.get("/api/me")).json() == {"auth_required": False, "authenticated": True}
        meta = (await c.get("/api/meta")).json()
        assert "price" in meta["display_fields"] and meta["bot"]["connected"] is False

        parsed = (await c.post("/api/parse-url", json={"url": "https://www.leboncoin.fr/recherche?text=rtx&price=1-2&mileage=0-10"})).json()
        assert parsed["keywords"] == "rtx" and parsed["extra_filters"][0]["key"] == "mileage"
        assert (await c.post("/api/parse-url", json={"url": "https://exemple.com"})).status_code == 400

        cfg = SearchConfig(name="API test", keywords="rtx", webhook_url=HOOK, interval_seconds=1).model_dump(mode="json")
        sid = (await c.post("/api/searches", json=cfg)).json()["id"]
        lst = (await c.get("/api/searches")).json()
        assert lst[0]["config"]["interval_seconds"] == 5  # bridé au minimum
        assert "text=rtx" in lst[0]["web_url"]

        prev = (await c.post("/api/preview", json=cfg)).json()
        assert prev["count"] == 3

        assert (await c.post(f"/api/searches/{sid}/test-notification")).json()["via"] == "webhook"
        assert hook.call_count == 1

        assert (await c.post(f"/api/searches/{sid}/toggle")).json() == {"enabled": False}
        assert sid not in engine.watchers
        assert (await c.post(f"/api/searches/{sid}/duplicate")).status_code == 200

        s = (await c.put("/api/settings", json={"paused": True, "source_mode": "api"})).json()
        assert s["paused"] is True and engine.paused and engine.client.mode == "api"
        assert (await c.put("/api/settings", json={"source_mode": "nope"})).status_code == 400

        exp = (await c.get("/api/export")).json()
        assert len(exp["searches"]) == 2
        assert len((await c.post("/api/import", json=exp)).json()["created"]) == 2
        assert (await c.delete(f"/api/searches/{sid}")).json() == {"ok": True}
        assert (await c.get(f"/api/searches/{sid}")).status_code == 404
        assert isinstance((await c.get("/api/status")).json()["watchers"], dict)
    await close(engine)


async def test_dashboard_password(settings):
    from lbcsniper.web.app import create_app

    settings.dashboard_password = "s3cret"
    engine = await make_engine(settings)
    app = create_app(engine)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/searches")).status_code == 401
        assert (await c.get("/api/me")).json()["authenticated"] is False
        assert (await c.post("/api/login", json={"password": "faux"})).status_code == 401
        r = await c.post("/api/login", json={"password": "s3cret"})
        assert r.status_code == 200
        assert (await c.get("/api/searches")).status_code == 200
    await close(engine)


async def test_rate_limiter():
    from lbcsniper.lbc.client import RateLimiter

    rl = RateLimiter(3)
    for _ in range(3):
        await rl.acquire()
    assert rl.used_last_minute == 3
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(rl.acquire(), 0.2)
