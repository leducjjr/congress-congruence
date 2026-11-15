"""University of Texas / Texas Politics Project polls, from their published toplines.

    python -m congress_congruence.ingest.tpp link     # which Senate vote each question is compared with
    python -m congress_congruence.ingest.tpp load     # link + store each poll's statewide result

config/tpp_items.yaml lists each poll (stored as its own survey, e.g. "Texas Politics Project, Aug 2025")
with its source details, margin of error and the questions used, each with its published approve /
disapprove percentages and the vote it's compared with. Results are statewide, so only Texas's two
senators are compared; House members never are.

How results are turned into estimates (method published-topline-v1, the same arithmetic as PPC's):
  support    = favor / (favor + oppose)     (people who took a side; "neither" and "don't know" left out)
  range      = support +/- MOE * (Z90 / 1.96) / (favor + oppose)
  effective_n = (0.98 / MOE)^2               (the sample size a simple random sample with that MOE would have)
where MOE is the poll's published margin of error adjusted for weighting (95%), converted to the 90%
level used for every estimate on the site. Every question must match a vote, or nothing is loaded.
"""

import logging
import sys

import yaml

from .. import config, opinion
from . import ces

log = logging.getLogger(__name__)

METHOD = "published-topline-v1"
STATE = "TX"
CONFIG = "tpp_items.yaml"


def load_config(path=None) -> dict:
    path = path or config.PROJECT_ROOT / "config" / CONFIG
    cfg = yaml.safe_load(path.read_text())
    for poll in cfg["polls"]:
        for key in ("survey", "congress", "moe", "respondents", "source", "items"):
            if key not in poll:
                raise ValueError(f"{poll.get('survey', 'a poll')}: missing {key}")
        for var, item in poll["items"].items():
            missing = {"question", "favor", "oppose", "url", "votes"} - set(item)
            if missing:
                raise ValueError(f"{var}: missing {sorted(missing)}")
            if set(item["votes"]) != {"senate"}:
                raise ValueError(f"{var}: statewide results are compared with senators only")
            if not 0 < item["favor"] + item["oppose"] <= 100:
                raise ValueError(f"{var}: favor + oppose must be between 1 and 100")
    return cfg


def estimate(favor: float, oppose: float, moe: float, n: int) -> opinion.Area:
    answered = (favor + oppose) / 100
    support = (favor / 100) / answered
    m = moe / 100
    half = m * (opinion.Z90 / 1.96) / answered
    return opinion.Area(state=STATE, district=None, respondents=n, effective_n=round((0.98 / m) ** 2, 1),
                        raw_support=support, support=support,
                        low=max(0.0, support - half), high=min(1.0, support + half))


def link_all(conn, cfg: dict) -> dict[str, list[tuple]]:
    out = {}
    for poll in cfg["polls"]:
        links = ces.link(conn, 0, poll)
        found = {lk[1] for lk in links}
        missing = set(poll["items"]) - found
        if missing:
            raise ValueError(f"{poll['survey']}: no vote found for {sorted(missing)}; nothing loaded")
        out[poll["survey"]] = links
        print()
    return out


def load(conn, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    links = link_all(conn, cfg)
    conn.commit()     # close the lookups' transaction so the block below is a real transaction
    counts = {"support": 0, "oppose": 0, "too_close": 0}
    with conn.transaction(), conn.cursor() as cur:
        for poll in cfg["polls"]:
            survey = poll["survey"]
            src = {**poll["source"], "kind": "survey"}
            ces.save_items(cur, survey, src, poll["respondents"],
                           [(v, item, None) for v, item in poll["items"].items()], links[survey])
            for var, item in poll["items"].items():
                a = estimate(item["favor"], item["oppose"], poll["moe"], poll["respondents"])
                cur.execute(
                    """insert into core.opinion_estimate (survey, variable, state, district, respondents, effective_n,
                           raw_support, support, support_low, support_high, majority, method, source_url)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (survey, var, a.state, a.district, a.respondents, a.effective_n, a.raw_support, a.support,
                     a.low, a.high, a.majority, METHOD, item["url"]))
                counts[a.majority] += 1
    return {"polls": len(cfg["polls"]), "items": sum(len(p["items"]) for p in cfg["polls"]),
            "votes_linked": sum(map(len, links.values())), "calls": counts}


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = argv[1:]
    if args not in (["link"], ["load"]):
        print(__doc__)
        return 2
    from .. import db
    from .votes import record_run
    with db.connect() as conn:
        if args[0] == "link":
            for poll in load_config()["polls"]:
                ces.link(conn, 0, poll)
                print()
        else:
            print(record_run(conn, "tpp", lambda: load(conn)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
