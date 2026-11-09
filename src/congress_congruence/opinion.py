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

v2 ("partial-pooling-v2-census"): districts are pulled toward their state's estimate plus a
prediction from their Census profile (education, income, age, race and ethnicity), fitted
across all districts, instead of toward the state alone. Used when every district has a profile.
Still simpler than full MRP (no election results, no individual-level model). Nothing here
touches the database.
"""

from dataclasses import dataclass
from math import log, sqrt

# Range multiplier. The textbook 90% value is 1.645, but these estimates treat the
# pooling strength as known, so ranges built with 1.645 caught the true value only
# 84-87% of the time in simulations with realistic district differences. 1.9 brings
# coverage to 91-96% across those scenarios, with about 1% of clear calls wrong.
Z90 = 1.9
METHOD = "partial-pooling-v1.1"
METHOD_WITH_PROFILES = "partial-pooling-v2-census"   # districts pulled toward a Census-profile prediction
PROFILE_FIELDS = ("pct_ba", "median_income", "pct_white_nh", "pct_black", "pct_hispanic", "median_age")
RIDGE = 0.1              # shrinks the profile coefficients a little, so a few odd districts can't swing them
MAX_BLANK = 0.02         # at most 2% of the district figures may be blank (filled with the state average)
MIN_DISTRICTS_PER_FIELD = 10   # fit the profile only with at least this many districts with respondents
                               # per profile figure (60); fewer, and it can chase noise (simulated: worse
                               # than state-only pooling with 20 districts, no worse with 435)
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


def profile_matrix(keys: list[tuple[str, int]], profiles: dict) -> list[list[float]] | None:
    """Census profile of each district, as differences from the average district in its state
    (so the state's own level isn't counted twice), each scaled to a standard deviation of 1.
    A figure the Census left blank for a district counts as its state's average (difference 0):
    a few releases leave the race and ethnicity counts empty for 1-4 districts. None if any
    district has no profile at all, or more than MAX_BLANK of the figures are blank."""
    rows, blanks = [], 0
    for k in keys:
        p = profiles.get(k)
        if not p:
            return None
        row = []
        for f in PROFILE_FIELDS:
            v = p.get(f)
            if v is None:
                blanks += 1
                row.append(None)
            else:
                row.append(log(max(v, 1.0)) if f == "median_income" else float(v))
        rows.append(row)
    if blanks > MAX_BLANK * len(keys) * len(PROFILE_FIELDS):
        return None
    by_state: dict[str, list[int]] = {}
    for i, (st, _) in enumerate(keys):
        by_state.setdefault(st, []).append(i)
    centered = [[0.0] * len(PROFILE_FIELDS) for _ in rows]
    for idx in by_state.values():
        for j in range(len(PROFILE_FIELDS)):
            known = [rows[i][j] for i in idx if rows[i][j] is not None]
            m = sum(known) / len(known) if known else 0.0
            for i in idx:
                centered[i][j] = rows[i][j] - m if rows[i][j] is not None else 0.0
    for j in range(len(PROFILE_FIELDS)):
        col = [r[j] for r in centered]
        sd = sqrt(sum(c * c for c in col) / len(col)) or 1.0
        for r in centered:
            r[j] /= sd
    return centered


def profile_predictions(keys, X, raw, state_est, tau2):
    """Each district's expected share from its state's estimate plus its Census profile:
    a weighted ridge regression of (raw district share - state estimate) on the profile,
    fitted across all districts with respondents. Returns ({key: prediction}, {key: variance})."""
    import numpy as np
    Xa = np.array(X)
    use = [i for i, k in enumerate(keys) if raw[k][0] is not None and raw[k][1] > 0]
    k_ = Xa.shape[1]
    if len(use) < MIN_DISTRICTS_PER_FIELD * k_:
        return ({k: state_est[k[0]] for k in keys}, {k: 0.0 for k in keys})
    y = np.array([raw[keys[i]][0] - state_est[keys[i][0]] for i in use])
    w = np.array([1.0 / (max(state_est[keys[i][0]] * (1 - state_est[keys[i][0]]), 1e-4) / raw[keys[i]][1] + tau2)
                  for i in use])
    Xu = Xa[use]
    xtwx = Xu.T @ (Xu * w[:, None])
    lam = RIDGE * np.trace(xtwx) / k_
    cov = np.linalg.inv(xtwx + lam * np.eye(k_))
    beta = cov @ (Xu.T @ (w * y))
    pred, var = {}, {}
    for i, key in enumerate(keys):
        x = Xa[i]
        pred[key] = float(min(max(state_est[key[0]] + x @ beta, 0.02), 0.98))
        var[key] = float(x @ cov @ x)
    return pred, var


def estimate(responses: list[tuple[str, int | None, int, float]],
             districts_by_state: dict[str, list[int]],
             profiles: dict | None = None) -> tuple[list[Area], list[Area]]:
    """responses: (state, district or None, support 1/0, weight) for people who answered.
    districts_by_state: every House district to report, so districts nobody in the sample
    lives in still get an (uncertain) estimate from their state.
    profiles: optional {(state, district): Census profile} for the survey's district lines. With
    them, each district is pulled toward what its state's estimate plus its own profile predict
    (v2) rather than toward the state alone (v1), so districts differ as much as the data supports.
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
    keys = sorted(dist_raw)
    parent = {k: state_est[k[0]] for k in keys}
    parent_var = {k: state_var[k[0]] for k in keys}
    X = profile_matrix(keys, profiles) if profiles else None
    if X is not None:
        tau2_guess = between_variance([(dist_raw[k][0], dist_raw[k][1], parent[k]) for k in keys])
        pred, pvar = profile_predictions(keys, X, dist_raw, state_est, tau2_guess)
        parent = pred
        parent_var = {k: state_var[k[0]] + pvar[k] for k in keys}
    tau2_dist = between_variance([(dist_raw[k][0], dist_raw[k][1], parent[k]) for k in keys])
    districts = []
    for (st, d) in keys:
        p, n_eff, n = dist_raw[(st, d)]
        est, lo, hi = pool(p, n_eff, parent[(st, d)], tau2_dist, parent_var[(st, d)])
        districts.append(Area(st, d, n, n_eff, p, est, lo, hi))
    return states, districts
