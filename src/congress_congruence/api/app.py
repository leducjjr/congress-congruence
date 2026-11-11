"""Read-only JSON API for the panels and, later, the phone app.

Run locally:
    uvicorn congress_congruence.api.app:app --port 8000

Endpoints (GET unless marked):
    /v1/health                         is the database reachable; how fresh is the data
    /v1/surveys                        every survey loaded, with links (Sources page)
    /v1/surveyed                       every survey question compared with a vote (Surveyed votes page)
    /v1/surveyed/detail?survey=&item=  one question: each member's vote against their area's opinion
    POST /v1/feedback                  the feedback form: emailed to the project inbox, never stored
    /v1/search?q=abort*                members (name, state, seat), survey questions and votes
    /v1/votes?chamber=&congress=&kind= every recorded vote, filtered (All votes page); /v1/votes/filters
    /v1/votes/{roll_call_id}           one vote and every member's position on it
    /v1/compare?a=&b=                  two members: votes they both cast, and where they split
    /v1/states/{code}                  a state's members, their surveyed-vote counts, statewide survey results
    /v1/members?state=TX&chamber=house members serving today (&include=former adds those who've left)
    /v1/members/{bioguide_id}          profile, attendance, votes with party majority
    /v1/members/{bioguide_id}/votes    most recent votes (limit=1..100, default 20)
    /v1/members/{bioguide_id}/opinion  surveyed votes compared with constituents' estimated views

Settings (environment or .env):
    API_DATABASE_URL   connection for a read-only database login (falls back to DATABASE_URL)
    API_CORS_ORIGINS   comma-separated sites allowed to call the API from a browser (optional)

The API never writes. Connections are opened read-only, and in production the
database login itself only has SELECT permission (see deploy/README.md).
"""

import os
import re
import unicodedata
from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import Body, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .. import config  # noqa: F401  (loads .env)
from ..ingest.ppc import STATE_NAMES as ppc_states
from ..ingest.votes import current_session
from . import feedback as fb
from . import queries as q

BIOGUIDE_RE = re.compile(r"^[A-Z]\d{6}$")
STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
    "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC", "PR", "GU", "VI", "AS", "MP",
}
CACHE = "public, max-age=300"   # data changes at most every couple of hours

pool: ConnectionPool | None = None


def database_url() -> str:
    url = os.environ.get("API_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Set API_DATABASE_URL (or DATABASE_URL)")
    return url


def make_read_only(conn) -> None:
    # psycopg's conn.read_only only applies to transactions it opens, which it doesn't
    # do in autocommit mode, so set Postgres's own session default instead.
    conn.autocommit = True
    conn.execute("set default_transaction_read_only = on")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = ConnectionPool(database_url(), min_size=1, max_size=5, configure=make_read_only,
                          kwargs={"row_factory": dict_row}, open=True)
    try:
        yield
    finally:
        pool.close()


app = FastAPI(title="congress-congruence API", version="0.1.0", lifespan=lifespan,
              docs_url="/v1/docs", openapi_url="/v1/openapi.json")

