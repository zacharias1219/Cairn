#!/usr/bin/env bash
# Create .env (read by docker compose's env_file) with fresh random credentials.
# Never overwrites an existing file.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"
if [ -f "$ENV_FILE" ]; then echo ".env already exists; leaving it alone."; exit 0; fi
rand() { python3 -c "import secrets;print(secrets.token_urlsafe($1))"; }
umask 077
ADMIN_PW=$(rand 24)
APP_PW=$(rand 24)
cat > "$ENV_FILE" <<ENV
POSTGRES_PASSWORD=$ADMIN_PW
CAIRN_DATABASE_URL=postgresql://cairn_app:$APP_PW@db:5432/cairn
CAIRN_ADMIN_DATABASE_URL=postgresql://postgres:$ADMIN_PW@db:5432/cairn
CAIRN_SECRET_KEY=$(rand 48)
CAIRN_MASTER_KEY=$(python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())")
ANTHROPIC_API_KEY=
ENV
echo "Wrote $ENV_FILE with random credentials."
