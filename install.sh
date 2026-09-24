#!/usr/bin/env bash
# Installs plex-smart-logo-updater in a dedicated Python environment (.venv), then runs the setup wizard.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
    echo "Python 3.8 or later is required (command: $PYTHON)." >&2
    exit 1
fi

if [ ! -d .venv ]; then
    echo "Creating the Python environment (.venv)…"
    "$PYTHON" -m venv .venv
fi

echo "Installing dependencies…"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
# rapidocr pulls in OpenCV 5 (opencv-python), which crashes on import on some
# machines: keep only the older "headless" build.
.venv/bin/pip uninstall --quiet -y opencv-python 2>/dev/null || true
.venv/bin/pip install --quiet --force-reinstall --no-deps "opencv-python-headless<4.11"

if ! .venv/bin/python -c "import cv2, plexapi, rapidocr_onnxruntime" 2>/dev/null; then
    echo "The dependencies do not load correctly: see the README." >&2
    exit 1
fi
echo "Dependencies installed."

if [ "${1:-}" != "--no-config" ]; then
    .venv/bin/python configure.py
fi
