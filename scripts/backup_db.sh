#!/bin/sh
# Back up the database to ~/backups/congress-YYYY-MM-DD.dump and keep the last 14 days.
# Run by the scheduler (scripts/run_job.sh backup) or by hand.
#
# Restore test (into a scratch database, never over the real one):
#     sudo -u postgres createdb -O john congress_restore_test
#     pg_restore --no-owner -d congress_restore_test ~/backups/congress-YYYY-MM-DD.dump
#     psql congress_restore_test -c "select count(*) from core.roll_call;"
#     sudo -u postgres dropdb congress_restore_test
#
# These copies live on the same server, so they protect against mistakes and bad
# loads, not against losing the server. Copy one off the server now and then
# (see deploy/README.md).
set -eu
cd "$(dirname "$0")/.."

url=$(grep -E '^DATABASE_URL=' .env | cut -d= -f2-)
dir="${BACKUP_DIR:-$HOME/backups}"
keep_days="${BACKUP_KEEP_DAYS:-14}"
mkdir -p "$dir"
chmod 700 "$dir"

file="$dir/congress-$(date -u +%F).dump"
pg_dump --format=custom --no-owner --file="$file.part" "$url"
pg_restore --list "$file.part" >/dev/null          # fails if the file isn't a readable backup
mv "$file.part" "$file"
chmod 600 "$file"

find "$dir" -name 'congress-*.dump' -mtime +"$keep_days" -delete
echo "Backup written: $file ($(du -h "$file" | cut -f1)); $(ls "$dir"/congress-*.dump | wc -l) kept"
