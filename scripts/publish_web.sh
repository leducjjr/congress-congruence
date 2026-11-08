#!/bin/sh
# Build the website (site/ pages in the shared header and footer, plus the panel) and copy it
# to where nginx serves it. Run after `git pull` whenever pages or the panel change:
#     scripts/publish_web.sh
#
# Pages load their scripts and styles as e.g. cc-member-panel.js?v=<code version>, so
# browsers fetch the new copy after each update instead of reusing a cached one.
set -eu
cd "$(dirname "$0")/.."
version=$(git rev-parse --short HEAD 2>/dev/null || date +%s)
rm -rf build/site
py=python3; [ -x .venv/bin/python ] && py=.venv/bin/python     # the project Python has markdown + yaml
"$py" scripts/build_site.py --out build/site --version "$version"
sudo mkdir -p /var/www/congress-dev
sudo cp build/site/* /var/www/congress-dev/
sudo chmod 644 /var/www/congress-dev/*
echo "Published the site to /var/www/congress-dev (version $version)"
