#!/bin/sh
# One-time setup on a new computer (Linux or macOS): builds the project's Python environment (.venv) and installs the
# exact package versions it was built with (requirements.lock). Needs Python 3.11+ (3.13 recommended) and internet
# for the first install. run_app.sh calls this automatically when .venv is missing. The Windows version is setup.bat.
cd "$(dirname "$0")" || exit 1

if [ -x .venv/bin/python ]; then
  echo "The environment already exists (.venv). To rebuild it, delete the .venv folder and run this again."
  exit 0
fi

# find a Python 3.11 or newer: the newest named one first, then python3 and python
PY=""
for c in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    PY="$c"
    break
  fi
done
if [ -z "$PY" ]; then
  echo
  echo "Python 3.11 or newer was not found. Install Python 3.13, then run this again:"
  echo "  macOS:          https://www.python.org/downloads/  (or: brew install python@3.13)"
  echo "  Debian/Ubuntu:  sudo apt install python3 python3-venv"
  echo "  Fedora:         sudo dnf install python3"
  exit 1
fi
echo "Using: $PY ($("$PY" --version 2>&1))"

fail() {
  echo
  echo "Setup failed (see the messages above). Fix the problem and run setup.sh again."
  rm -rf .venv                                   # it did not exist before this run: remove the half-built one
  exit 1
}

# On Linux, a plain "pip install torch" downloads the CUDA build (several GB). The CPU build is enough here.
EXTRA=""
if [ "$(uname -s)" = "Linux" ]; then
  EXTRA="--extra-index-url https://download.pytorch.org/whl/cpu"
fi

echo
echo "[1/3] Creating the environment (.venv)..."
"$PY" -m venv .venv || {
  echo "(On Debian/Ubuntu this usually means the venv module is missing: sudo apt install python3-venv)"
  fail
}
echo "[2/3] Installing the packages (first time: several minutes, PyTorch is large)..."
.venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1      # not needed to succeed
# shellcheck disable=SC2086
.venv/bin/python -m pip install -r requirements.lock $EXTRA || fail
echo "[3/3] Installing afl_sim itself..."
.venv/bin/python -m pip install -e . --no-deps || fail
echo
echo "Done. Start the app with ./run_app.sh"
