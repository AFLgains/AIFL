#!/bin/sh
# Start the afl_sim app (Develop / Play / Inspect / Lab) on Linux or macOS and open it in the browser.
# Press Ctrl+C to stop the app. Running this again restarts it (with the latest code).
# Another port:  ./run_app.sh 8766          The Windows version is run_app.bat.
cd "$(dirname "$0")" || exit 1
PORT="${1:-8765}"
URL="http://127.0.0.1:$PORT/"

# The environment (.venv). Three cases:
#   1. its Python does not start (the folder was copied from another computer): move it aside to .venv.broken,
#      then build a new one;
#   2. no .venv: build one (setup.sh);
#   3. its Python starts but the app's packages are missing: install them into it.
# afl.py puts src/ on the path itself, so the aflsim package does not need to be installed for the app to start.
if [ -e .venv/bin/python ] && ! .venv/bin/python -c 'import sys' >/dev/null 2>&1; then
  echo "The .venv folder doesn't work on this computer (it was probably copied from another one)."
  rm -rf .venv.broken
  mv .venv .venv.broken || { echo "Could not move .venv aside. Delete .venv and run this again."; exit 1; }
  echo "Moved it to .venv.broken (delete that folder when the new environment works)."
fi
if [ ! -x .venv/bin/python ]; then
  echo "First run on this computer: setting up the environment..."
  sh ./setup.sh || exit 1
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, numpy' >/dev/null 2>&1; then
  echo "Some of the app's packages are missing: installing them..."
  .venv/bin/python -m pip install -r requirements.lock || { echo "The install failed (see the messages above)."; exit 1; }
fi

# an app already on this port (an old copy): stop it, so this starts the current code. Only a Python process is stopped.
if command -v lsof >/dev/null 2>&1; then
  for pid in $(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null); do
    if ps -p "$pid" -o comm= 2>/dev/null | grep -qi python; then
      echo "Stopping the copy already running on port $PORT (process $pid)..."
      kill "$pid" 2>/dev/null
      sleep 1
    fi
  done
fi

echo "Starting afl_sim at $URL  (press Ctrl+C to stop)"
PYTHONIOENCODING=utf-8 exec .venv/bin/python afl.py app --port "$PORT"
