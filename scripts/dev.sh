#!/usr/bin/env bash
# Start Cairn locally: API (with the in-process worker) on :8000, console on :3000.
# Needs PostgreSQL 16 with pgvector on localhost (or `docker compose up db`).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT/backend"
if [ ! -f .env ] && [ -z "${CAIRN_DATABASE_URL:-}" ]; then
  echo "Create backend/.env with CAIRN_DATABASE_URL and CAIRN_ADMIN_DATABASE_URL (see .env.example)." >&2
  exit 1
fi
if [ ! -d "$ROOT/.venv" ]; then python3 -m venv "$ROOT/.venv"; fi
source "$ROOT/.venv/bin/activate"
pip install -q -e ".[dev]"
cairn db migrate
cairn seed
if [ "${1:-}" = "--demo" ]; then cairn demo-traffic; fi

(cd "$ROOT/widget" && npm install --silent && npm run build --silent)
(cd "$ROOT/console" && npm install --silent)

uvicorn cairn.api.app:app --port 8000 &
API=$!
trap 'kill $API' EXIT
cd "$ROOT/console" && npx next dev -p 3000
