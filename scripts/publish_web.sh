#!/bin/sh
# Build the website (site/ pages in the shared header and footer, plus the panel) and copy it
# to where nginx serves it. Run after `git pull` whenever pages or the panel change:
#     scripts/publish_web.sh          # the password-protected dev site (/var/www/congress-dev)
#     scripts/publish_web.sh prod     # the public site, uscongressvsvoters.org (/var/www/congress)
#     scripts/publish_web.sh both
#
# Pages load their scripts and styles as e.g. cc-member-panel.js?v=<code version>, so
# browsers fetch the new copy after each update instead of reusing a cached one.
set -eu
cd "$(dirname "$0")/.."
case "${1:-dev}" in
  dev)  targets="/var/www/congress-dev" ;;
  prod) targets="/var/www/congress" ;;
  both) targets="/var/www/congress-dev /var/www/congress" ;;
  *) echo "usage: $0 [dev|prod|both]" >&2; exit 2 ;;
esac
version=$(git rev-parse --short HEAD 2>/dev/null || date +%s)
rm -rf build/site
py=python3; [ -x .venv/bin/python ] && py=.venv/bin/python     # the project Python has markdown + yaml
"$py" scripts/build_site.py --out build/site --version "$version"
for dir in $targets; do
  sudo mkdir -p "$dir"
  sudo cp -r build/site/. "$dir/"          # includes .well-known/
  sudo find "$dir" -type d -exec chmod 755 {} +
  sudo find "$dir" -type f -exec chmod 644 {} +
  echo "Published the site to $dir (version $version)"
done