origins = [o.strip() for o in os.environ.get("API_CORS_ORIGINS", "").split(",") if o.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"])


def fetch(sql: str, params: dict | None = None) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(sql, params or {}).fetchall()


def member_summary(row: dict) -> dict:
    return {
        "bioguide_id": row["bioguide_id"],
        "name": row["name"],
        "chamber": row["chamber"],
        "state": row["state"],
        "district": row["district"] if row["chamber"] == "house" else None,
        "seat": q.seat_label(row["state"], row["district"], row["chamber"]),
        "party": row["party"],
        "caucus": row["caucus"],
    }


def pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


@app.get("/v1/health")
def health(response: Response):
    response.headers["Cache-Control"] = "no-cache"
    data = [{"chamber": r["chamber"], "source": r["source"], "votes": r["votes"],
             "first_vote": r["first_vote"], "latest_vote": r["latest_vote"],
             "first_congress": r["first_congress"], "latest_congress": r["latest_congress"]}
            for r in fetch(q.FRESHNESS)]
    runs = {r["job"]: r["finished_at"] for r in fetch(q.LAST_RUNS)}
    return {"status": "ok", "data": data, "last_successful_runs": runs}


@app.get("/v1/surveys")
def surveys(response: Response):
    """Every survey loaded, newest first within each organization (for the Sources page)."""
    response.headers["Cache-Control"] = CACHE
    keys = ("survey", "title", "fielded", "respondents", "dataset_url", "guide_url", "about_url",
            "organization", "description", "kind", "items")
    return {"surveys": [{k: r[k] for k in keys} for r in fetch(q.SURVEY_LIST)]}


def fold(text: str) -> str:
    """Lowercase without accents, so 'velazquez' finds 'Velázquez'."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


STATE_NAMES = {fold(name): code for name, code in {
    **ppc_states, "District of Columbia": "DC", "Washington DC": "DC", "Puerto Rico": "PR", "Guam": "GU",
    "Virgin Islands": "VI", "U.S. Virgin Islands": "VI", "American Samoa": "AS",
    "Northern Mariana Islands": "MP"}.items()}
SEAT_RE = re.compile(r"^([a-z]{2})\s*-?\s*(\d{1,2}|al|at-large)$")


def latest_first(former: list[dict]) -> list[dict]:
    """Former members, most recently in office first (like the votes, newest first)."""
    return sorted(former, key=lambda r: (-(r["end_date"].toordinal() if r.get("end_date") else 0),
                                         r.get("last_name") or "", r.get("name") or ""))


def search_members(query: str, rows: list[dict], limit: int = 12) -> list[dict]:
    """Members matching a name, a state, or a seat; current members before former ones, who are
    listed most recently in office first."""
    found = match_members(query, rows)
    return ([r for r in found if not r.get("former")] + latest_first([r for r in found if r.get("former")]))[:limit]


def match_members(query: str, rows: list[dict], limit: int | None = None) -> list[dict]:
    """Members matching a name, a state, or a seat; current members before former ones. Examples:
    'cruz', 'ted c', 'velazquez', 'Texas', 'TX', 'TX-7', 'tx 7', 'ak-al'. A trailing * is ignored."""
    q = fold(query).replace("*", " ").strip()
    q = re.sub(r"\s+", " ", q)
    if not q:
        return []
    seat = SEAT_RE.match(q)
    if seat and seat.group(1).upper() in STATES:
        st, d = seat.group(1).upper(), seat.group(2)
        district = 0 if d in ("al", "at-large") else int(d)
        found = [r for r in rows if r["chamber"] == "house" and r["state"] == st and (r["district"] or 0) == district]
        return sorted(found, key=lambda r: bool(r.get("former")))[:limit]
    state = STATE_NAMES.get(q) or (q.upper() if len(q) == 2 and q.upper() in STATES else None)
    if state:
        mine = [r for r in rows if r["state"] == state]
        return sorted(mine, key=lambda r: (bool(r.get("former")), r["chamber"] != "senate", r["district"] or 0,
                                           r["last_name"] or ""))[:limit]

    tokens = q.split(" ")
    scored = []
    for r in rows:
        words = re.split(r"[\s.,'-]+", fold(r["name"]))
        where = {r["state"].lower(), *[w for n, c in STATE_NAMES.items() if c == r["state"] for w in n.split()]}
        if not all(any(w.startswith(t) for w in words) or t in where for t in tokens):
            continue
        last = fold(r["last_name"] or "")
        score = (bool(r.get("former")), 0 if last.startswith(tokens[0]) else 1, r["chamber"] != "senate",
                 r["state"], r["district"] or 0)
        scored.append((score, r))
    return [r for _, r in sorted(scored, key=lambda x: x[0])][:limit]


def build_tsquery(text: str) -> str | None:
    """Turn what a visitor typed into a PostgreSQL text-search query, using only letters and digits.

    Words must all match (in any order); English word endings are handled ('abortion' also finds
    'abortions'); a trailing * matches any ending ('abort*' finds 'abortion', 'aborted');
    "quoted words" must appear together in that order ("data center")."""
    parts = []
    text = re.sub(r"(?<=[a-z])\.(?=[a-z])", "", fold(text))       # 'H.R. 1' -> 'hr. 1', 'S.J.Res.' -> 'sjres.'
    for m in re.finditer(r'"([^"]*)"?|(\S+)', text):
        if m.group(1) is not None:
            words = re.findall(r"[a-z0-9]+", m.group(1))
            if words:
                parts.append("(" + " <-> ".join(words) + ")")
            continue
        raw = m.group(2)
        words = re.findall(r"[a-z0-9]+", raw)
        for k, w in enumerate(words):
            parts.append(w + (":*" if raw.endswith("*") and k == len(words) - 1 else ""))
    return " & ".join(parts) or None


def vote_summary(r: dict) -> dict:
    return {
        "roll_call_id": r["roll_call_id"], "chamber": r["chamber"], "date": r["vote_date"],
        "question": r["question"], "description": r["description"], "result": r["result"],
        "yea": r["yea_total"], "nay": r["nay_total"], "present": r["present_total"],
        "not_voting": r["not_voting_total"],
        "bill": q.bill_info(r["bill_congress"] or r["congress"], r["bill_type"], r["bill_number"]),
        "official_url": q.official_vote_url(r["chamber"], r["congress"], r["session"], r["roll_number"],
                                            r["vote_date"]),
    }


def question_cards(qrows: list[dict], members: list[str]) -> list[dict]:
    """For survey questions (rows with survey, variable, question, note, title, organization, fielded,
    guide_url): the spread of support across areas, each chamber's vote, and how many members voted
    with or against a clear majority where they live. Shared by search and the Surveyed votes page."""
    keys = [f"{r['survey']}|{r['variable']}" for r in qrows]
    tallies, spreads, mine = {}, {}, {}
    if keys:
        for t in fetch(q.QUESTION_TALLY, {"keys": keys}):
            tallies.setdefault((t["survey"], t["variable"]), []).append(t)
        for sp in fetch(q.QUESTION_SPREAD, {"keys": keys}):
            spreads.setdefault((sp["survey"], sp["variable"]), {})["states" if sp["statewide"] else "districts"] = {
                "areas": sp["areas"], "lowest_pct": round(100 * sp["lowest"], 1),
                "highest_pct": round(100 * sp["highest"], 1), "support": sp["support_areas"],
                "oppose": sp["oppose_areas"], "too_close": sp["too_close_areas"]}
    ids = [t["roll_call_id"] for ts in tallies.values() for t in ts]
    if ids and members:
        for r in fetch(q.MEMBER_POSITIONS, {"ids": ids, "members": members}):
            mine.setdefault(r["roll_call_id"], []).append(
                {"bioguide_id": r["bioguide_id"], "name": r["name"], "position": r["position"]})
    return [{
        "survey": r["survey"], "item": r["variable"], "question": r["question"], "note": r["note"],
        "source": {"title": r["title"], "organization": r["organization"], "fielded": r["fielded"],
                   "guide_url": r["guide_url"], "about_url": r.get("about_url"), "kind": r.get("kind", "survey")},
        # A ballot measure's result is statewide; its copies for at-large House seats aren't districts.
        "spread": {k: v for k, v in spreads.get((r["survey"], r["variable"]), {}).items()
                   if r.get("kind") != "ballot" or k == "states"},
        "votes": [{
            "chamber": t["chamber"], "match": t["match_kind"], "support_side": t["support_side"],
            "roll_call_id": t["roll_call_id"], "date": t["vote_date"], "question": t["question"],
            "result": t["result"], "yea": t["yea_total"], "nay": t["nay_total"],
            "official_url": q.official_vote_url(t["chamber"], t["congress"], t["session"], t["roll_number"],
                                                t["vote_date"]),
            "members": {"with_majority": t["with_majority"], "against_majority": t["against_majority"],
                        "too_close": t["too_close"], "not_surveyed": t["not_surveyed"],
                        "did_not_vote": t["did_not_vote"]},
            "your_members": mine.get(t["roll_call_id"], []),
        } for t in sorted(tallies.get((r["survey"], r["variable"]), []), key=lambda t: t["chamber"] != "senate")],
    } for r in qrows]


def search_text(text: str, chamber: str | None, members: list[str], limit: int, sort: str = "match",
                offset: int = 0, parts: tuple[str, ...] = ("questions", "votes"), surveyed: bool = False) -> dict:
    """Survey questions and votes matching the text, with what the site can say about each.
    offset skips that many of each (for "Show more"); parts limits the answer to questions or votes."""
    out = {}
    tsq = build_tsquery(text)
    if "questions" in parts:
        qrows = fetch(q.QUESTION_SEARCH, {"tsq": tsq, "limit": limit, "offset": offset}) if tsq else []
        out.update({"questions": question_cards(qrows, members),
                    "questions_total": qrows[0]["total"] if qrows else 0})
    if "votes" in parts:
        vrows = fetch(q.VOTE_SEARCH.replace("{order}", q.VOTE_SEARCH_ORDER[sort]),
                      {"tsq": tsq, "chamber": chamber, "limit": limit, "offset": offset,
                       "surveyed": surveyed}) if tsq else []
        out.update({"votes": vote_items(vrows, members), "votes_total": vrows[0]["total"] if vrows else 0})
    return out


def vote_items(vrows: list[dict], members: list[str]) -> list[dict]:
    """Votes as listed on Search and All votes: what happened, how each party voted, which survey
    questions they're compared with, and how the visitor's own members voted."""
    ids = [r["roll_call_id"] for r in vrows]
    split, surveyed, mine = {}, {}, {}
    if ids:
        for r in fetch(q.VOTE_PARTY_SPLIT, {"ids": ids}):
            split.setdefault(r["roll_call_id"], {}).setdefault(r["party"], {})[r["position"]] = r["n"]
        for r in fetch(q.VOTE_SURVEYED, {"ids": ids}):
            surveyed.setdefault(r["roll_call_id"], []).append(
                {"survey": r["survey"], "item": r["variable"], "question": r["question"], "match": r["match_kind"]})
        if members:
            for r in fetch(q.MEMBER_POSITIONS, {"ids": ids, "members": members}):
                mine.setdefault(r["roll_call_id"], []).append(
                    {"bioguide_id": r["bioguide_id"], "name": r["name"], "position": r["position"]})

    return [{**vote_summary(r), "snippet": r["snippet"],
             "bill_title": r["bill_title"], "policy_area": r["policy_area"],
             "subjects": r["subjects"].split(" | ") if r["subjects"] else [],
             "matched_by": "title" if r["title_match"] else "subject",
             **({"kind": r["kind"], "outcome": r["outcome"]} if "kind" in r else {}),
             "by_party": split.get(r["roll_call_id"], {}),
             "surveyed": surveyed.get(r["roll_call_id"], []),
             "your_members": mine.get(r["roll_call_id"], [])} for r in vrows]


@app.get("/v1/surveyed")
def surveyed(response: Response, member: list[str] = Query([], max_length=6)):
    """Every survey question compared with a vote, newest survey first within each organization."""
    members = [m for m in member if BIOGUIDE_RE.match(m)]
    cards = question_cards(fetch(q.QUESTION_LIST), members)
    response.headers["Cache-Control"] = CACHE
    return {"questions": cards}


@app.get("/v1/surveyed/detail")
def surveyed_detail(response: Response,
                    survey: str = Query(..., min_length=3, max_length=40),
                    item: str = Query(..., min_length=2, max_length=40)):
    """One survey question: its card, and for each linked vote every member who could vote, with the
    estimated support where they live, how they voted, and whether that was with a clear majority."""
    rows = fetch(q.QUESTION_ONE, {"survey": survey, "item": item})
    if not rows:
        raise HTTPException(404, "No survey question with that name")
    card = question_cards(rows, [])[0]
    by_vote = {}
    for r in fetch(q.QUESTION_MEMBERS, {"survey": survey, "item": item}):
        surveyed_area = r["support"] is not None
        by_vote.setdefault(r["roll_call_id"], []).append({
            "bioguide_id": r["bioguide_id"], "name": r["name"], "party": r["party"],
            "state": r["state"], "seat": q.seat_label(r["state"], r["district"], r["chamber"]),
            "position": r["position"], "sided_with": sided_with(r["position"], r["support_side"]),
            "area": {"support_pct": round(100 * r["support"], 1), "low_pct": round(100 * r["support_low"], 1),
                     "high_pct": round(100 * r["support_high"], 1), "majority": r["majority"],
                     "respondents": r["respondents"], "area_note": r["area_note"],
                     "source_url": r["source_url"]} if surveyed_area else None,
            "agreement": agreement(r["position"], r["majority"], r["support_side"]) if surveyed_area
                         else ("not_surveyed" if r["position"] in ("yea", "nay") else "did_not_vote"),
        })
    for v in card["votes"]:
        v["member_votes"] = sorted(by_vote.get(v["roll_call_id"], []), key=lambda m: (m["state"], m["seat"]))
    response.headers["Cache-Control"] = CACHE
    return card


@app.get("/v1/search")
def search(response: Response,
           text: str = Query(..., alias="q", min_length=2, max_length=80),
           only: str | None = Query(None, pattern="^(members|text|questions|votes)$"),
           chamber: str | None = Query(None, pattern="^(house|senate)$"),
           member: list[str] = Query([], max_length=6),
           limit: int = Query(40, ge=1, le=100),
           offset: int = Query(0, ge=0, le=5000),
           surveyed: bool = False,
           sort: str = Query("match", pattern="^(match|newest|oldest)$")):
    """Members (name, state or seat), survey questions and votes matching what was typed.
    sort orders the votes: match (words in the title first, then newest), newest, or oldest;
    surveyed=true keeps only votes a survey question is compared with.

    only=members is for suggestions as you type; only=votes or only=questions with offset=<n> fetches
    the next page of one list ("Show more"). member=<id> (up to 6) adds how those members voted on
    each vote found ("your members"). Text matching: see build_tsquery."""
    members = [m for m in member if BIOGUIDE_RE.match(m)]
    out = {"query": text}
    if only in (None, "members"):
        rows = fetch(q.CURRENT_MEMBERS, {"on": date.today(), "state": None, "chamber": None})
        former = [{**r, "former": True} for r in fetch(q.FORMER_MEMBERS, {"on": date.today(), "state": None})]
        out["members"] = [{**member_summary(r), **({"former": True, "left_office": r["end_date"]} if r.get("former") else {})}
                          # Suggestions as you type stay short; the Search page lists a whole delegation.
                          for r in search_members(text, rows + former, 12 if only == "members" else 120)]
    if only != "members":
        parts = (only,) if only in ("questions", "votes") else ("questions", "votes")
        out.update(search_text(text, chamber, members, limit, sort, offset, parts, surveyed))
    response.headers["Cache-Control"] = CACHE
    return out


@app.post("/v1/feedback")
def feedback(request: Request, data: dict = Body(...)):
    """The site's feedback form: emailed to the project inbox, never stored (see api/feedback.py)."""
    if not isinstance(data, dict) or len(str(data)) > 6000:
        return JSONResponse({"ok": False, "message": "Your message couldn't be sent."}, status_code=400)
    try:
        result = fb.submit(data, request.client.host if request.client else "")
    except fb.Rejected as e:
        return JSONResponse({"ok": False, "message": str(e)}, status_code=e.status,
                            headers={"Cache-Control": "no-store"})
    return JSONResponse({"ok": True, **(result or {})}, headers={"Cache-Control": "no-store"})


@app.get("/v1/members")
def members(response: Response,
            state: str | None = Query(None, min_length=2, max_length=2),
            chamber: str | None = Query(None, pattern="^(house|senate)$"),
            include: str | None = Query(None, pattern="^former$")):
    if state is not None:
        state = state.upper()
        if state not in STATES:
            raise HTTPException(400, "Unknown state code")
    rows = fetch(q.CURRENT_MEMBERS, {"on": date.today(), "state": state, "chamber": chamber})
    rows.sort(key=lambda r: (r["chamber"] != "senate", r["state"], r["district"] or 0, r["last_name"]))
    out = [member_summary(r) for r in rows]
    if include == "former":     # members who have left office but have votes in the data loaded
        former = [r for r in fetch(q.FORMER_MEMBERS, {"on": date.today(), "state": state})
                  if chamber is None or r["chamber"] == chamber]
        out += [{**member_summary(r), "former": True, "left_office": r["end_date"]} for r in latest_first(former)]
    response.headers["Cache-Control"] = CACHE
    return {"members": out}


def get_member_row(bioguide_id: str) -> dict:
    if not BIOGUIDE_RE.match(bioguide_id):
        raise HTTPException(400, "A member ID looks like B001277")
    rows = fetch(q.MEMBER, {"id": bioguide_id, "on": date.today()})
    if not rows:
        raise HTTPException(404, "No member with that ID")
    return rows[0]


def seat_population(row: dict) -> dict | None:
    """Residents of the member's seat (lines of the Congress their term began in), with context."""
    if row["chamber"] == "senate":
        # Six-year terms span Congresses, and a state's population doesn't depend on district lines.
        found = fetch(q.STATE_POPULATION, {"state": row["state"]})
    else:
        congress = current_session(row["start_date"])[0]
        found = fetch(q.AREA_POPULATION, {"congress": congress, "state": row["state"], "district": row["district"]})
    if not found:
        return None
    congress = found[0]["congress"]
    ctx = fetch(q.POPULATION_CONTEXT, {"congress": congress})[0]
    return {
        "residents": found[0]["population"],
        "source": found[0]["source"],
        "congress": congress,
        "area": q.seat_label(row["state"], row["district"], row["chamber"]),
        "average_district": int(ctx["avg_district"]) if ctx["avg_district"] else None,
        "smallest_state": {"state": ctx["smallest_state"], "residents": ctx["smallest_pop"]} if ctx["smallest_state"] else None,
        "largest_state": {"state": ctx["largest_state"], "residents": ctx["largest_pop"]} if ctx["largest_state"] else None,
    }


def seat_history(terms: list[dict], today: date) -> list[dict]:
    """Terms merged into unbroken spells in one seat with one party, newest first.
    A new spell starts with a change of chamber, state, district (e.g. after redistricting) or
    party, or a gap of more than a month between terms."""
    spells: list[dict] = []
    for t in terms:
        party = t["caucus"] if t["caucus"] and t["caucus"] != t["party"] else t["party"]
        district = t["district"] if t["chamber"] == "house" else None
        last = spells[-1] if spells else None
        if (last and (last["chamber"], last["state"], last["district"], last["party"]) ==
                (t["chamber"], t["state"], district, party)
                and (t["start_date"] - last["end"]).days <= 31):
            last["end"] = max(last["end"], t["end_date"])
            continue
        spells.append({"chamber": t["chamber"], "state": t["state"], "district": district, "party": party,
                       "start": t["start_date"], "end": t["end_date"]})
    return [{"chamber": s["chamber"], "state": s["state"], "seat": q.seat_label(s["state"], s["district"], s["chamber"]),
             "party": s["party"], "start": s["start"], "end": None if s["end"] >= today else s["end"],
             "first_congress": congress_on(s["start"]), "last_congress": congress_on(min(s["end"], today) - timedelta(days=1))}
            for s in reversed(spells)]


def congress_on(day: date) -> int:
    """The Congress in session on a day (a new one begins January 3 of odd years)."""
    year = day.year - (1 if day.year % 2 == 1 and (day.month, day.day) < (1, 3) else 0)
    return (year - 1787) // 2


def period_stats(bioguide_id: str, congress: int, chamber: str) -> dict:
    st = fetch(q.STATS, {"id": bioguide_id, "congress": congress, "chamber": chamber})[0]
    return {
        "congress": congress, "chamber": chamber,
        "votes_total": st["votes_total"], "votes_missed": st["votes_missed"],
        "missed_pct": pct(st["votes_missed"], st["votes_total"]),
        "party_votes": st["party_votes"], "with_party": st["with_party"],
        "with_party_pct": pct(st["with_party"], st["party_votes"]),
        "first_vote": st["first_vote"], "last_vote": st["last_vote"],
    }


@app.get("/v1/members/{bioguide_id}")
def member(bioguide_id: str, response: Response):
    """Profile and figures. 'service' has attendance and party alignment for every Congress and
    chamber the member voted in (newest first); 'stats' is the most recent of them, or the current
    Congress if they haven't voted yet."""
    row = get_member_row(bioguide_id)
    service = []
    for p in fetch(q.SERVICE_PERIODS, {"id": bioguide_id}):
        service.append({**period_stats(bioguide_id, p["congress"], p["chamber"]),
                        "seat": q.seat_label(p["state"], p["district"], p["chamber"]) if p["state"] else None,
                        "party": p["caucus"] if p["caucus"] and p["caucus"] != p["party"] else p["party"]})
    stats = service[0] if service else period_stats(bioguide_id, current_session()[0], row["chamber"])
    response.headers["Cache-Control"] = CACHE
    return {
        **member_summary(row),
        "serving": row["serving"],
        "term": {"start": row["start_date"], "end": row["end_date"]},
        "left_office": None if row["serving"] else row["end_date"],
        "population": seat_population(row),
        "stats": stats,
        "service": service,
        "seats": seat_history(fetch(q.TERMS, {"id": bioguide_id}), date.today()),
    }


@app.get("/v1/members/{bioguide_id}/votes")
def member_votes(bioguide_id: str, response: Response, limit: int = Query(20, ge=1, le=500)):
    get_member_row(bioguide_id)
    rows = fetch(q.RECENT_VOTES, {"id": bioguide_id, "limit": limit})
    response.headers["Cache-Control"] = CACHE
    return {"votes": [{
        "roll_call_id": r["roll_call_id"],
        "chamber": r["chamber"],
        "date": r["vote_date"],
        "question": r["question"],
        "description": r["description"],
        "result": r["result"],
        "bill": q.bill_info(r["bill_congress"], r["bill_type"], r["bill_number"]),
        "yea_total": r["yea_total"],
        "nay_total": r["nay_total"],
        "position": r["position"],
        "position_detail": r["raw_position"],
        "source": r["source"],
        "official_url": q.official_vote_url(r["chamber"], r["congress"], r["session"],
                                            r["roll_number"], r["vote_date"]),
    } for r in rows]}


def sided_with(position: str, support_side: str = "yea") -> str | None:
    """Which side of the survey question the vote was on: 'support', 'oppose', or None (didn't vote)."""
    if position not in ("yea", "nay"):
        return None
    return "support" if position == support_side else "oppose"


MIN_PARTY_VOTES = 3    # a party side needs at least this many members voting


def party_position(r: dict) -> dict:
    yea, nay = r["party_yea"] or 0, r["party_nay"] or 0
    side = None
    if yea + nay >= MIN_PARTY_VOTES and yea != nay:
        side = sided_with("yea" if yea > nay else "nay", r["support_side"])
    return {"name": r["party_name"], "sided_with": side,
            # elected as an independent (or other party) but counted with the caucus they sit with
            "caucus_of": r["own_party"] if r["own_party"] and r["own_party"] != r["party_name"] else None}


def agreement(position: str, majority: str, support_side: str = "yea") -> str:
    """How a vote lines up with the estimated majority where the member represents."""
    side = sided_with(position, support_side)
    if side is None:
        return "did_not_vote"
    if majority == "too_close":
        return "too_close"
    return "with" if side == majority else "against"


def tally(items: list[dict]) -> dict:
    """Score only votes on the same proposal the survey asked about, where the majority was clear."""
    same = [i for i in items if i["match"] == "same"]
    counted = [i for i in same if i["agreement"] in ("with", "against")]
    return {"surveyed_votes": len(same), "clear_majority": len(counted),
            "with_majority": sum(i["agreement"] == "with" for i in counted),
            "related_votes": len(items) - len(same)}


@app.get("/v1/members/{bioguide_id}/opinion")
def member_opinion(bioguide_id: str, response: Response):
    row = get_member_row(bioguide_id)
    rows = fetch(q.OPINION, {"id": bioguide_id})
    surveys = {r["survey"]: r for r in fetch(q.SURVEYS)}
    items = [{
        "survey": r["survey"],
        "kind": r["kind"],                              # survey | ballot (certified votes on a state measure)
        "item": r["variable"],
        "question": r["question"],
        "note": r["note"],
        "vote": {
            "roll_call_id": r["roll_call_id"], "date": r["vote_date"], "question": r["vote_question"],
            "result": r["result"], "yea_total": r["yea_total"], "nay_total": r["nay_total"],
            "congress": r["congress"],
            "official_url": q.official_vote_url(r["chamber"], r["congress"], r["session"],
                                                r["roll_number"], r["vote_date"]),
        },
        "position": r["position"],
        # Which side of the proposal most of the member's party (or the party they caucus with) took on
        # this vote. None on a tie, or when the "party" is too small to be a group to compare with
        # (an independent who caucuses with no one would otherwise be compared with themselves).
        "party": party_position(r),
        "match": r["match_kind"],                       # same | related (related is never scored)
        "support_side": r["support_side"],              # which vote (yea/nay) supported the proposal
        "sided_with": sided_with(r["position"], r["support_side"]),
        # Where to read the exact question: the area's own PDF if the survey publishes per area,
        # else the survey's guide (search it for the item's variable name).
        "wording_url": r["source_url"] or surveys.get(r["survey"], {}).get("guide_url"),
        "wording_hint": None if r["source_url"] else r["variable"],
        "constituents": {
            "area": "state" if r["chamber"] == "senate" else "district",
            "area_label": q.seat_label(r["state"], r["seat_district"], r["chamber"]),   # seat at vote time
            "support_pct": round(100 * r["support"], 1),
            "range_pct": [round(100 * r["support_low"], 1), round(100 * r["support_high"], 1)],
            "majority": r["majority"],
            "respondents": r["respondents"],             # for a ballot measure: votes cast on it
            "residents": r["residents"],
            "area_note": r["area_note"],                 # for a ballot measure: the state's measure name
        },
        "agreement": agreement(r["position"], r["majority"], r["support_side"]),
    } for r in rows]
    samples, res = {}, {}
    for i in items:
        if i["kind"] == "ballot":
            continue                                     # votes cast, not people surveyed
        key = (i["survey"], i["constituents"]["area_label"])
        samples[key] = max(samples.get(key, 0), i["constituents"]["respondents"])
        res[key] = i["constituents"]["residents"]
    response.headers["Cache-Control"] = CACHE
    return {
        "area": q.seat_label(row["state"], row["district"], row["chamber"]),
        "summary": tally(items),
        # The same score per survey organization: sources are shown side by side, never blended.
        "by_source": [{"organization": org, **tally([i for i in items
                                                     if surveys[i["survey"]]["organization"] == org])}
                      for org in dict.fromkeys(surveys[i["survey"]]["organization"] for i in items)],
        # People surveyed where the member represented them, per survey (largest count among its questions).
        "samples": sorted(({"survey": k[0], "area_label": k[1], "surveyed": v, "residents": res.get(k)}
                           for k, v in samples.items()), key=lambda x: x["survey"], reverse=True),
        "surveys": [{
            "name": s["survey"], "title": s["title"], "fielded": s["fielded"], "respondents": s["respondents"],
            "dataset_url": s["dataset_url"], "guide_url": s["guide_url"], "about_url": s["about_url"],
            "organization": s["organization"], "description": s["description"], "kind": s["kind"],
        } for s in surveys.values() if any(i["survey"] == s["survey"] for i in items)],
        "items": items,
    }


# ---------------------------------------------------------------- All votes page

ROLL_CALL_RE = re.compile(r"^[hs]-\d{2,3}-\d-\d{1,5}$")
VOTE_KINDS = ("passage", "amendment", "nomination", "procedural", "other")


@app.get("/v1/votes/filters")
def vote_filters(response: Response):
    """What the All votes page's filters can offer: Congresses loaded in each chamber, and the
    main topics (Congress.gov policy areas) of the bills voted on."""
    congresses = {}
    for r in fetch(q.VOTE_CONGRESSES):
        c = congresses.setdefault(r["congress"], {"congress": r["congress"], "first_vote": r["first_vote"],
                                                  "last_vote": r["last_vote"], "votes": {}})
        c["votes"][r["chamber"]] = r["votes"]
        c["first_vote"], c["last_vote"] = min(c["first_vote"], r["first_vote"]), max(c["last_vote"], r["last_vote"])
    response.headers["Cache-Control"] = CACHE
    return {"congresses": list(congresses.values()),
            "topics": [{"name": r["policy_area"], "votes": r["votes"]} for r in fetch(q.VOTE_TOPICS)],
            "kinds": list(VOTE_KINDS)}


@app.get("/v1/votes")
def votes(response: Response,
          chamber: str | None = Query(None, pattern="^(house|senate)$"),
          congress: int | None = Query(None, ge=1, le=200),
          kind: str | None = Query(None, pattern="^(" + "|".join(VOTE_KINDS) + ")$"),
          outcome: str | None = Query(None, pattern="^(passed|failed)$"),
          topic: str | None = Query(None, min_length=2, max_length=80),
          surveyed: bool = False,
          text: str | None = Query(None, alias="q", max_length=80),
          member: list[str] = Query([], max_length=6),
          sort: str = Query("newest", pattern="^(newest|oldest)$"),
          limit: int = Query(25, ge=1, le=100),
          offset: int = Query(0, ge=0, le=100000)):
    """Every recorded vote, newest first, narrowed by any of the filters. kind and outcome come from
    the official wording of the question and result (see queries.VOTE_KIND, VOTE_OUTCOME)."""
    tsq = build_tsquery(text) if text and text.strip() else None
    rows = fetch(q.VOTE_LIST.replace("{order}", q.VOTE_SEARCH_ORDER[sort]),
                 {"chamber": chamber, "congress": congress, "kind": kind, "outcome": outcome, "topic": topic,
                  "surveyed": surveyed, "tsq": tsq, "limit": limit, "offset": offset})
    members = [m for m in member if BIOGUIDE_RE.match(m)]
    response.headers["Cache-Control"] = CACHE
    return {"total": rows[0]["total"] if rows else 0, "offset": offset, "votes": vote_items(rows, members)}


@app.get("/v1/votes/{roll_call_id}")
def vote_detail(roll_call_id: str, response: Response):
    """One vote and every member's position on it, with the seat and party they held that day."""
    if not ROLL_CALL_RE.match(roll_call_id):
        raise HTTPException(400, "A vote ID looks like h-119-1-23")
    rows = fetch(q.VOTE_ONE, {"id": roll_call_id})
    if not rows:
        raise HTTPException(404, "No vote with that ID")
    chamber = rows[0]["chamber"]
    response.headers["Cache-Control"] = CACHE
    return {**vote_summary(rows[0]),
            "members": [{"bioguide_id": r["bioguide_id"], "name": r["name"], "state": r["state"],
                         "seat": q.seat_label(r["state"], r["district"], chamber) if r["state"] else None,
                         "party": r["party"], "caucus": r["caucus"] if r["caucus"] != r["party"] else None,
                         "position": r["position"]}
                        for r in fetch(q.VOTE_MEMBERS, {"id": roll_call_id})]}


# ---------------------------------------------------------------- Compare two members

@app.get("/v1/compare")
def compare(response: Response,
            a: str = Query(..., min_length=7, max_length=7), b: str = Query(..., min_length=7, max_length=7),
            limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0, le=100000)):
    """Two members: how many votes they were both recorded on, how often both voting Yea or Nay
    they voted the same way, and the votes where one voted Yea and the other Nay (newest first)."""
    for x in (a, b):
        get_member_row(x)
    counts = fetch(q.COMPARE_COUNTS, {"a": a, "b": b})[0]
    splits = fetch(q.COMPARE_SPLITS, {"a": a, "b": b, "limit": limit, "offset": offset})
    response.headers["Cache-Control"] = CACHE
    return {
        "a": a, "b": b,
        "both_recorded": counts["both_recorded"], "both_voted": counts["both_voted"],
        "same_way": counts["same_way"], "same_way_pct": pct(counts["same_way"], counts["both_voted"]),
        "first_vote": counts["first_vote"], "last_vote": counts["last_vote"],
        "splits_total": splits[0]["total"] if splits else 0, "offset": offset,
        "splits": [{**vote_summary(r), "position_a": r["position_a"], "position_b": r["position_b"]} for r in splits],
    }


