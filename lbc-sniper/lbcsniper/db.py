"""Stockage SQLite : recherches, annonces déjà vues, flux des annonces trouvées, réglages."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from .models import Ad, SearchConfig

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS seen (
    search_id INTEGER NOT NULL,
    list_id TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    PRIMARY KEY (search_id, list_id)
);
CREATE TABLE IF NOT EXISTS ads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL,
    list_id TEXT NOT NULL,
    data TEXT NOT NULL,
    found_at TEXT NOT NULL,
    latency_s REAL,
    notified INTEGER NOT NULL DEFAULT 0,
    reject_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ads_found ON ads(found_at DESC);
CREATE INDEX IF NOT EXISTS ads_search ON ads(search_id, found_at DESC);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS: dict[str, Any] = {
    "default_channel_id": "",
    "default_webhook_url": "",
    "alert_channel_id": "",
    "paused": False,
    "source_mode": "auto",
    "keep_ads": 3000,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    @classmethod
    async def open(cls, path: Path | str) -> "Database":
        conn = await aiosqlite.connect(str(path))
        conn.row_factory = aiosqlite.Row
        await conn.executescript(SCHEMA)
        await conn.commit()
        return cls(conn)

    async def close(self) -> None:
        await self.conn.close()

    # ---------------- Recherches ----------------
    async def list_searches(self) -> list[tuple[int, SearchConfig]]:
        async with self.conn.execute("SELECT id, config FROM searches ORDER BY id") as cur:
            rows = await cur.fetchall()
        return [(r["id"], SearchConfig.model_validate_json(r["config"])) for r in rows]

    async def get_search(self, search_id: int) -> SearchConfig | None:
        async with self.conn.execute("SELECT config FROM searches WHERE id=?", (search_id,)) as cur:
            row = await cur.fetchone()
        return SearchConfig.model_validate_json(row["config"]) if row else None

    async def create_search(self, cfg: SearchConfig) -> int:
        now = _now()
        cur = await self.conn.execute(
            "INSERT INTO searches (config, created_at, updated_at) VALUES (?, ?, ?)",
            (cfg.model_dump_json(), now, now),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def update_search(self, search_id: int, cfg: SearchConfig) -> bool:
        cur = await self.conn.execute(
            "UPDATE searches SET config=?, updated_at=? WHERE id=?",
            (cfg.model_dump_json(), _now(), search_id),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def delete_search(self, search_id: int) -> bool:
        cur = await self.conn.execute("DELETE FROM searches WHERE id=?", (search_id,))
        await self.conn.execute("DELETE FROM seen WHERE search_id=?", (search_id,))
        await self.conn.execute("DELETE FROM ads WHERE search_id=?", (search_id,))
        await self.conn.commit()
        return cur.rowcount > 0

    # ---------------- Annonces vues ----------------
    async def load_seen(self, search_id: int, limit: int = 5000) -> set[str]:
        async with self.conn.execute(
            "SELECT list_id FROM seen WHERE search_id=? ORDER BY seen_at DESC LIMIT ?",
            (search_id, limit),
        ) as cur:
            return {r["list_id"] for r in await cur.fetchall()}

    async def add_seen(self, search_id: int, list_ids: list[str]) -> None:
        if not list_ids:
            return
        now = _now()
        await self.conn.executemany(
            "INSERT OR IGNORE INTO seen (search_id, list_id, seen_at) VALUES (?, ?, ?)",
            [(search_id, lid, now) for lid in list_ids],
        )
        await self.conn.commit()

    async def reset_seen(self, search_id: int) -> None:
        await self.conn.execute("DELETE FROM seen WHERE search_id=?", (search_id,))
        await self.conn.commit()

    async def prune(self, keep_ads: int = 3000, keep_seen_per_search: int = 5000) -> None:
        await self.conn.execute(
            "DELETE FROM ads WHERE id NOT IN (SELECT id FROM ads ORDER BY id DESC LIMIT ?)",
            (keep_ads,),
        )
        await self.conn.execute(
            """DELETE FROM seen WHERE rowid IN (
                 SELECT rowid FROM (
                   SELECT rowid, ROW_NUMBER() OVER (PARTITION BY search_id ORDER BY seen_at DESC) rn
                   FROM seen) WHERE rn > ?)""",
            (keep_seen_per_search,),
        )
        await self.conn.commit()

    # ---------------- Flux d'annonces ----------------
    async def add_ad(
        self, search_id: int, ad: Ad, latency_s: float | None, notified: bool, reason: str
    ) -> int:
        cur = await self.conn.execute(
            "INSERT INTO ads (search_id, list_id, data, found_at, latency_s, notified, reject_reason)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (search_id, ad.list_id, ad.model_dump_json(), _now(), latency_s, int(notified), reason),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def recent_ads(
        self, limit: int = 100, search_id: int | None = None, only_notified: bool = False
    ) -> list[dict]:
        sql = "SELECT * FROM ads"
        cond, args = [], []
        if search_id is not None:
            cond.append("search_id=?")
            args.append(search_id)
        if only_notified:
            cond.append("notified=1")
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        async with self.conn.execute(sql, args) as cur:
            rows = await cur.fetchall()
        return [self._ad_row(r) for r in rows]

    async def last_ad(self, search_id: int) -> Ad | None:
        async with self.conn.execute(
            "SELECT data FROM ads WHERE search_id=? ORDER BY id DESC LIMIT 1", (search_id,)
        ) as cur:
            row = await cur.fetchone()
        return Ad.model_validate_json(row["data"]) if row else None

    async def counts(self) -> dict:
        q = """SELECT search_id, COUNT(*) total, SUM(notified) notified, AVG(CASE WHEN notified=1 THEN latency_s END) avg_latency
               FROM ads GROUP BY search_id"""
        async with self.conn.execute(q) as cur:
            rows = await cur.fetchall()
        return {
            r["search_id"]: {
                "found": r["total"],
                "notified": r["notified"] or 0,
                "avg_latency_s": round(r["avg_latency"], 1) if r["avg_latency"] is not None else None,
            }
            for r in rows
        }

    @staticmethod
    def _ad_row(r: aiosqlite.Row) -> dict:
        return {
            "id": r["id"],
            "search_id": r["search_id"],
            "ad": json.loads(r["data"]),
            "found_at": r["found_at"],
            "latency_s": r["latency_s"],
            "notified": bool(r["notified"]),
            "reject_reason": r["reject_reason"],
        }

    # ---------------- Réglages ----------------
    async def get_settings(self) -> dict:
        out = dict(DEFAULT_SETTINGS)
        async with self.conn.execute("SELECT key, value FROM settings") as cur:
            for r in await cur.fetchall():
                out[r["key"]] = json.loads(r["value"])
        return out

    async def set_settings(self, values: dict) -> dict:
        for key, value in values.items():
            if key not in DEFAULT_SETTINGS:
                continue
            await self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )
        await self.conn.commit()
        return await self.get_settings()
