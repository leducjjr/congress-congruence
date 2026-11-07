#!/bin/sh
# Copy the panel files (web/) to where nginx serves them.
# Run after `git pull` whenever the panel changes:  scripts/publish_web.sh
set -eu
cd "$(dirname "$0")/.."
sudo mkdir -p /var/www/congress-dev
sudo cp web/*.html web/*.js /var/www/congress-dev/
sudo chmod 644 /var/www/congress-dev/*
echo "Published web/ to /var/www/congress-dev"
