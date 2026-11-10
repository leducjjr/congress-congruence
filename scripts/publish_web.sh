#!/bin/sh
# Build the website (site/ pages in the shared header and footer, plus the panel) and copy it
# to where nginx serves it. Run after `git pull` whenever pages or the panel change:
#     scripts/publish_web.sh          # the password-protected dev site (/var/www/congress-dev)
#     scripts/publish_web.sh prod     # the public site, uscongressvsvoters.org (/var/www/congress)
#     scripts/publish_web.sh both
#     scripts/publish_web.sh pages    # only refresh the member and state pages and the sitemap on
#                                     # both sites (the weekly cron job; needs no sudo)
#
# The member and state pages (members/, states/, sitemap.xml) are built from the API running on
# this server (scripts/build_profiles.py). If the API isn't answering, the rest of the site is
# still published and the pages already there are kept.
#
# Pages load their scripts and styles as e.g. cc-member-panel.js?v=<code version>, so
# browsers fetch the new copy after each update instead of reusing a cached one.
set -eu
cd "$(dirname "$0")/.."
case "${1:-dev}" in
  dev)   targets="/var/www/congress-dev" ;;
  prod)  targets="/var/www/congress" ;;
  both|pages) targets="/var/www/congress-dev /var/www/congress" ;;
  *) echo "usage: $0 [dev|prod|both|pages]" >&2; exit 2 ;;
esac
version=$(git rev-parse --short HEAD 2>/dev/null || date +%s)
py=python3; [ -x .venv/bin/python ] && py=.venv/bin/python     # the project Python has markdown + yaml
me=$(id -un)

build_pages() {   # build_pages <dir>: member and state pages into <dir>; fails if the API is down
  "$py" scripts/build_profiles.py --out "$1" --version "$version"
}

if [ "${1:-}" = "pages" ]; then
  rm -rf build/pages
  "$py" scripts/build_site.py --out build/pages --version "$version" >/dev/null   # so the sitemap lists every page
  build_pages build/pages
  for dir in $targets; do
    [ -w "$dir/members" ] || { echo "$dir/members isn't writable: run scripts/publish_web.sh both once" >&2; exit 1; }
    cp -r build/pages/members build/pages/states "$dir/"
    cp build/pages/sitemap.xml "$dir/sitemap.xml"
    echo "Refreshed the member and state pages in $dir"
  done
  exit 0
fi

# sudo is needed only if a web folder isn't this user's. After a one-time
#     sudo chown -R "$USER": /var/www/congress /var/www/congress-dev
# publishing never asks for a password. Otherwise it asks once, up front, and keeps sudo from
# timing out while the member pages build (that takes several minutes).
SUDO=""
for dir in $targets; do
  [ -d "$dir" ] && [ -w "$dir" ] && [ -z "$(find "$dir" ! -user "$me" -print -quit)" ] || SUDO=sudo
done
if [ -n "$SUDO" ]; then
  sudo -v
  ( while sleep 50; do sudo -n -v 2>/dev/null || exit; done ) &
  keepalive=$!
  trap 'kill $keepalive 2>/dev/null' EXIT INT TERM
fi

rm -rf build/site
"$py" scripts/build_site.py --out build/site --version "$version"
pages=yes
build_pages build/site || { pages=no; echo "WARNING: couldn't build the member and state pages (is the API running?). Publishing the rest; the pages already there are kept." >&2; }
for dir in $targets; do
  $SUDO mkdir -p "$dir"
  $SUDO cp -r build/site/. "$dir/"          # includes .well-known/
  $SUDO find "$dir" -type d -exec chmod 755 {} +
  $SUDO find "$dir" -type f -exec chmod 644 {} +
  if [ -n "$SUDO" ] && [ "$pages" = yes ]; then
    # Owned by this user, so the weekly `pages` job can refresh them without sudo.
    sudo chown -R "$me" "$dir/members" "$dir/states" "$dir/sitemap.xml"
  fi
  echo "Published the site to $dir (version $version)"
done
