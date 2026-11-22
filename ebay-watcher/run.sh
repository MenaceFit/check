#!/usr/bin/env bash
# eBay Watcher - lanceur macOS / Linux. Usage : ./run.sh [commande]
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f ".venv/installed.ok" ]; then
    echo "[eBay Watcher] Installation (une seule fois, environ 1 minute)..."
    PY=""
    for candidate in python3.13 python3.12 python3.11 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && \
           "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
            PY="$candidate"; break
        fi
    done
    if [ -z "$PY" ]; then
        echo "Python 3.11 ou plus récent est requis : https://www.python.org/downloads/"
        exit 1
    fi
    [ -x ".venv/bin/python" ] || "$PY" -m venv .venv
    .venv/bin/python -m pip install --disable-pip-version-check -q --upgrade pip
    .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
    touch .venv/installed.ok
    echo "[eBay Watcher] Installation terminée."
fi

exec .venv/bin/python -m ebaywatch "$@"
