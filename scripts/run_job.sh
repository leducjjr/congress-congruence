#!/bin/sh
# Runs one scheduled job and appends its output to logs/<job>.log.
# Used by cron (see scripts/crontab.txt). Safe to run by hand too:
#     scripts/run_job.sh house
#
# Jobs:
#   members          refresh the member list (new members must exist before their votes load)
#   house            load any new House votes for the current session (official Clerk files)
#   senate-voteview  reload the current Congress's Senate votes from Voteview
#
# Each job holds a lock, so a slow run is never started twice at once.

set -eu
cd "$(dirname "$0")/.."
. .venv/bin/activate
mkdir -p logs

job="${1:-}"
log="logs/$job.log"
lock="/tmp/congress-congruence-$job.lock"

run() {
    echo "== $(date -u '+%Y-%m-%d %H:%M:%S UTC') start $job"
    status=0
    "$@" || status=$?
    echo "== $(date -u '+%Y-%m-%d %H:%M:%S UTC') end $job (exit $status)"
    return $status
}

case "$job" in
    members)
        exec >>"$log" 2>&1
        run flock -n "$lock" sh -c 'git -C data/raw/congress-legislators pull -q && python -m congress_congruence.ingest.members data/raw/congress-legislators'
        ;;
    house)
        exec >>"$log" 2>&1
        run flock -n "$lock" python -m congress_congruence.ingest.votes sync house current
        ;;
    senate-voteview)
        exec >>"$log" 2>&1
        run flock -n "$lock" python -m congress_congruence.ingest.voteview senate current
        ;;
    *)
        echo "usage: $0 members|house|senate-voteview" >&2
        exit 2
        ;;
esac
