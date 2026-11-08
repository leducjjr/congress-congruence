"""Estimate the share of people supporting a survey question in each state and district.

Method (v1, "partial pooling"):

1. In each area, the weighted share answering Support among those who answered
   Support or Oppose, and its effective sample size: (sum of weights)^2 / sum of
   squared weights, which shrinks when a few respondents carry big weights.
2. States are pulled toward the national share, and districts toward their state's
   estimate, more strongly the fewer effective respondents they have. How hard to
   pull is learned from the data: if districts within states really differ, the pull
   is weak; if the differences look like sampling noise, it is strong.
       estimate = (n_eff * raw + k * parent) / (n_eff + k)
       k = parent * (1 - parent) / between_area_variance
3. A 90% range from the pooled estimate's standard error (widened so it really
   covers 90% in simulation; see Z90). If the range includes 50%, the area's
   majority is "too close" to call.

This is simpler than full MRP (which would also use each district's demographics
and past election results); it is honest about uncertainty but districts with few
respondents will mostly show "too close". Nothing here touches the database.
"""

from dataclasses import dataclass
from math import sqrt

# Range multiplier. The textbook 90% value is 1.645, but these estimates treat the
# pooling strength as known, so ranges built with 1.645 caught the true value only
# 84-87% of the time in simulations with realistic district differences. 1.9 brings
# coverage to 91-96% across those scenarios, with about 1% of clear calls wrong.
Z90 = 1.9
METHOD = "partial-pooling-v1.1"
MIN_TAU2 = 0.0025        # floor on between-area variance: assume areas can differ by at least ~5 points.
                         # Without it, a small apparent spread pools areas so hard that ranges get
                         # unrealistically narrow.


@dataclass
class Area:
    state: str
    district: int | None      # None = statewide
    respondents: int
    effective_n: float
    raw_support: float | None
    support: float
    low: float
    high: float

    @property
    def majority(self) -> str:
        if self.low > 0.5:
            return "support"
        if self.high < 0.5:
            return "oppose"
        return "too_close"


def summarize(answers) -> tuple[float, float, int, float | None]:
    """answers: iterable of (support 0/1, weight). Returns (sum_w, sum_w2, count, weighted share)."""
    sw = sw2 = sy = 0.0
    n = 0
    for y, w in answers:
        if w is None or w <= 0:
            continue
        sw += w
        sw2 += w * w
        sy += w * y
        n += 1
    return sw, sw2, n, (sy / sw if sw else None)


def effective_n(sw: float, sw2: float) -> float:
    return (sw * sw / sw2) if sw2 else 0.0


def between_variance(groups: list[tuple[float | None, float, float]]) -> float:
    """Method-of-moments estimate of true between-area variance.
    groups: (raw share, effective n, parent share). Observed spread minus expected sampling noise."""
    usable = [(p, n, m) for p, n, m in groups if p is not None and n >= 2]
    if len(usable) < 3:
        return MIN_TAU2
    total_w = sum(n for _, n, _ in usable)
    spread = sum(n * (p - m) ** 2 for p, n, m in usable) / total_w
    noise = sum(n * (m * (1 - m) / n) for _, n, m in usable) / total_w
    return max(MIN_TAU2, spread - noise)


def pool(raw: float | None, n_eff: float, parent: float, tau2: float,
         parent_var: float = 0.0) -> tuple[float, float, float]:
    """(estimate, low, high) after pulling raw toward parent.
    parent_var: uncertainty in the parent itself, carried into the area in
    proportion to how much the area leans on it."""
    parent = min(max(parent, 1e-6), 1 - 1e-6)
    k = parent * (1 - parent) / tau2
    has_data = raw is not None and n_eff > 0
    est = (n_eff * raw + k * parent) / (n_eff + k) if has_data else parent
    lean = k / (n_eff + k) if has_data else 1.0
    var = est * (1 - est) / ((n_eff if has_data else 0) + k) + lean * lean * parent_var
    se = sqrt(var)
    return est, max(0.0, est - Z90 * se), min(1.0, est + Z90 * se)


def estimate(responses: list[tuple[str, int | None, int, float]],
             districts_by_state: dict[str, list[int]]) -> tuple[list[Area], list[Area]]:
    """responses: (state, district or None, support 1/0, weight) for people who answered.
    districts_by_state: every House district to report, so districts nobody in the sample
    lives in still get an (uncertain) estimate from their state.
    Returns (state areas, district areas)."""
    by_state: dict[str, list] = {}
    by_district: dict[tuple[str, int], list] = {}
    for st, dist, y, w in responses:
        by_state.setdefault(st, []).append((y, w))
        if dist is not None:
            by_district.setdefault((st, dist), []).append((y, w))

    nat_sw, nat_sw2, _, national = summarize((y, w) for st in by_state for y, w in by_state[st])
    if national is None:
        raise ValueError("No usable responses")

    # States toward the nation.
    state_raw = {}
    for st in set(by_state) | set(districts_by_state):
        sw, sw2, n, p = summarize(by_state.get(st, []))
        state_raw[st] = (p, effective_n(sw, sw2), n)
    tau2_state = between_variance([(p, n_eff, national) for p, n_eff, _ in state_raw.values()])
    states = []
    for st, (p, n_eff, n) in sorted(state_raw.items()):
        est, lo, hi = pool(p, n_eff, national, tau2_state)
        states.append(Area(st, None, n, n_eff, p, est, lo, hi))
    state_est = {a.state: a.support for a in states}
    state_var = {a.state: ((a.high - a.low) / (2 * Z90)) ** 2 for a in states}

    # Districts toward their state's estimate.
    dist_raw = {}
    for st, dists in districts_by_state.items():
        for d in dists:
            sw, sw2, n, p = summarize(by_district.get((st, d), []))
            dist_raw[(st, d)] = (p, effective_n(sw, sw2), n)
    tau2_dist = between_variance([(p, n_eff, state_est[st]) for (st, _), (p, n_eff, _) in dist_raw.items()])
    districts = []
    for (st, d), (p, n_eff, n) in sorted(dist_raw.items()):
        est, lo, hi = pool(p, n_eff, state_est[st], tau2_dist, state_var[st])
        districts.append(Area(st, d, n, n_eff, p, est, lo, hi))
    return states, districts
