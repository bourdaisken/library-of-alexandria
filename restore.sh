#!/usr/bin/env bash
# =====================================================================
#  Restore a PostgreSQL backup created by ./backup.sh
#  WARNING: this replaces the current catalog with the backup's contents.
#
#  Usage:   ./restore.sh backups/loa-YYYYmmdd-HHMMSS.sql
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"
DB_USER="${POSTGRES_USER:-loa}"; DB_NAME="${POSTGRES_DB:-loa}"

FILE="${1:-}"
if [ -z "$FILE" ]; then
  echo "Usage: ./restore.sh backups/loa-YYYYmmdd-HHMMSS.sql"
  echo "Available backups:"; ls -1 backups/*.sql 2>/dev/null || echo "  (none found)"
  exit 1
fi
[ -f "$FILE" ] || { echo "No such file: $FILE"; exit 1; }

echo "==> Stopping the app (so the database has no open connections) ..."
docker compose stop app >/dev/null 2>&1 || true

echo "==> Starting the database ..."
docker compose up -d db
for _ in $(seq 1 30); do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  sleep 1
done

echo "==> Restoring $FILE  (this replaces current data)"
docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" < "$FILE"
echo "Done. Start the app with:  docker compose up -d app"
