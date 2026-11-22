"""Common interface for listing sources."""

from __future__ import annotations

from typing import Protocol

from ..config import Search
from ..markets import Market
from ..models import Listing


class SourceError(RuntimeError):
    """A request failed; the engine retries with exponential backoff."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class BlockedSourceError(SourceError):
    """eBay refused the request (anti-bot, 403, 429...). Back off longer."""


class Source(Protocol):
    name: str

    async def search(self, search: Search, market: Market) -> list[Listing]:
        """Return the most recent listings for ``search`` on ``market``, newest first."""
        ...

    async def aclose(self) -> None: ...