# ---------------------------------------------------------------- State pages

STATE_NAME = {v: k for k, v in ppc_states.items()} | {"DC": "District of Columbia", "PR": "Puerto Rico"}


def side_agreement(side: str | None, majority: str) -> str:
    """agreement() for a vote already turned into the side it took ('support'/'oppose'/None)."""
    if side is None:
        return "did_not_vote"
    return "too_close" if majority == "too_close" else ("with" if side == majority else "against")


def member_scores(ids: list[str]) -> dict[str, list[dict]]:
    """Per member, per survey organization: surveyed votes, how many had a clear majority, and how
    many of those the member voted with (the counts the member panel shows)."""
    out: dict[str, list[dict]] = {}
    if ids:
        for r in fetch(q.MEMBER_SCORES, {"ids": ids}):
            out.setdefault(r["bioguide_id"], []).append(
                {"organization": r["organization"], "surveyed_votes": r["surveyed_votes"],
                 "clear_majority": r["clear_majority"], "with_majority": r["with_majority"]})
    return out


def months_between(a: date, b: date) -> int:
    """Whole months from a to b (same rule as the member page's "13 years, 11 months")."""
    return max(0, (b.year - a.year) * 12 + (b.month - a.month) - (b.day < a.day))


@app.get("/v1/numbers")
def numbers(response: Response, congress: int | None = None, chamber: str | None = Query(None, pattern="^(house|senate)$")):
    """Members by the numbers: everyone who voted in one Congress, with the same counts as their member
    pages (votes, Yea / Nay / Present / not voting, with their party) and how long they've served:
    in Congress in all and in their latest seat, from the official member list (so service before the
    votes on this site counts too). Plain counts; the page sorts them."""
    available = sorted({r["congress"] for r in fetch(q.VOTE_CONGRESSES)}, reverse=True)
    if not available:
        raise HTTPException(404, "No votes loaded")
    congress = congress or available[0]
    if congress not in available:
        raise HTTPException(404, "No votes loaded for that Congress")
    rows = fetch(q.MEMBER_NUMBERS, {"congress": congress, "chamber": chamber})
    today = date.today()
    terms: dict[str, list[dict]] = {}
    for t in fetch(q.TERMS_FOR, {"ids": [r["bioguide_id"] for r in rows]}):
        terms.setdefault(t["bioguide_id"], []).append(t)
    members = []
    for r in rows:
        spells = seat_history(terms.get(r["bioguide_id"], []), today)        # newest first
        # Breaks in service: a gap of more than a month between one seat's end and the next's start
        # (a member who left Congress and came back). Moving seat or chamber without a gap isn't one.
        breaks = []
        for later, earlier in zip(spells, spells[1:]):
            if earlier["end"] and (later["start"] - earlier["end"]).days > 31:
                breaks.append({"left": earlier["end"], "returned": later["start"]})
        members.append({
            "bioguide_id": r["bioguide_id"], "name": r["name"], "last_name": r["last_name"],
            "chamber": r["chamber"], "state": r["state"], "district": r["district"],
            "seat": q.seat_label(r["state"], r["district"], r["chamber"]) if r["state"] else None,
            "party": r["party"], "caucus": r["caucus"],
            "serving": bool(spells) and spells[0]["end"] is None,
            "first_sworn_in": spells[-1]["start"] if spells else None,
            "breaks": list(reversed(breaks)),                                      # oldest first
            "months_in_congress": sum(months_between(s["start"], s["end"] or today) for s in spells),
            "seat_since": spells[0]["start"] if spells else None,
            "months_in_seat": months_between(spells[0]["start"], spells[0]["end"] or today) if spells else None,
            "votes_total": r["votes_total"], "yea": r["yea"], "nay": r["nay"], "present": r["present"],
            "not_voting": r["not_voting"],
            "yea_pct": pct(r["yea"], r["votes_total"]), "nay_pct": pct(r["nay"], r["votes_total"]),
            "missed_pct": pct(r["not_voting"], r["votes_total"]),
            "party_votes": r["party_votes"], "with_party": r["with_party"],
            "with_party_pct": pct(r["with_party"], r["party_votes"]),
            "first_vote": r["first_vote"], "last_vote": r["last_vote"],
        })
    members.sort(key=lambda m: (m["chamber"] != "senate", m["state"] or "", m["district"] or 0, m["last_name"]))
    response.headers["Cache-Control"] = CACHE
    return {"congress": congress, "chamber": chamber, "congresses": available, "members": members}


