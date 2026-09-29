#!/usr/bin/env bash
# Installs plex-smart-logo-updater in a dedicated Python environment (.venv), then runs the setup wizard.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys' 2>/dev/null; then
    echo "Python 3.8 to 3.12 is required (command not found: $PYTHON)." >&2
    exit 1
fi
# The OCR engine (rapidocr-onnxruntime) does not install on Python 3.13 or later yet
if ! "$PYTHON" -c 'import sys; sys.exit(not (3, 8) <= sys.version_info[:2] <= (3, 12))'; then
    version=$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    echo "Python 3.8 to 3.12 is required ($PYTHON is $version)." >&2
    echo "If another version is installed, run for example: PYTHON=python3.12 ./install.sh" >&2
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
