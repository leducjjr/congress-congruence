"""Bill titles, policy areas and subject tags from the Congress.gov API, for bills with recorded votes.

    python -m congress_congruence.ingest.bills sync            # bills new or not checked recently
    python -m congress_congruence.ingest.bills sync --all      # re-check every bill with a vote
    python -m congress_congruence.ingest.bills show 119 hr 1   # what's stored for one bill

Why: vote titles are official names ("Laken Riley Act") that often don't contain the words people
search for ("immigration"). The Library of Congress tags every bill with a policy area and
legislative subjects; search uses them too.

Needs a free key from https://api.data.gov/signup in .env as CONGRESS_API_KEY=<key>.
api.data.gov allows 5,000 requests an hour; each bill takes two (bill, then its subjects), and
the loader pauses between requests. Raw responses are kept under RAW_DATA_DIR/congress_gov/.

A bill is checked when it has a vote but hasn't been checked yet, when it got a new vote since its
last check, or when its last check is more than 30 days old (subjects are added over time).
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import requests

from .. import config
from .votes import http_session, record_run

log = logging.getLogger(__name__)

API = "https://api.congress.gov/v3"
BILL_TYPES = {"hr", "s", "hjres", "sjres", "hconres", "sconres", "hres", "sres"}
PAUSE_SECONDS = 0.4
RECHECK_DAYS = 30

BILLS_TO_CHECK = """
with voted as (
    select coalesce(bill_congress, congress) as congress, bill_type, bill_number, max(vote_date) as last_vote
      from core.roll_call
     where bill_type = any(%(types)s) and bill_number is not null
     group by 1, 2, 3
)
select v.congress, v.bill_type, v.bill_number
  from voted v
  left join core.bill b using (congress, bill_type, bill_number)
 where %(all)s or b.checked_at is null
    or b.checked_at < v.last_vote
    or b.checked_at < now() - make_interval(days => %(days)s)
 order by v.last_vote desc
"""


class KeyProblem(RuntimeError):
    """The API key is missing or was refused; nothing will work until it's fixed."""


def api_key() -> str:
    key = os.environ.get("CONGRESS_API_KEY", "").strip()
    if not key:
        raise KeyProblem("CONGRESS_API_KEY is not set in .env. Get a free key at https://api.data.gov/signup "
                         "and add the line CONGRESS_API_KEY=<key> to .env.")
    return key


def get_json(http, url: str, key: str, params: dict | None = None) -> dict:
    """GET a Congress.gov API URL as JSON. Retries after a rate-limit or server error, or a dropped
    connection (a reply cut off mid-way). Error messages never include the key."""
    params = {"format": "json", **(params or {})}
    for attempt in range(3):
        try:
            resp = http.get(url, params={**params, "api_key": key}, timeout=60)
        except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError,
                requests.exceptions.Timeout) as e:
            wait = 10 * (attempt + 1)
            log.warning("Connection to Congress.gov dropped (%s); retrying in %ss", type(e).__name__, wait)
            time.sleep(wait)
            continue
        if resp.status_code in (401, 403):
            raise KeyProblem(f"Congress.gov refused the API key (HTTP {resp.status_code}). Check CONGRESS_API_KEY in "
                             ".env, or request a new key at https://api.data.gov/signup.")
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = 60 if resp.status_code == 429 else 5 * (attempt + 1)
            log.warning("Congress.gov answered %s for %s; waiting %ss", resp.status_code, url, wait)
            time.sleep(wait)
            continue
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Congress.gov kept failing for {url}")


def fetch_bill(http, key: str, congress: int, bill_type: str, number: int) -> dict:
    """{'bill': {...}, 'subjects': [names...], 'policy_area': str|None} for one bill ({} if not found)."""
    base = f"{API}/bill/{congress}/{bill_type}/{number}"
    bill = get_json(http, base, key).get("bill")
    if not bill:
        return {}
    time.sleep(PAUSE_SECONDS)
    subjects, url, params = [], f"{base}/subjects", {"limit": 250}
    while url:
        page = get_json(http, url, key, params)
        block = page.get("subjects") or {}
        subjects += [s["name"] for s in block.get("legislativeSubjects") or [] if s.get("name")]
        url = (page.get("pagination") or {}).get("next")
        params = {}                                      # the "next" URL already carries offset and limit
        if url:
            time.sleep(PAUSE_SECONDS)
    policy = (bill.get("policyArea") or {}).get("name")
    return {"bill": bill, "subjects": sorted(set(subjects)), "policy_area": policy}


