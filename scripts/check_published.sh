#!/bin/sh
# Fails (exit 1) when a change saved to GitHub more than a day ago hasn't reached the live site yet.
# Run daily by the scheduler (scripts/run_job.sh published), which reports to healthchecks.io.
#
# How: the live pages carry the code version they were built from (site.js?v=<version>). Every commit
# on GitHub's main branch after that version, touching anything the site is built or served from, and
# older than a day, counts as unpublished. Notes-only changes (docs, PROJECT_NOTES.md) don't count.
# Fix: on the server, `git pull && scripts/publish_web.sh both` (plus any migrate/restart/load the
# change's commit message asks for).
set -eu
cd "$(dirname "$0")/.."
site="${SITE_URL:-https://uscongressvsvoters.org}"
max_age_hours="${PUBLISH_GRACE_HOURS:-24}"

live=$(curl -fsS --max-time 20 "$site/" | grep -o 'site\.js?v=[0-9a-f]*' | head -n 1 | cut -d= -f2)
[ -n "$live" ] || { echo "couldn't read the live site's version from $site/"; exit 1; }
git fetch -q origin main
git cat-file -e "$live^{commit}" 2>/dev/null || { echo "the live version $live isn't in the repository"; exit 1; }

cutoff=$(( $(date +%s) - max_age_hours * 3600 ))
late=$(git log --format='%ct %h %s' "$live..origin/main" -- site web src sql config scripts \
       | awk -v c="$cutoff" '$1 < c {print}')
if [ -n "$late" ]; then
    echo "Saved to GitHub over ${max_age_hours} hours ago but not on the live site (live version $live):"
    echo "$late" | cut -d' ' -f2-
    exit 1
fi
echo "Live site is current (version $live; $(git rev-list --count "$live..origin/main") newer commits, none overdue)."
