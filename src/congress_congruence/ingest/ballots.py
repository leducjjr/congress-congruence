"""State ballot measures: certified statewide results, compared with members who represent the whole state.

    python -m congress_congruence.ingest.ballots link 2024    # which roll call each measure is compared with
    python -m congress_congruence.ingest.ballots load 2024    # link + store each state's result

config/ballot_<year>_items.yaml lists, per item, the vote(s) it relates to and each state's measure
with its certified Yes and No counts (yes_votes, no_votes: plain yes/no would read as true/false
in YAML) and a link to the result.

A measure whose result isn't certified yet is listed with `pending: true` and no counts: load skips
it (and any item with nothing certified yet), so a year can be loaded state by state as each one
certifies. Re-running load replaces the year's earlier rows. `link` checks every item's votes,
pending or not.

How results are stored (method certified-results-v1), next to survey estimates but never blended:
  support    = Yes / (Yes + No)        votes actually cast, so no margin of error: low = high = support
  majority   = support if Yes > No, oppose if No > Yes, too_close only on an exact tie
  respondents = Yes + No (votes cast on the measure)
  area_note  = the state's own measure name, e.g. "Idaho HJR 5"
Rows are statewide (district null). A state with a single House seat also gets the same row for its
at-large district (district 0), so its representative is compared too; representatives of states
with several districts are not, because a statewide result isn't their district's view.
"""

import logging
import sys

import yaml

from .. import config
from . import ces

log = logging.getLogger(__name__)

METHOD = "certified-results-v1"
KIND = "ballot"


def load_config(year: int) -> dict:
    path = config.PROJECT_ROOT / "config" / f"ballot_{year}_items.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No ballot-measure list for {year}: create {path}")
    cfg = yaml.safe_load(path.read_text())
    for var, item in cfg["items"].items():
        for r in item.get("results", []):
            needed = {"state", "measure", "url"} | (set() if r.get("pending") else {"yes_votes", "no_votes"})
            missing = needed - set(r)
            if missing:
                raise ValueError(f"{var} {r.get('state')}: missing {sorted(missing)}")
            if r.get("pending"):
                continue
            if int(r["yes_votes"]) < 0 or int(r["no_votes"]) < 0 or int(r["yes_votes"]) + int(r["no_votes"]) == 0:
                raise ValueError(f"{var} {r['state']}: vote counts must be positive")
    return cfg


def result_row(r: dict) -> dict:
    yes, no = int(r["yes_votes"]), int(r["no_votes"])
    share = yes / (yes + no)
    return {"state": r["state"], "support": share, "majority": "support" if yes > no else "oppose" if no > yes else "too_close",
            "votes": yes + no, "measure": r["measure"], "url": r["url"]}


def certified(cfg: dict) -> tuple[dict, list[str]]:
    """The config with only certified results, and items with none yet dropped; plus what was left out."""
    items, waiting = {}, []
    for var, item in cfg["items"].items():
        done = [r for r in item.get("results", []) if not r.get("pending")]
        waiting += [f"{var} {r['state']}" for r in item.get("results", []) if r.get("pending")]
        if done:
            items[var] = {**item, "results": done}
    return {**cfg, "items": items}, waiting


def load(conn, year: int) -> dict:
    cfg, waiting = certified(load_config(year))
    for w in waiting:
        log.info("Not certified yet, skipped: %s", w)
    if not cfg["items"]:
        raise ValueError(f"No certified results in config/ballot_{year}_items.yaml yet")
    links = ces.link(conn, year, cfg)
    seats = ces.house_seats(conn, year)
    conn.commit()     # close the lookups' transaction so the block below is a real transaction
    survey, items = cfg["survey"], list(cfg["items"])
    src = {**cfg["source"], "kind": KIND}
    rows = 0
    with conn.transaction(), conn.cursor() as cur:
        ces.save_items(cur, survey, src, None, [(v, cfg["items"][v], None) for v in items], links)
        for var in items:
            for r in map(result_row, cfg["items"][var].get("results", [])):
                areas = [None] + ([0] if seats.get(r["state"]) == [0] else [])
                for district in areas:
                    cur.execute(
                        """insert into core.opinion_estimate (survey, variable, state, district, respondents, effective_n,
                               raw_support, support, support_low, support_high, majority, method, source_url, area_note)
                           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (survey, var, r["state"], district, r["votes"], r["votes"], r["support"], r["support"],
                         r["support"], r["support"], r["majority"], METHOD, r["url"], r["measure"]))
                    rows += 1
    return {"items": len(items), "votes_linked": len(links), "area_rows": rows, "not_certified_yet": len(waiting)}


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = argv[1:]
    if len(args) != 2 or args[0] not in ("link", "load") or not args[1].isdigit():
        print(__doc__)
        return 2
    from .. import db
    from .votes import record_run
    year = int(args[1])
    with db.connect() as conn:
        if args[0] == "link":
            ces.link(conn, year, load_config(year))
        else:
            print(record_run(conn, f"ballots_{year}", lambda: load(conn, year)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
