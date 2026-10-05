#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND="$ROOT/src/aflhub"
PYTHON="$ROOT/.venv/bin/python"
REPLAYHUB_PORT="${REPLAYHUB_PORT:-5173}"

command -v python3 >/dev/null || { printf 'Python 3 is required.\n' >&2; exit 1; }
command -v npm >/dev/null || { printf 'Node.js and npm are required.\n' >&2; exit 1; }

if [[ ! -x "$PYTHON" ]]; then
  python3 -m venv "$ROOT/.venv"
fi
if ! "$PYTHON" -c 'import fastapi, uvicorn, numpy, matplotlib, PIL' 2>/dev/null; then
  "$PYTHON" -m pip install -e "$ROOT[app]"
fi
if [[ ! -x "$FRONTEND/node_modules/.bin/vite" ]]; then
  npm ci --prefix "$FRONTEND"
fi

backend_pid=''
frontend_pid=''
cleanup() {
  [[ -z "$frontend_pid" ]] || kill "$frontend_pid" 2>/dev/null || true
  [[ -z "$backend_pid" ]] || kill "$backend_pid" 2>/dev/null || true
  [[ -z "$frontend_pid" ]] || wait "$frontend_pid" 2>/dev/null || true
  [[ -z "$backend_pid" ]] || wait "$backend_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

(cd "$ROOT" && exec "$PYTHON" afl.py app --no-browser) &
backend_pid=$!
(cd "$FRONTEND" && exec ./node_modules/.bin/vite --host 127.0.0.1 --port "$REPLAYHUB_PORT" --strictPort) &
frontend_pid=$!

printf 'AIFL backend:  http://127.0.0.1:8765\n'
printf 'Replayhub:     http://127.0.0.1:%s/replayhub/\n' "$REPLAYHUB_PORT"
printf 'Press Ctrl-C to stop both.\n'

while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 1
done
printf 'A server stopped; shutting down both.\n' >&2
exit 1
