#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f config.json ]; then
    echo "[ascension] config.json not found"
    echo "[ascension] copy config.json.template to config.json and edit it"
    exit 1
fi

source .venv/bin/activate
python -m src.orchestrator "$@"
