"""Census district profiles and the v2 district estimates that use them."""

import random

from congress_congruence import opinion
from congress_congruence.ingest import district_profile as dp

HEADER = ["NAME", *dp.VARIABLES, "state", "congressional district"]


def row(name, state, cd, adults=1000, ba=300, income=60000, people=2000, white=1200, black=200, hisp=400, age=38):
    vals = {"B15002_001E": adults, "B19013_001E": income, "B03002_001E": people, "B03002_003E": white,
            "B03002_004E": black, "B03002_012E": hisp, "B01002_001E": age}
    vals.update({k: 0 for k in dp.BA_PLUS})
    vals[dp.BA_PLUS[0]] = ba
    return [name, *[str(vals[k]) for k in dp.VARIABLES], state, cd]


def test_parse_reads_lines_shares_and_skips_delegates():
    table = [HEADER,
             row("Congressional District 6 (119th Congress), Texas", "48", "06"),
             row("Congressional District (at Large) (119th Congress), Wyoming", "56", "00", income=-666666666),
             row("Delegate District (at Large) (119th Congress), District of Columbia", "11", "98")]
    congress, rows = dp.parse(table)
    assert congress == 119 and len(rows) == 2
    tx, wy = rows
    assert tx == {"state": "TX", "district": 6, "pct_ba": 30.0, "median_income": 60000.0, "pct_white_nh": 60.0,
                  "pct_black": 10.0, "pct_hispanic": 20.0, "median_age": 38.0}
    assert wy["district"] == 0 and wy["median_income"] is None          # Census missing-value code


def simulated(seed, informative=True):
    """Eight states of 10 districts; true support follows the BA share when informative."""
    rng = random.Random(seed)
    responses, profiles, truth = [], {}, {}
    seats = {st: list(range(1, 11)) for st in ("AA", "BB", "CC", "DD", "EE", "FF", "GG", "HH")}
    for st in seats:
        for d in seats[st]:
            ba = rng.uniform(15, 55)
            p = 0.5 + (ba - 35) / 100 if informative else 0.5 + rng.uniform(-0.05, 0.05)
            truth[(st, d)] = p
            profiles[(st, d)] = {"pct_ba": ba, "median_income": 60000, "pct_white_nh": 60 + rng.uniform(-5, 5),
                                 "pct_black": 12, "pct_hispanic": 15, "median_age": 38 + rng.uniform(-2, 2)}
            for _ in range(40):
                responses.append((st, d, int(rng.random() < p), 1.0))
    return responses, seats, profiles, truth


def error(areas, truth):
    return sum((a.support - truth[(a.state, a.district)]) ** 2 for a in areas) / len(areas)


def test_profiles_sharpen_districts_when_they_explain_differences():
    better = 0
    for seed in range(6):
        resp, seats, prof, truth = simulated(seed)
        _, v1 = opinion.estimate(resp, seats)
        _, v2 = opinion.estimate(resp, seats, prof)
        better += error(v2, truth) < error(v1, truth)
    assert better >= 5


def test_profiles_do_little_harm_when_they_explain_nothing():
    for seed in range(4):
        resp, seats, prof, truth = simulated(seed, informative=False)
        _, v1 = opinion.estimate(resp, seats)
        _, v2 = opinion.estimate(resp, seats, prof)
        assert error(v2, truth) < error(v1, truth) + 0.001


def test_missing_profile_means_state_only_pooling():
    resp, seats, prof, _ = simulated(1)
    prof.pop(("AA", 3))
    assert opinion.profile_matrix(sorted(prof) + [("AA", 3)], prof) is None
    _, with_gap = opinion.estimate(resp, seats, prof)
    _, v1 = opinion.estimate(resp, seats)
    assert [round(a.support, 6) for a in with_gap] == [round(a.support, 6) for a in v1]
