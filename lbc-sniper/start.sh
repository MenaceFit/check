#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -d .venv ] || { echo "Lancez d'abord ./install.sh"; exit 1; }
exec .venv/bin/python -m lbcsniper
