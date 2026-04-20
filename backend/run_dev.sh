#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  echo "Missing backend/.venv — create it with:"
  echo "  python3.12 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

# --timeout-keep-alive: allow long-lived client connections during slow crew runs
# --timeout-graceful-shutdown: allow in-flight requests up to 300s on reload/shutdown
exec .venv/bin/python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 \
  --timeout-keep-alive 300 \
  --timeout-graceful-shutdown 300 \
  "$@"
