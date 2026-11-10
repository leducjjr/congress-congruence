#!/bin/sh
# Runs one scheduled job and appends its output to logs/<job>.log.
# Used by cron (see scripts/crontab.txt). Safe to run by hand too:
#     scripts/run_job.sh house
#
# Jobs:
#   members          refresh the member list (new members must exist before their votes load)
#   house            load any new House votes for the current session (official Clerk files)
#   senate-voteview  reload the current Congress's Senate votes from Voteview
#   backup           nightly database backup (scripts/backup_db.sh)
#   survey-watch     monthly check for new survey releases; drafts them for review, never loads
#   bills            daily: titles, policy areas and subject tags from Congress.gov for voted-on bills
#   reminders        daily: emails any reminders due (config/reminders.yaml) to REMINDERS_TO
#
# Each job holds a lock, so a slow run is never started twice at once.
#
# Alerts: if .env has HEALTHCHECK_<JOB>=<ping URL> (job name in capitals, '-' as '_',
# e.g. HEALTHCHECK_SENATE_VOTEVIEW), the job reports start, success or failure to it.
# Made for healthchecks.io, which emails you when a job fails or doesn't report on time.

set -eu
cd "$(dirname "$0")/.."
. .venv/bin/activate
mkdir -p logs

job="${1:-}"
log="logs/$job.log"
lock="/tmp/congress-congruence-$job.lock"
key="HEALTHCHECK_$(echo "$job" | tr 'a-z-' 'A-Z_')"
ping_url=$(grep -E "^${key}=" .env 2>/dev/null | cut -d= -f2- || true)

ping() {   # ping <suffix>: "start", or an exit code (0 = success)
    [ -n "$ping_url" ] || return 0
    curl -fsS -m 10 --retry 3 -o /dev/null "$ping_url/$1" || echo "(alert ping failed: $ping_url/$1)"
}

run() {
    echo "== $(date -u '+%Y-%m-%d %H:%M:%S UTC') start $job"
    ping start
    status=0
    "$@" || status=$?
    ping "$status"
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
    backup)
        exec >>"$log" 2>&1
        run flock -n "$lock" scripts/backup_db.sh
        ;;
    survey-watch)
        exec >>"$log" 2>&1
        run flock -n "$lock" python -m congress_congruence.ingest.watch
        ;;
    bills)
        exec >>"$log" 2>&1
        run flock -n "$lock" python -m congress_congruence.ingest.bills sync
        ;;
    reminders)
        exec >>"$log" 2>&1
        run flock -n "$lock" python -m congress_congruence.reminders
        ;;
    *)
        echo "usage: $0 members|house|senate-voteview|backup|survey-watch|bills|reminders" >&2
        exit 2
        ;;
esac
