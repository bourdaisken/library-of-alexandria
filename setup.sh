#!/usr/bin/env bash
# =====================================================================
#  Library of Alexandria — one-command setup. Safe to re-run.
#
#  Requirements: Docker + Docker Compose. Then just:
#      ./setup.sh
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"

DB_USER="${POSTGRES_USER:-loa}"
DB_NAME="${POSTGRES_DB:-loa}"

echo "==> [1/5] Preparing .env ..."
[ -f .env ] || cp .env.example .env
# Generate a stable session SECRET_KEY if one isn't set yet (so logins survive restarts).
if ! grep -q '^SECRET_KEY=.\+' .env; then
  SECRET="$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets;print(secrets.token_hex(32))')"
  if grep -q '^SECRET_KEY=' .env; then
    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET|" .env
  else
    echo "SECRET_KEY=$SECRET" >> .env
  fi
  echo "    Generated SECRET_KEY."
fi
mkdir -p ebooks data backups

echo "==> [2/5] Starting the database ..."
docker compose up -d db
for _ in $(seq 1 30); do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  sleep 1
done
docker compose run --rm -T app python manage.py initdb

echo "==> [3/5] Seeding a few sample books (only if the catalog is empty) ..."
docker compose run --rm -T app python manage.py seed-sample

echo "==> [4/5] Ensuring an admin account exists ..."
docker compose run --rm -T app python manage.py ensure-admin

echo "==> [5/5] Building & starting the app ..."
docker compose up -d --build app

PORT="$(grep -E '^LOA_PORT=' .env | cut -d= -f2)"; PORT="${PORT:-5001}"
echo
echo "============================================================"
echo "  Library of Alexandria is running."
echo "  Open:  http://localhost:${PORT}"
echo
echo "  Log in with the admin username + the password printed above"
echo "  (step 4). Change it from the in-app Account tab."
echo
echo "  Back up your data anytime:   ./backup.sh"
echo "============================================================"
