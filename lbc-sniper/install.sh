#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
if ! command -v "$PY" >/dev/null; then
  echo "Python 3.10+ est requis (sudo apt install python3 python3-venv)"; exit 1
fi
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt
[ -f .env ] || { cp .env.example .env; echo "Fichier .env créé : ajoutez-y votre DISCORD_TOKEN."; }
echo "Installation terminée. Lancez ./start.sh"