def save_raw(congress: int, bill_type: str, number: int, data: dict) -> None:
    folder = config.raw_data_dir() / "congress_gov" / "bills" / str(congress)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{bill_type}{number}.json").write_text(json.dumps(data, indent=1, sort_keys=True))


def store(conn, congress: int, bill_type: str, number: int, data: dict) -> None:
    """Write one bill's title, policy area, latest action and subjects (replacing what was there)."""
    bill = data.get("bill") or {}
    latest = bill.get("latestAction") or {}
    latest_text = " ".join(x for x in (latest.get("actionDate"), latest.get("text")) if x) or None
    with conn.cursor() as cur:
        cur.execute(
            """insert into core.bill (congress, bill_type, bill_number, title, introduced, policy_area,
                                      latest_action, updated_at, checked_at)
               values (%s, %s, %s, %s, %s, %s, %s, %s, now())
               on conflict (congress, bill_type, bill_number) do update set
                   title = coalesce(excluded.title, core.bill.title),
                   introduced = coalesce(excluded.introduced, core.bill.introduced),
                   policy_area = coalesce(excluded.policy_area, core.bill.policy_area),
                   latest_action = coalesce(excluded.latest_action, core.bill.latest_action),
                   updated_at = coalesce(excluded.updated_at, core.bill.updated_at),
                   checked_at = now()""",
            (congress, bill_type, number, bill.get("title"), bill.get("introducedDate"), data.get("policy_area"),
             latest_text, bill.get("updateDateIncludingText") or bill.get("updateDate")))
        if data:
            cur.execute("delete from core.bill_subject where congress = %s and bill_type = %s and bill_number = %s",
                        (congress, bill_type, number))
            cur.executemany("insert into core.bill_subject (congress, bill_type, bill_number, subject) "
                            "values (%s, %s, %s, %s)",
                            [(congress, bill_type, number, s) for s in data.get("subjects", [])])
    conn.commit()


def sync(conn, http=None, check_all: bool = False, limit: int | None = None) -> dict:
    key = api_key()
    http = http or http_session()
    with conn.cursor() as cur:
        cur.execute(BILLS_TO_CHECK, {"types": sorted(BILL_TYPES), "all": check_all, "days": RECHECK_DAYS})
        todo = cur.fetchall()
    conn.commit()
    if limit:
        todo = todo[:limit]
    done = missing = failed = 0
    for congress, bill_type, number in todo:
        try:
            data = fetch_bill(http, key, congress, bill_type, number)
        except KeyProblem:
            raise
        except Exception as e:          # one bill's trouble shouldn't stop the run; it's retried next time
            failed += 1
            log.error("%s %s %s: %s", congress, bill_type, number, e)
            if failed >= 20:
                raise RuntimeError("20 bills failed in this run; stopping (is Congress.gov down?)") from e
            continue
        if data:
            save_raw(congress, bill_type, number, data)
        else:
            missing += 1
            log.warning("Congress.gov has no record of %s %s %s", congress, bill_type, number)
        store(conn, congress, bill_type, number, data)
        done += 1
        if done % 25 == 0:
            log.info("%s of %s bills checked", done, len(todo))
        time.sleep(PAUSE_SECONDS)
    return {"loaded": done, "bills_checked": done, "not_found": missing, "failed": failed,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from .. import db
    args = argv[1:]
    if args[:1] == ["sync"]:
        with db.connect() as conn:
            try:
                print(record_run(conn, "bills", lambda: sync(conn, check_all="--all" in args)))
            except KeyProblem as e:
                print(e, file=sys.stderr)
                return 1
        return 0
    if len(args) == 4 and args[0] == "show" and args[1].isdigit() and args[3].isdigit():
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("select title, policy_area, latest_action, checked_at from core.bill "
                        "where congress = %s and bill_type = %s and bill_number = %s",
                        (int(args[1]), args[2].lower(), int(args[3])))
            print(cur.fetchone())
            cur.execute("select subject from core.bill_subject where congress = %s and bill_type = %s "
                        "and bill_number = %s order by subject", (int(args[1]), args[2].lower(), int(args[3])))
            print([r[0] for r in cur.fetchall()])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
