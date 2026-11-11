"""Save the API answers behind the Features page screenshots into one file.

    python scripts/capture_demo_data.py            # reads the API on this server (127.0.0.1:8000)
    → data/exports/demo-data.json.gz              # attach this file in the chat

Only public, read-only API answers are saved (the same data anyone can see on the site); nothing
about visitors. The screenshots are then taken elsewhere from exactly this data.
"""

import gzip
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parents[1] / "data" / "exports" / "demo-data.json.gz"

STATES = ["TX"]
MEMBERS = ["C001098", "C001056", "V000134", "C001091"]   # Cruz, Cornyn, Van Duyne, Castro (all Texas)
COMPARE = [("C001098", "C001056"), ("V000134", "C001091")]
QUESTIONS = [("CES 2022", "CC22_350b"), ("CES 2022", "CC22_350a"), ("CES 2024", "CC24_340c")]

saved: dict[str, object] = {}


def get(path: str, **params):
    query = urlencode([(k, v) for k, vs in params.items() for v in (vs if isinstance(vs, list) else [vs])])
    key = path + (f"?{query}" if query else "")
    if key in saved:
        return saved[key]
    try:
        with urlopen(BASE + key, timeout=120) as r:
            saved[key] = json.load(r)
    except Exception as e:                      # noqa: BLE001 - record and carry on
        print(f"  skipped {key}: {e}")
        saved[key] = None
    return saved[key]


def main() -> int:
    print(f"Reading {BASE} ...")
    for p in ("/v1/health", "/v1/surveys", "/v1/votes/filters", "/v1/surveyed"):
        get(p)
    for s in STATES:
        get(f"/v1/states/{s}")
        get("/v1/members", state=s, include="former")
    for m in MEMBERS:
        get(f"/v1/members/{m}")
        get(f"/v1/members/{m}/opinion")
        get(f"/v1/members/{m}/votes", limit=100)
    for a, b in COMPARE:
        r = get("/v1/compare", a=a, b=b, limit=25)
        for v in (r or {}).get("splits", [])[:3]:
            get(f"/v1/votes/{v['roll_call_id']}")
    for survey, item in QUESTIONS:
        get("/v1/surveyed/detail", survey=survey, item=item)
    for params in ({"limit": 25}, {"limit": 25, "surveyed": "true"}):
        r = get("/v1/votes", **params, member=MEMBERS[:2])
        for v in (r or {}).get("votes", [])[:3]:
            get(f"/v1/votes/{v['roll_call_id']}")
    get("/v1/search", q="background check*", limit=40, member=MEMBERS[:2])
    get("/v1/numbers", congress=119, chamber="house")                 # Members by the numbers
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt") as f:
        json.dump(saved, f, default=str)
    ok = sum(v is not None for v in saved.values())
    print(f"Saved {ok} of {len(saved)} answers to {OUT} ({OUT.stat().st_size // 1024} KB)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
