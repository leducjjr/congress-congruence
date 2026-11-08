#!/bin/sh
# Copy the panel files (web/) to where nginx serves them.
# Run after `git pull` whenever the panel changes:  scripts/publish_web.sh
#
# The published pages load cc-member-panel.js?v=<code version>, so browsers fetch the new
# panel after each update instead of reusing a cached copy.
set -eu
cd "$(dirname "$0")/.."
version=$(git rev-parse --short HEAD 2>/dev/null || date +%s)
sudo mkdir -p /var/www/congress-dev
sudo cp web/*.js /var/www/congress-dev/
for page in web/*.html; do
    sed "s/cc-member-panel\.js\"/cc-member-panel.js?v=$version\"/" "$page" \
        | sudo tee "/var/www/congress-dev/$(basename "$page")" >/dev/null
done
sudo chmod 644 /var/www/congress-dev/*
echo "Published web/ to /var/www/congress-dev (version $version)"
