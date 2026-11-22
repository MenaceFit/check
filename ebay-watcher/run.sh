#!/usr/bin/env bash
# eBay Watcher - lanceur macOS / Linux. Usage : ./run.sh [commande]
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    echo "[eBay Watcher] Première installation, création de l'environnement Python..."
    PY=$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)
    "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
        || { echo "Python 3.11+ requis (trouvé : $("$PY" --version))"; exit 1; }
    "$PY" -m venv .venv
    .venv/bin/python -m pip install --upgrade pip >/dev/null
    .venv/bin/python -m pip install -r requirements.txt
fi

exec .venv/bin/python -m ebaywatch "$@"
