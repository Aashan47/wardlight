#!/usr/bin/env bash
# Start the Wardlight API. Used by the systemd unit and for local runs.
#   deploy/run.sh                 live data from data/work (127.0.0.1:8000)
#   WARDLIGHT_FIXTURE=1 deploy/run.sh   fixtures only, no data/work
#   HOST=0.0.0.0 PORT=8080 deploy/run.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"
[ -x "$PY" ] || { echo "no .venv in $(pwd); create it first (deploy/README.md)" >&2; exit 1; }
if [ "${WARDLIGHT_FIXTURE:-0}" != "1" ]; then
  for f in facilities matches facility_results nerc_rows; do
    [ -f "data/work/$f.parquet" ] || { echo "data/work/$f.parquet missing; copy data/work or set WARDLIGHT_FIXTURE=1" >&2; exit 1; }
  done
fi
[ -f web/dist/index.html ] || echo "warning: web/dist is not built; only /api will answer" >&2
# memory: Arrow frees into the system allocator; glibc keeps few arenas (Linux)
export ARROW_DEFAULT_MEMORY_POOL="${ARROW_DEFAULT_MEMORY_POOL:-system}"
export MALLOC_ARENA_MAX="${MALLOC_ARENA_MAX:-2}"
# the on-disk store (api/store_build.py) is built on first start when absent; build it ahead with
#   .venv/bin/python -m api.store_build
exec "$PY" -m uvicorn --factory api.main:create_app \
  --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" --workers 1 \
  --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
  --timeout-keep-alive 30 --log-level "${LOG_LEVEL:-info}"
