from __future__ import annotations

from ..config import Config
from .api import ApiSource
from .base import BlockedSourceError, Source, SourceError
from .html import HtmlSource


def create_source(config: Config) -> Source:
    if config.general.backend == "api":
        return ApiSource(config)
    return HtmlSource(config)


__all__ = ["ApiSource", "BlockedSourceError", "HtmlSource", "Source", "SourceError", "create_source"]
