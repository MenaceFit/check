"""Command line entry point.

    python -m ebaywatch                 interface terminal (par défaut)
    python -m ebaywatch run             mode console sans interface (serveur, VPS…)
    python -m ebaywatch search "ps5" -c fr uk   recherche ponctuelle, affiche les résultats
    python -m ebaywatch doctor          diagnostic complet (réseau, parsing, notifications)
    python -m ebaywatch test-notify     envoie une notification de test
    python -m ebaywatch init            crée config.toml à partir du modèle
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import time
from importlib import resources
from pathlib import Path

import httpx
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import Config, ConfigError, Search
from .engine import LogEvent, NewListing
from .filters import ListingFilter
from .markets import MARKETS, get_market
from .models import Listing
from .notifiers import build_notifiers
from .runtime import build_runtime
from .sources import create_source
from .sources.base import BlockedSourceError, SourceError
from .sources.html import build_search_url

console = Console(highlight=False)


def template_text() -> str:
    return resources.files("ebaywatch").joinpath("data/config.example.toml").read_text(encoding="utf-8")


def ensure_config(path: Path) -> bool:
    """Create the config file from the template if it does not exist. Returns True if created."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template_text(), encoding="utf-8")
    return True


def load_config(path: Path) -> Config:
    if ensure_config(path):
        console.print(f"[green]✔ Fichier de configuration créé :[/] {path.resolve()}")
    return Config.load(path)


def _listing_table(listings: list[tuple[Listing, str]], title: str) -> Table:
    table = Table(title=title, show_lines=False, expand=True)
    table.add_column("Pays", width=4)
    table.add_column("ID", width=13, style="dim")
    table.add_column("Titre", ratio=3, overflow="fold")
    table.add_column("Prix", justify="right", style="bold", width=13)
    table.add_column("Livraison", ratio=1, overflow="fold")
    table.add_column("Filtre", ratio=1, overflow="fold")
    for listing, verdict in listings:
        table.add_row(listing.market.upper(), listing.item_id, listing.title, listing.display_price,
                      listing.shipping_text, verdict)
    return table


# --------------------------------------------------------------------- run
async def _run_headless(config: Config) -> int:
    def on_event(event) -> None:
        if isinstance(event, NewListing):
            l = event.listing
            market = get_market(l.market)
            console.print(
                f"[bold green]🆕 {time.strftime('%H:%M:%S')}[/] [cyan]{market.code.upper()}[/] "
                f"[magenta]{l.search_name}[/] — {l.title} — [bold]{l.display_price}[/] {l.shipping_text}\n"
                f"   [link={l.url}]{l.url}[/link]",
                markup=True, highlight=False,
            )
            if config.notifications.sound:
                console.bell()
        elif isinstance(event, LogEvent):
            style = {"warning": "yellow", "error": "bold red"}.get(event.level, "dim")
            console.print(f"[{style}]{time.strftime('%H:%M:%S')}  {event.message}[/]", markup=True)

    runtime = build_runtime(config, on_event=on_event,
                            on_notify_error=lambda m: console.print(f"[yellow]{m}[/]"))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):   # Windows
            pass
    await runtime.engine.start()
    console.print("[dim]Ctrl+C pour arrêter.[/]")
    try:
        await stop.wait()
    except asyncio.CancelledError:
        pass
    finally:
        await runtime.aclose()
        runtime.store.close()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if not any(s.enabled for s in config.searches):
        console.print("[red]Aucune recherche active dans la configuration.[/]")
        return 1
    try:
        return asyncio.run(_run_headless(config))
    except KeyboardInterrupt:
        console.print("\n[dim]Arrêt.[/]")
        return 0


