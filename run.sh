#!/usr/bin/env bash
# Launcher for the Grim Dawn Build Assistant.
#
#   • Double-click this file in your file manager (choose "Run"), or
#   • run  ./run.sh  from a terminal.
#
# On first run it creates a local virtual environment (.venv) and installs
# dependencies; after that it just launches the app.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

PY="${PYTHON:-python3}"
VENV=".venv"

if [ ! -d "$VENV" ]; then
    echo "First run: setting up the environment (this can take a minute)…"
    "$PY" -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -e .
fi

# Ensure GUI deps exist even if the venv predates them.
"$VENV/bin/python" -c "import PySide6" 2>/dev/null \
    || "$VENV/bin/pip" install --quiet PySide6 platformdirs

# src/ layout: make the package importable without requiring an editable install.
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

exec "$VENV/bin/python" -m gd_assistant "$@"
