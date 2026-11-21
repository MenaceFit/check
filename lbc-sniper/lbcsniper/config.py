"""Configuration chargée depuis le fichier .env / les variables d'environnement."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "oui", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


@dataclass
class Settings:
    discord_token: str = ""
    discord_guild_id: str = ""
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8080
    dashboard_password: str = ""
    database_path: Path = field(default_factory=lambda: ROOT_DIR / "data" / "lbcsniper.db")
    secret_key: str = ""
    # Garde-fous réseau : intervalle minimum par recherche et plafond global de requêtes.
    min_interval: int = 10
    max_requests_per_minute: int = 30
    lbc_api_url: str = "https://api.leboncoin.fr/finder/search"
    lbc_web_url: str = "https://www.leboncoin.fr"
    lbc_api_key: str = "ba0c2dad52b3ec"
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    log_level: str = "INFO"

    @property
    def is_local_only(self) -> bool:
        return self.dashboard_host in {"127.0.0.1", "localhost", "::1"}


def load_settings(env_file: str | os.PathLike | None = None) -> Settings:
    load_dotenv(env_file or ROOT_DIR / ".env", override=False)
    env = os.environ
    s = Settings(
        discord_token=env.get("DISCORD_TOKEN", "").strip(),
        discord_guild_id=env.get("DISCORD_GUILD_ID", "").strip(),
        dashboard_host=env.get("DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1",
        dashboard_port=_int(env.get("DASHBOARD_PORT"), 8080),
        dashboard_password=env.get("DASHBOARD_PASSWORD", ""),
        min_interval=max(5, _int(env.get("LBC_MIN_INTERVAL"), 10)),
        max_requests_per_minute=max(1, _int(env.get("LBC_MAX_REQUESTS_PER_MINUTE"), 30)),
        log_level=env.get("LOG_LEVEL", "INFO").upper(),
    )
    if env.get("DATABASE_PATH"):
        p = Path(env["DATABASE_PATH"])
        s.database_path = p if p.is_absolute() else ROOT_DIR / p
    # Surcharges utiles pour les tests (serveur Leboncoin simulé).
    s.lbc_api_url = env.get("LBC_API_URL", s.lbc_api_url)
    s.lbc_web_url = env.get("LBC_WEB_URL", s.lbc_web_url).rstrip("/")
    s.lbc_api_key = env.get("LBC_API_KEY", s.lbc_api_key)
    s.user_agent = env.get("LBC_USER_AGENT", s.user_agent)

    s.database_path.parent.mkdir(parents=True, exist_ok=True)
    s.secret_key = env.get("SECRET_KEY", "") or _persistent_secret(s.database_path.parent)

    # Dashboard exposé sur le réseau sans mot de passe : on en génère un.
    if not s.is_local_only and not s.dashboard_password:
        s.dashboard_password = secrets.token_urlsafe(9)
        print(
            "\n[ATTENTION] DASHBOARD_HOST n'est pas local et aucun DASHBOARD_PASSWORD n'est défini.\n"
            f"            Mot de passe temporaire du dashboard : {s.dashboard_password}\n"
        )
    return s


def _persistent_secret(folder: Path) -> str:
    path = folder / "secret.key"
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_hex(32)
    path.write_text(key)
    return key