# ------------------------------------------------------------------ search
async def _search_once(config: Config, search: Search, show_all: bool) -> int:
    source = create_source(config)
    flt = ListingFilter(search, config)
    status = 0
    try:
        for code in search.countries:
            market = get_market(code)
            console.print(f"[dim]GET {build_search_url(search, market, config)}[/]")
            started = time.monotonic()
            try:
                listings = await source.search(search, market)
            except BlockedSourceError as exc:
                console.print(f"[bold red]✘ {market.host} : {exc}[/]")
                status = 2
                continue
            except SourceError as exc:
                console.print(f"[red]✘ {market.host} : {exc}[/]")
                status = 2
                continue
            rows = []
            kept = 0
            for listing in listings:
                decision = flt.check(listing)
                kept += decision.accepted
                if decision.accepted or show_all:
                    rows.append((listing, "✔" if decision.accepted else f"✘ {decision.reason}"))
            elapsed = time.monotonic() - started
            console.print(_listing_table(
                rows, f"{market.flag} {market.host} — {len(listings)} annonces lues, {kept} retenues "
                      f"({elapsed:.1f} s) — les plus récentes en premier"))
    finally:
        await source.aclose()
    return status


def cmd_search(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    try:
        search = Search.from_dict({
            "name": "recherche ponctuelle",
            "keywords": args.keywords,
            "countries": args.countries,
            "min_price": args.min_price,
            "max_price": args.max_price,
            "currency": args.currency,
            "exclude": args.exclude or [],
            "buying_format": args.format,
            "condition": args.condition,
        })
    except ConfigError as exc:
        console.print(f"[red]{exc}[/]")
        return 1
    return asyncio.run(_search_once(config, search, args.all))


# ------------------------------------------------------------------ doctor
async def _doctor(config: Config, countries: list[str], keywords: str) -> int:
    ok = True
    console.rule("[bold]Diagnostic eBay Watcher")
    console.print(f"Version {__version__} — Python {sys.version.split()[0]} — source : [bold]{config.general.backend}[/]")
    console.print(f"Configuration : {config.path}")
    console.print(f"Base de données : {config.database_path}")
    console.print(f"Recherches : {len(config.searches)} ({sum(s.enabled for s in config.searches)} actives)\n")

    probe = Search(name="doctor", keywords=keywords, countries=countries)
    source = create_source(config)
    table = Table(title=f"Test de recherche « {keywords} » (tri : plus récentes)")
    for col in ("Pays", "Résultat", "Annonces", "Temps", "Exemple (la plus récente)"):
        table.add_column(col, overflow="fold")
    try:
        for code in countries:
            market = get_market(code)
            started = time.monotonic()
            try:
                listings = await source.search(probe, market)
            except BlockedSourceError as exc:
                ok = False
                table.add_row(market.host, "[bold red]BLOQUÉ[/]", "-", f"{time.monotonic() - started:.1f}s", str(exc))
                continue
            except SourceError as exc:
                ok = False
                table.add_row(market.host, "[red]ERREUR[/]", "-", f"{time.monotonic() - started:.1f}s", str(exc))
                continue
            elapsed = f"{time.monotonic() - started:.1f}s"
            if not listings:
                ok = False
                table.add_row(market.host, "[yellow]0 annonce[/]", "0", elapsed,
                              "Page reçue mais aucune annonce reconnue (mise en page eBay modifiée ?)")
                continue
            sample = listings[0]
            with_price = sum(1 for l in listings if l.price is not None)
            table.add_row(market.host, "[green]OK[/]", f"{len(listings)} ({with_price} avec prix)", elapsed,
                          f"{sample.title[:60]} — {sample.display_price}\n{sample.url}")
    finally:
        await source.aclose()
    console.print(table)

    n = config.notifications
    console.print("\n[bold]Notifications[/]")
    console.print(f"  Discord  : {'configuré' if n.discord_webhook_url else 'non configuré'}")
    console.print(f"  Telegram : {'configuré' if n.telegram_bot_token and n.telegram_chat_id else 'non configuré'}")
    console.print("  (python -m ebaywatch test-notify pour envoyer un message de test)\n")
    if ok:
        console.print("[bold green]✔ Tout fonctionne. Lance l'interface : python -m ebaywatch[/]")
    else:
        console.print(
            "[bold yellow]⚠ Au moins un pays a échoué.[/] Si c'est « BLOQUÉ » : attends 10-30 min, augmente "
            "interval_seconds, évite les VPN/hébergeurs, ou passe sur backend = \"api\" (clés gratuites)."
        )
    return 0 if ok else 2


def cmd_doctor(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    countries = args.countries or sorted({c for s in config.searches for c in s.countries}) or ["fr"]
    return asyncio.run(_doctor(config, countries, args.keywords))


# ------------------------------------------------------------- test-notify
async def _test_notify(config: Config) -> int:
    listing = Listing(item_id="0", market="fr", title="Test eBay Watcher — les notifications fonctionnent ✅",
                      url="https://www.ebay.fr", price=1.0, currency="EUR", search_name="test",
                      image_url="https://ir.ebaystatic.com/cr/v/c01/s_1x2.png")
    async with httpx.AsyncClient(timeout=15) as client:
        notifiers = build_notifiers(config.notifications, client)
        if not notifiers:
            console.print("[yellow]Aucun canal configuré (Discord / Telegram) dans config.toml.[/]")
            return 1
        status = 0
        for notifier in notifiers:
            try:
                await notifier.send(listing)
                console.print(f"[green]✔ {notifier.name} : message envoyé[/]")
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]✘ {notifier.name} : {exc}[/]")
                status = 2
        return status


def cmd_test_notify(args: argparse.Namespace) -> int:
    return asyncio.run(_test_notify(load_config(args.config)))


def cmd_init(args: argparse.Namespace) -> int:
    if args.config.exists() and not args.force:
        console.print(f"[yellow]{args.config} existe déjà (utilise --force pour l'écraser).[/]")
        return 1
    args.config.write_text(template_text(), encoding="utf-8")
    console.print(f"[green]✔ {args.config.resolve()} créé.[/]")
    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    from .tui import EbayWatchApp

    config = load_config(args.config)
    EbayWatchApp(config, autostart=not args.no_autostart).run()
    return 0


# -------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ebaywatch", description="Surveille les nouvelles annonces eBay.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-f", "--config", type=Path, default=Path("config.toml"),
                        help="fichier de configuration (défaut : ./config.toml)")
    parser.add_argument("-v", "--verbose", action="store_true", help="journal détaillé dans ebaywatch.log")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("tui", help="interface terminal (défaut)")
    p.add_argument("--no-autostart", action="store_true", help="ne pas démarrer la surveillance au lancement")
    p.set_defaults(func=cmd_tui)

    p = sub.add_parser("run", help="surveillance en mode console, sans interface")
    p.set_defaults(func=cmd_run)

    countries_help = "pays : " + " ".join(MARKETS)
    p = sub.add_parser("search", help="recherche ponctuelle (affiche les annonces les plus récentes)")
    p.add_argument("keywords")
    p.add_argument("-c", "--countries", nargs="+", default=["fr"], help=countries_help)
    p.add_argument("--min-price", type=float)
    p.add_argument("--max-price", type=float)
    p.add_argument("--currency", default="EUR")
    p.add_argument("--exclude", nargs="*")
    p.add_argument("--format", choices=["all", "bin", "auction"], default="all")
    p.add_argument("--condition", choices=["all", "new", "used"], default="all")
    p.add_argument("--all", action="store_true", help="afficher aussi les annonces rejetées par les filtres")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("doctor", help="diagnostic : teste chaque pays et les notifications")
    p.add_argument("-c", "--countries", nargs="+", help=countries_help)
    p.add_argument("-k", "--keywords", default="iphone", help="mot-clé de test (défaut : iphone)")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("test-notify", help="envoie une notification de test")
    p.set_defaults(func=cmd_test_notify)

    p = sub.add_parser("init", help="crée config.toml à partir du modèle")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        filename="ebaywatch.log" if args.verbose else None,
        level=logging.DEBUG if args.verbose else logging.CRITICAL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.command is None:
        args.func = cmd_tui
        args.no_autostart = False
    try:
        return args.func(args)
    except ConfigError as exc:
        console.print(f"[bold red]Erreur de configuration :[/] {exc}")
        return 1
    except ValueError as exc:
        console.print(f"[bold red]Erreur :[/] {exc}")
        return 1
