"""SQLite persistence: already-seen items, baselines and found listings history."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from .models import Listing

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    search_key TEXT NOT NULL,
    item_id    TEXT NOT NULL,
    first_seen REAL NOT NULL,
    PRIMARY KEY (search_key, item_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS baseline (
    search_key TEXT NOT NULL,
    market     TEXT NOT NULL,
    done_at    REAL NOT NULL,
    PRIMARY KEY (search_key, market)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS listings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    search_key  TEXT NOT NULL,
    search_name TEXT NOT NULL,
    item_id     TEXT NOT NULL,
    market      TEXT NOT NULL,
    title       TEXT NOT NULL,
    price       REAL,
    currency    TEXT,
    url         TEXT NOT NULL,
    found_at    TEXT NOT NULL,
    data        TEXT NOT NULL,
    UNIQUE (search_key, item_id)
);
CREATE INDEX IF NOT EXISTS idx_listings_found ON listings(found_at DESC);
"""


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------- baselines
    def is_baselined(self, search_key: str, market: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM baseline WHERE search_key=? AND market=?", (search_key, market)
            ).fetchone()
        return row is not None

    def mark_baselined(self, search_key: str, market: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO baseline(search_key, market, done_at) VALUES (?,?,?)",
                (search_key, market, time.time()),
            )

    # ------------------------------------------------------------------ seen
    def unseen(self, search_key: str, item_ids: Iterable[str]) -> list[str]:
        ids = list(dict.fromkeys(item_ids))
        if not ids:
            return []
        with self._lock:
            known: set[str] = set()
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                marks = ",".join("?" * len(chunk))
                rows = self._conn.execute(
                    f"SELECT item_id FROM seen WHERE search_key=? AND item_id IN ({marks})",
                    (search_key, *chunk),
                ).fetchall()
                known.update(r[0] for r in rows)
        return [i for i in ids if i not in known]

    def mark_seen(self, search_key: str, item_ids: Iterable[str]) -> None:
        now = time.time()
        rows = [(search_key, i, now) for i in dict.fromkeys(item_ids)]
        if not rows:
            return
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.executemany("INSERT OR IGNORE INTO seen VALUES (?,?,?)", rows)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    # -------------------------------------------------------------- listings
    def add_listing(self, search_key: str, listing: Listing) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO listings(search_key, search_name, item_id, market, title, price, currency,"
                " url, found_at, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    search_key,
                    listing.search_name,
                    listing.item_id,
                    listing.market,
                    listing.title,
                    listing.price,
                    listing.currency,
                    listing.url,
                    listing.found_at.isoformat(),
                    json.dumps(listing.to_dict(), ensure_ascii=False),
                ),
            )

    def recent_listings(self, limit: int = 200) -> list[Listing]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM listings ORDER BY found_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for (data,) in rows:
            d = json.loads(data)
            for key in ("created_at", "found_at"):
                if d.get(key):
                    d[key] = datetime.fromisoformat(d[key])
            result.append(Listing(**d))
        return result

    def count_listings(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]

    # ----------------------------------------------------------- maintenance
    def reset_search(self, search_key: str) -> None:
        with self._lock:
            for table in ("seen", "baseline"):
                self._conn.execute(f"DELETE FROM {table} WHERE search_key=?", (search_key,))

    def prune(self, max_age_days: int = 60) -> int:
        cutoff = time.time() - max_age_days * 86400
        with self._lock:
            cur = self._conn.execute("DELETE FROM seen WHERE first_seen < ?", (cutoff,))
            iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
            self._conn.execute("DELETE FROM listings WHERE found_at < ?", (iso,))
            return cur.rowcount
