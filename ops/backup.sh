#!/bin/sh
# Database backups (pg_dump custom format) into ./backups (gitignored).
#
#   sh ops/backup.sh             take a backup: backups/jobmatch-<UTC time>.dump
#   sh ops/backup.sh check [F]   restore F (default: the newest backup) into a scratch
#                                database, compare every table's row count with the live
#                                database, then drop the scratch database
#   sh ops/backup.sh restore F   replace the live database with F (asks first)
#
# The dump streams through `docker compose exec`, so nothing is written inside the
# container. Volumes are never touched.
set -eu
cd "$(dirname "$0")/.."
mkdir -p backups

psql_db() {  # psql_db <database> <sql>
  docker compose exec -T db sh -c "psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d '$1' -Atc \"$2\""
}

counts() {  # counts <database>: "table rows" lines, exact counts
  tables=$(psql_db "$1" "select tablename from pg_tables where schemaname='public' order by 1")
  for t in $tables; do
    echo "$t $(psql_db "$1" "select count(*) from public.\\\"$t\\\"")"
  done
  # Row counts alone would not notice a lost vector column.
  echo "jobs.embedding $(psql_db "$1" "select count(embedding) from jobs")"
}

live_db() {
  docker compose exec -T db sh -c 'printf %s "$POSTGRES_DB"'
}

case "${1:-backup}" in
backup)
  file="backups/jobmatch-$(date -u +%Y%m%dT%H%M%SZ).dump"
  docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' >"$file.partial"
  mv "$file.partial" "$file"
  # A dump that pg_restore cannot list is not a backup.
  entries=$(docker compose exec -T db pg_restore --list <"$file" | grep -vc '^;')
  echo "$file  $(wc -c <"$file" | tr -d ' ') bytes, $entries entries"
  ;;
check)
  file="${2:-$(ls -1 backups/jobmatch-*.dump 2>/dev/null | sort | tail -1)}"
  [ -n "$file" ] && [ -f "$file" ] || { echo "no backup found" >&2; exit 1; }
  scratch=jobmatch_restore_check
  live=$(live_db)
  docker compose exec -T db sh -c "dropdb -U \"\$POSTGRES_USER\" --if-exists $scratch && createdb -U \"\$POSTGRES_USER\" $scratch"
  docker compose exec -T db sh -c "pg_restore -U \"\$POSTGRES_USER\" -d $scratch --no-owner --exit-on-error" <"$file"
  counts "$live" >backups/.live-counts
  counts "$scratch" >backups/.restored-counts
  docker compose exec -T db sh -c "dropdb -U \"\$POSTGRES_USER\" $scratch"
  if diff -u backups/.live-counts backups/.restored-counts; then
    echo "restore check passed: $file"
    cat backups/.restored-counts
  else
    echo "restore check FAILED: row counts differ (live changed since the backup, or the dump is incomplete)" >&2
    exit 1
  fi
  rm -f backups/.live-counts backups/.restored-counts
  ;;
restore)
  file="${2:?usage: sh ops/backup.sh restore backups/<file>.dump}"
  printf 'Replace the live database with %s? Type yes: ' "$file"
  read -r answer
  [ "$answer" = yes ] || { echo "cancelled"; exit 1; }
  docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --exit-on-error' <"$file"
  echo "restored $file"
  ;;
*)
  echo "usage: sh ops/backup.sh [backup | check [file] | restore file]" >&2
  exit 2
  ;;
esac
