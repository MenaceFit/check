from __future__ import annotations

import html
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from ebaywatch.config import Config

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_config(searches: list[dict] | None = None, **general) -> Config:
    data = {
        "general": {"interval_seconds": 60, "min_delay_per_host": 0, **general},
        "searches": searches if searches is not None else [
            {"name": "Switch", "keywords": "nintendo switch", "countries": ["fr"]}
        ],
    }
    return Config.from_dict(data)


def scard_page(items: list[dict], *, rewrite_after: list[dict] | None = None) -> str:
    """Build an eBay-like s-card search result page."""

    def card(item: dict) -> str:
        iid = item["id"]
        title = html.escape(item["title"])
        price = html.escape(item.get("price", "10,00 EUR"))
        host = item.get("host", "www.ebay.fr")
        return (
            f'<li class="s-card s-card--horizontal" data-listingid="{iid}">'
            f'<div class="su-card-container"><div class="su-card-container__media">'
            f'<a href="https://{host}/itm/{iid}?hash=x"><img class="s-card__image" '
            f'src="https://i.ebayimg.com/images/g/{iid}/s-l140.webp" alt="{title}"></a></div>'
            f'<div class="su-card-container__content"><a class="su-link" href="https://{host}/itm/{iid}?hash=x">'
            f'<div role="heading" class="s-card__title"><span class="su-styled-text primary default">{title}</span>'
            f'<span class="clipped">La page s\'ouvre dans une nouvelle fenêtre ou un nouvel onglet</span></div></a>'
            f'<div class="s-card__attribute-row"><span class="su-styled-text s-card__price">{price}</span></div>'
            f'<div class="s-card__attribute-row"><span class="su-styled-text">+5,00 EUR livraison</span></div>'
            f"</div></div></li>"
        )

    body = "".join(card(i) for i in items)
    if rewrite_after:
        body += '<li class="srp-river-answer srp-river-answer--REWRITE_START"><h3>moins de mots</h3></li>'
        body += "".join(card(i) for i in rewrite_after)
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><title>eBay</title></head><body>'
        f'<div id="srp-river-results"><ul class="srp-results srp-list clearfix">{body}</ul></div></body></html>'
    )


@dataclass
class FakeEbay:
    """State of the local fake eBay + Discord server."""

    pages: dict[str, str] = field(default_factory=dict)       # market code -> html
    status: dict[str, int] = field(default_factory=dict)      # market code -> forced status
    requests: list[dict] = field(default_factory=list)
    discord_posts: list[dict] = field(default_factory=list)
    telegram_posts: list[dict] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    base_url: str = ""

    def url_for(self, market: str) -> str:
        return f"{self.base_url}/{market}"


@pytest.fixture
def fake_ebay() -> Iterator[FakeEbay]:
    state = FakeEbay()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # silence
            pass

        def _send(self, status: int, body: str, ctype: str = "text/html; charset=utf-8") -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            parts = parsed.path.strip("/").split("/")
            market = parts[0] if parts else ""
            with state.lock:
                state.requests.append({
                    "market": market, "path": parsed.path, "query": parse_qs(parsed.query),
                    "headers": dict(self.headers),
                })
                status = state.status.get(market, 200)
                page = state.pages.get(market, scard_page([]))
            self._send(status, page if status == 200 else "<html>error</html>")

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            with state.lock:
                if self.path.startswith("/discord"):
                    state.discord_posts.append(payload)
                else:
                    state.telegram_posts.append({"path": self.path, **payload})
            if self.path.startswith("/discord"):
                self.send_response(204)
                self.end_headers()
            else:
                self._send(200, json.dumps({"ok": True}), "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.base_url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
