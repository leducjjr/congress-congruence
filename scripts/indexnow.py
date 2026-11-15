"""Tell search engines which pages changed, with IndexNow (https://www.indexnow.org), used by Bing,
Yandex and others. Google doesn't use it; it reads the sitemap's dates instead.

    python scripts/indexnow.py keyfile build/site   # put the key file in the built site
    python scripts/indexnow.py send                 # report the pages that changed

The key is INDEXNOW_KEY in .env (make one with: openssl rand -hex 16). It isn't a secret: IndexNow
checks that https://<site>/<key>.txt contains it, which proves the reports come from the site's
owner. Without a key, both commands do nothing.

build_profiles.py adds each page whose content changed to data/exports/indexnow_pending.json at every
build; `send` reports them after the public site is published (scripts/publish_web.sh) and empties
the list once they're accepted. Nothing is sent for the dev site, and a failure never stops a publish.
"""

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

PENDING = ROOT / "data" / "exports" / "indexnow_pending.json"
ENDPOINT = "https://api.indexnow.org/indexnow"
BATCH = 10_000                       # IndexNow's limit per request


def key() -> str | None:
    from congress_congruence import config  # noqa: F401 - loads .env
    k = os.environ.get("INDEXNOW_KEY", "").strip()
    return k if re.fullmatch(r"[A-Za-z0-9-]{8,128}", k) else None


def site_url() -> str:
    import build_site
    return str(build_site.load_settings().get("site_url", "")).rstrip("/")


def read_pending(path: Path = PENDING) -> list[str]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def add_pending(paths, path: Path = PENDING) -> None:
    merged = sorted(set(read_pending(path)) | set(paths))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged), encoding="utf-8")


def write_keyfile(folder: Path) -> bool:
    k = key()
    if not k:
        return False
    (folder / f"{k}.txt").write_text(k, encoding="utf-8")
    return True


def send(post=None, path: Path = PENDING, log=print) -> int:
    """Report the pending pages. Returns how many were accepted."""
    k = key()
    pages = read_pending(path)
    if not k:
        log("IndexNow: no INDEXNOW_KEY in .env, so nothing sent")
        return 0
    if not pages:
        log("IndexNow: no changed pages to report")
        return 0
    base = site_url()
    if post is None:
        import requests
        post = lambda body: requests.post(ENDPOINT, json=body, timeout=30,
                                          headers={"Content-Type": "application/json; charset=utf-8"}).status_code
    sent = 0
    for i in range(0, len(pages), BATCH):
        chunk = pages[i:i + BATCH]
        body = {"host": urlsplit(base).hostname, "key": k, "keyLocation": f"{base}/{k}.txt",
                "urlList": [f"{base}/{p}" for p in chunk]}
        try:
            status = post(body)
        except Exception as e:                      # noqa: BLE001 - never stop a publish over this
            log(f"IndexNow: couldn't reach {ENDPOINT} ({e}); will try again next publish")
            break
        if status in (200, 202):
            sent += len(chunk)
        else:
            meaning = {400: "bad request", 403: "key not found on the site yet", 422: "addresses don't match the site",
                       429: "too many requests"}.get(status, "unexpected answer")
            log(f"IndexNow: answered {status} ({meaning}); will try again next publish")
            break
    if sent:
        rest = pages[sent:]
        path.write_text(json.dumps(rest), encoding="utf-8")
        log(f"IndexNow: reported {sent} changed page{'s' if sent != 1 else ''}")
    return sent


def main(argv: list[str]) -> int:
    if argv[1:2] == ["keyfile"] and len(argv) == 3:
        if write_keyfile(Path(argv[2])):
            print("IndexNow key file added")
        return 0
    if argv[1:] == ["send"]:
        send()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