@app.get("/v1/states/{code}")
def state(code: str, response: Response):
    """A state: its members today and those who've left (with votes on this site), each with their
    surveyed-vote counts per source; and what the state's residents told each survey, with how the
    state's senators voted on it."""
    code = code.upper()
    if code not in STATES:
        raise HTTPException(404, "Unknown state code")
    current = fetch(q.CURRENT_MEMBERS, {"on": date.today(), "state": code, "chamber": None})
    current.sort(key=lambda r: (r["chamber"] != "senate", r["district"] or 0, r["last_name"]))
    former = latest_first(fetch(q.FORMER_MEMBERS, {"on": date.today(), "state": code}))
    scores = member_scores([r["bioguide_id"] for r in current + former])
    pop = fetch(q.STATE_POPULATION, {"state": code})

    senators: dict[tuple[str, str], list[dict]] = {}
    for r in fetch(q.STATE_SENATE_VOTES, {"state": code}):
        senators.setdefault((r["survey"], r["variable"]), []).append({
            "bioguide_id": r["bioguide_id"], "name": r["name"], "party": r["party"], "date": r["vote_date"],
            "roll_call_id": r["roll_call_id"], "match": r["match_kind"], "position": r["position"],
            "sided_with": sided_with(r["position"], r["support_side"])})
    opinion = [{
        "survey": r["survey"], "item": r["variable"], "question": r["question"], "kind": r["kind"],
        "source": {"organization": r["organization"], "title": r["title"], "fielded": r["fielded"]},
        "support_pct": round(100 * r["support"], 1),
        "range_pct": [round(100 * r["support_low"], 1), round(100 * r["support_high"], 1)],
        "majority": r["majority"], "respondents": r["respondents"], "area_note": r["area_note"],
        "senate_votes": [{**s, "agreement": side_agreement(s["sided_with"], r["majority"])}
                         for s in senators.get((r["survey"], r["variable"]), [])],
    } for r in fetch(q.STATE_OPINION, {"state": code})]
    response.headers["Cache-Control"] = CACHE
    return {
        "state": code,
        "name": STATE_NAME.get(code, code),
        "residents": pop[0]["population"] if pop else None,
        "members": [{**member_summary(r), "scores": scores.get(r["bioguide_id"], [])} for r in current],
        "former": [{**member_summary(r), "left_office": r["end_date"], "scores": scores.get(r["bioguide_id"], [])}
                   for r in former],
        "opinion": opinion,
    }
