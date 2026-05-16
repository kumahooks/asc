#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

source .venv/bin/activate

if ! python -c "import PyInstaller" 2>/dev/null; then
    echo "[ascension] installing pyinstaller..."
    pip install pyinstaller
fi

echo "[ascension] building orchestrator..."
pyinstaller \
    --onefile \
    --name ascension-orchestrator \
    --add-data "beep.wav:." \
    --collect-all playwright \
    src/orchestrator.py

echo "[ascension] building sniffer..."
pyinstaller \
    --onefile \
    --name ascension-sniff \
    --collect-all playwright \
    src/sniff.py

echo "[ascension] binaries in dist/"
ls -lh dist/ascension-*
