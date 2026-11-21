"""Bus d'événements en mémoire (temps réel vers le dashboard) + journal circulaire."""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any


class EventBus:
    def __init__(self, history: int = 500):
        self._subscribers: set[asyncio.Queue] = set()
        self.logs: deque[dict] = deque(maxlen=history)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, kind: str, data: Any) -> None:
        event = {"type": kind, "data": data, "ts": datetime.now(timezone.utc).isoformat()}
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def log(self, level: str, message: str, search_id: int | None = None) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
            "search_id": search_id,
        }
        self.logs.append(entry)
        self.publish("log", entry)


class BusLogHandler(logging.Handler):
    """Renvoie les logs Python (WARNING et plus) vers le journal du dashboard."""

    def __init__(self, bus: EventBus):
        super().__init__(level=logging.WARNING)
        self.bus = bus

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bus.log(record.levelname, record.getMessage())
        except Exception:  # pragma: no cover - ne jamais casser le logging
            pass
