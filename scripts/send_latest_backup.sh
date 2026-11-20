#!/bin/sh
# Sends the newest database backup to standard output, and nothing else.
#
# Used as the forced command for the PC's download key in ~/.ssh/authorized_keys, so that key can
# only ever fetch the latest backup: no shell, no other files, no port forwarding.
#     command="/home/john/congress-congruence/scripts/send_latest_backup.sh",restrict ssh-ed25519 AAAA... backup-download
# The PC side is deploy/windows/download_backup.bat (see deploy/README.md, "Backups").
set -eu
dir="${BACKUP_DIR:-$HOME/backups}"
latest=$(ls -1t "$dir"/congress-*.dump 2>/dev/null | head -n 1)
if [ -z "$latest" ]; then
    echo "no backup found in $dir" >&2
    exit 1
fi
exec cat -- "$latest"
