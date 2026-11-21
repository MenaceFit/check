import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def api_response():
    return json.loads((FIXTURES / "api_response.json").read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for k in ("DISCORD_TOKEN", "DASHBOARD_PASSWORD", "DASHBOARD_HOST", "LBC_API_URL", "LBC_WEB_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("LBC_MIN_INTERVAL", "5")
    monkeypatch.setenv("LBC_MAX_REQUESTS_PER_MINUTE", "1000")
    from lbcsniper.config import load_settings

    return load_settings(env_file=tmp_path / "absent.env")
