#!/usr/bin/env bash
# =====================================================================
#  Back up everything to ./backups/ :
#    * loa-<timestamp>.sql        full PostgreSQL dump (authoritative)
#    * library-<timestamp>.csv    + wishlist-<timestamp>.csv  (UTF-8)
#
#  Usage:   ./backup.sh
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"
DB_USER="${POSTGRES_USER:-loa}"; DB_NAME="${POSTGRES_DB:-loa}"
mkdir -p backups
TS="$(date +%Y%m%d-%H%M%S)"

echo "==> Dumping PostgreSQL -> backups/loa-$TS.sql"
docker compose exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists > "backups/loa-$TS.sql"

echo "==> Exporting CSV copies (UTF-8 with BOM)"
docker compose exec -T app python manage.py export-csv --stdout library  > "backups/library-$TS.csv"
docker compose exec -T app python manage.py export-csv --stdout wishlist > "backups/wishlist-$TS.csv"

echo
echo "Backup complete:"
ls -lh "backups/loa-$TS.sql" "backups/library-$TS.csv" "backups/wishlist-$TS.csv"
