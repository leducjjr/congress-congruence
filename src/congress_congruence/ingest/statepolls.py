"""Statewide polls that publish their results (toplines), compared with the state's members.

    python -m congress_congruence.ingest.statepolls link tpp    # which vote each question is compared with
    python -m congress_congruence.ingest.statepolls load tpp    # link + store each poll's statewide result
    python -m congress_congruence.ingest.statepolls load unh    # UNH Survey Center polls (NH, ME, VT, MA)

config/<name>_items.yaml lists each poll (stored as its own survey, e.g. "Texas Politics Project, Aug
2025") with its state, source details, margin of error and the questions used, each with its published
percentages for the two sides and the vote(s) it's compared with. Results are statewide, so they're
compared with the state's senators, and with its House member only where the state has a single
at-large seat (the statewide result is then that district's too); never with a district's member.

How results are turned into estimates (method published-topline-v1, the same arithmetic as PPC's):
  support    = favor / (favor + oppose)     (people who took a side; "neither" and "don't know" left out)
  range      = support +/- MOE * (Z90 / 1.96) / (favor + oppose)
  effective_n = (0.98 / MOE)^2               (the sample size a simple random sample with that MOE would have)
where MOE is the poll's published margin of error (95%), times the square root of its design effect
when the poll gives one and says its margin doesn't include it (design_effect in the item file),
converted to the 90% level used for every estimate on the site. Every question must match a vote, or
nothing is loaded.
"""

import logging
import sys

import yaml

from .. import config, opinion
from . import ces

log = logging.getLogger(__name__)

METHOD = "published-topline-v1"


def config_path(name: str):
    return config.PROJECT_ROOT / "config" / f"{name}_items.yaml"


def load_config(path=None) -> dict:
    """A poll list; path is a file or a name such as "tpp" (config/tpp_items.yaml)."""
    path = config_path("tpp") if path is None else config_path(path) if isinstance(path, str) else path
    cfg = yaml.safe_load(path.read_text())
    for poll in cfg["polls"]:
        poll.setdefault("state", cfg.get("state"))
        for key in ("survey", "state", "congress", "moe", "respondents", "source", "items"):
            if not poll.get(key):
                raise ValueError(f"{poll.get('survey', 'a poll')}: missing {key}")
        for var, item in poll["items"].items():
            missing = {"question", "favor", "oppose", "url", "votes"} - set(item)
            if missing:
                raise ValueError(f"{var}: missing {sorted(missing)}")
            if not item["votes"] or set(item["votes"]) - {"senate", "house"}:
                raise ValueError(f"{var}: votes must be senate and/or house")
            if "house" in item["votes"] and not poll.get("at_large"):
                raise ValueError(f"{var}: statewide results are compared with senators only, and with a House "
                                 "member only for a state with a single at-large seat (set at_large: true)")
            if not 0 < item["favor"] + item["oppose"] <= 100:
                raise ValueError(f"{var}: favor + oppose must be between 1 and 100")
    return cfg


def estimate(favor: float, oppose: float, moe: float, n: int, state: str = "TX", district: int | None = None,
             design_effect: float = 1.0) -> opinion.Area:
    answered = (favor + oppose) / 100
    support = (favor / 100) / answered
    m = moe / 100 * design_effect ** 0.5
    half = m * (opinion.Z90 / 1.96) / answered
    return opinion.Area(state=state, district=district, respondents=n, effective_n=round((0.98 / m) ** 2, 1),
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
    for poll in cfg["polls"]:
        if poll.get("at_large"):
            seats = ces.house_seats(conn, 1787 + 2 * int(poll["congress"]) + 1)
            if seats.get(poll["state"]) != [0]:
                raise ValueError(f"{poll['survey']}: {poll['state']} doesn't have a single at-large House seat")
    conn.commit()     # close the lookups' transaction so the block below is a real transaction
    counts = {"support": 0, "oppose": 0, "too_close": 0}
    with conn.transaction(), conn.cursor() as cur:
        for poll in cfg["polls"]:
            survey = poll["survey"]
            src = {**poll["source"], "kind": "survey"}
            ces.save_items(cur, survey, src, poll["respondents"],
                           [(v, item, None) for v, item in poll["items"].items()], links[survey])
            for var, item in poll["items"].items():
                # Statewide; repeated for a single at-large seat so its House member is compared too.
                for district in [None] + ([0] if poll.get("at_large") else []):
                    a = estimate(item["favor"], item["oppose"], poll["moe"], poll["respondents"], poll["state"],
                                 district, float(poll.get("design_effect") or 1.0))
                    cur.execute(
                        """insert into core.opinion_estimate (survey, variable, state, district, respondents, effective_n,
                               raw_support, support, support_low, support_high, majority, method, source_url)
                           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (survey, var, a.state, a.district, a.respondents, a.effective_n, a.raw_support, a.support,
                         a.low, a.high, a.majority, METHOD, item["url"]))
                    if district is None:
                        counts[a.majority] += 1
    return {"polls": len(cfg["polls"]), "items": sum(len(p["items"]) for p in cfg["polls"]),
            "votes_linked": sum(map(len, links.values())), "calls": counts}


def main(argv: list[str], default: str | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = argv[1:] + ([default] if default and len(argv) == 2 else [])
    if len(args) != 2 or args[0] not in ("link", "load") or not config_path(args[1]).exists():
        print(__doc__)
        return 2
    from .. import db
    from .votes import record_run
    cfg = load_config(args[1])
    with db.connect() as conn:
        if args[0] == "link":
            for poll in cfg["polls"]:
                ces.link(conn, 0, poll)
                print()
        else:
            print(record_run(conn, args[1], lambda: load(conn, cfg)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
