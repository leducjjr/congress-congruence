"""API for the historical section (/history/): the 1st to 92nd Congresses, 1789-1972, from the history
schema (sql/012_history.sql). Kept apart from the main endpoints, as the data is.

    /v1/history/congresses                                  every Congress loaded, with counts
    /v1/history/congresses/{n}/numbers?chamber=             each member's figures (By the numbers)
    /v1/history/congresses/{n}/votes?chamber=&q=&offset=    the roll calls
    /v1/history/votes/{chamber}/{congress}/{roll}           one roll call: how each member voted
    /v1/history/members/{id}                                a member's Congresses (id: Bioguide or ICPSR)
    /v1/history/members/{id}/votes?congress=&chamber=       their votes in one Congress
"""

import re
from collections import Counter

from fastapi import APIRouter, HTTPException, Query, Response

from .titles import _title_words, bill_label, tidy

router = APIRouter(prefix="/v1/history")
CACHE = "public, max-age=3600"        # the historical record changes only when it's reloaded
CHAMBER = Query("house", pattern="^(house|senate)$")
CAST = {"1": "yea", "2": "paired_yea", "3": "announced_yea", "4": "announced_nay", "5": "paired_nay",
        "6": "nay", "7": "present", "8": "present", "9": "not_voting"}
CAST_LABEL = {"1": "Yea", "2": "Paired Yea", "3": "Announced Yea", "4": "Announced Nay", "5": "Paired Nay",
              "6": "Nay", "7": "Present", "8": "Present", "9": "Not Voting"}


def fetch(sql, params=None):
    from .app import fetch as main_fetch            # the main API's connection pool
    return main_fetch(sql, params)


def years(congress: int) -> str:
    start = 1787 + 2 * congress
    return f"{start}–{start + 2}"


def display_name(voteview_name: str) -> str:
    """Voteview writes "LINCOLN, Abraham" or "ADAMS, John Quincy"; show "Abraham Lincoln"."""
    last, _, first = voteview_name.partition(",")
    last = _title_words(last.strip().lower())
    last = last[:1].upper() + last[1:]                 # "Van Buren", "De Priest"
    first = first.strip()
    suffix = ""
    m = re.search(r"\s*\((Jr\.?|Sr\.?|II|III|IV)\)\s*$", first, re.I)
    if m:
        first, suffix = first[:m.start()], ", " + m.group(1)
    return f"{first} {last}{suffix}".strip()


def pct(n, d):
    return round(100 * n / d, 1) if d else None


def voteview_url(chamber: str, congress: int, roll: int) -> str:
    return f"https://voteview.com/rollcall/R{'H' if chamber == 'house' else 'S'}{congress:03d}{roll:04d}"


def congress_or_404(n: int) -> None:
    if not fetch("select 1 from history.load_run where congress = %(n)s", {"n": n}):
        raise HTTPException(404, "That Congress isn't in the historical record (1st to 92nd)")


@router.get("/congresses")
def congresses(response: Response):
    rows = fetch("""
        select l.congress, l.chamber, l.roll_calls, l.members, l.totals_mismatched,
               min(r.vote_date) as first_vote, max(r.vote_date) as last_vote
          from history.load_run l
          left join history.roll_call r on r.chamber = l.chamber and r.congress = l.congress
         group by 1, 2, 3, 4, 5 order by 1 desc, 2""")
    out = {}
    for r in rows:
        c = out.setdefault(r["congress"], {"congress": r["congress"], "years": years(r["congress"])})
        c[r["chamber"]] = {"roll_calls": r["roll_calls"], "members": r["members"],
                           "totals_mismatched": r["totals_mismatched"],
                           "first_vote": r["first_vote"], "last_vote": r["last_vote"]}
    response.headers["Cache-Control"] = CACHE
    return {"congresses": list(out.values())}


@router.get("/congresses/{congress}/numbers")
def numbers(congress: int, response: Response, chamber: str = CHAMBER):
    congress_or_404(congress)
    rows = fetch("""
        select mc.icpsr, m.bioguide_id, m.name, mc.state, mc.district, mc.party_code, p.name as party,
               mc.votes_total, mc.yea, mc.nay, mc.present, mc.not_voting, mc.party_votes, mc.with_party,
               mc.first_vote, mc.last_vote,
               exists (select 1 from core.term t where t.bioguide_id = m.bioguide_id
                        and t.end_date > '1973-01-03') as on_main_site
          from history.member_congress mc
          join history.member m using (icpsr)
          left join history.party p using (party_code)
         where mc.congress = %(c)s and mc.chamber = %(ch)s and mc.votes_total > 0
         order by mc.state, mc.district, m.name""", {"c": congress, "ch": chamber})
    members = [{
        "id": r["bioguide_id"] or str(r["icpsr"]), "bioguide_id": r["bioguide_id"], "icpsr": r["icpsr"],
        "name": display_name(r["name"]), "state": r["state"],
        "district": r["district"] if chamber == "house" and r["district"] else None,
        "party": r["party"] or (f"Party code {r['party_code']}" if r["party_code"] is not None else None),
        "votes_total": r["votes_total"], "yea": r["yea"], "nay": r["nay"], "present": r["present"],
        "not_voting": r["not_voting"], "yea_pct": pct(r["yea"], r["votes_total"]),
        "nay_pct": pct(r["nay"], r["votes_total"]), "missed_pct": pct(r["not_voting"], r["votes_total"]),
        "party_votes": r["party_votes"], "with_party": r["with_party"],
        "with_party_pct": pct(r["with_party"], r["party_votes"]),
        "first_vote": r["first_vote"], "last_vote": r["last_vote"], "on_main_site": r["on_main_site"],
    } for r in rows]
    response.headers["Cache-Control"] = CACHE
    return {"congress": congress, "years": years(congress), "chamber": chamber, "members": members,
            "parties": [{"party": p, "members": n} for p, n in Counter(m["party"] for m in members).most_common()]}


@router.get("/congresses/{congress}/votes")
def votes(congress: int, response: Response, chamber: str = CHAMBER, q: str | None = None,
          offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)):
    congress_or_404(congress)
    where, params = "", {"c": congress, "ch": chamber, "offset": offset, "limit": limit}
    if q and q.strip():
        where = "and (description ilike %(q)s or question ilike %(q)s or bill_number ilike %(q)s)"
        params["q"] = f"%{q.strip()}%"
    rows = fetch(f"""
        select rollnumber, session, vote_date, yea_count, nay_count, result, question, description,
               bill_number, totals_match, count(*) over () as total
          from history.roll_call where congress = %(c)s and chamber = %(ch)s {where}
         order by rollnumber offset %(offset)s limit %(limit)s""", params)
    response.headers["Cache-Control"] = CACHE
    return {"congress": congress, "chamber": chamber, "total": rows[0]["total"] if rows else 0,
            "votes": [vote_row(chamber, congress, r) for r in rows]}


def vote_row(chamber, congress, r):
    return {"roll": r["rollnumber"], "session": r["session"], "date": r["vote_date"],
            "yea": r["yea_count"], "nay": r["nay_count"], "result": r["result"],
            "question": tidy(r["question"]), "description": tidy(r["description"]),
            "bill": bill_label(r["bill_number"]), "totals_match": r["totals_match"],
            "voteview_url": voteview_url(chamber, congress, r["rollnumber"])}


@router.get("/votes/{chamber}/{congress}/{roll}")
def vote(chamber: str, congress: int, roll: int, response: Response):
    if chamber not in ("house", "senate"):
        raise HTTPException(404)
    rc = fetch("""select * from history.roll_call where chamber = %(ch)s and congress = %(c)s
                  and rollnumber = %(r)s""", {"ch": chamber, "c": congress, "r": roll})
    if not rc:
        raise HTTPException(404, "No such roll call")
    rows = fetch("""
        select m.bioguide_id, mc.icpsr, m.name, mc.state, mc.district, p.name as party,
               substr(mc.casts, %(r)s, 1) as cast
          from history.member_congress mc join history.member m using (icpsr)
          left join history.party p using (party_code)
         where mc.chamber = %(ch)s and mc.congress = %(c)s and substr(mc.casts, %(r)s, 1) not in ('', '0')
         order by mc.state, mc.district, m.name""", {"ch": chamber, "c": congress, "r": roll})
    by_party = {}
    for r in rows:
        t = by_party.setdefault(r["party"] or "Unknown", Counter())
        t[CAST[r["cast"]]] += 1
    response.headers["Cache-Control"] = CACHE
    return {**vote_row(chamber, congress, rc[0]), "chamber": chamber, "congress": congress,
            "by_party": [{"party": p, "yea": t["yea"], "nay": t["nay"]} for p, t in
                         sorted(by_party.items(), key=lambda x: -sum(x[1].values()))],
            "members": [{"id": r["bioguide_id"] or str(r["icpsr"]), "name": display_name(r["name"]),
                         "state": r["state"], "district": r["district"] if chamber == "house" and r["district"] else None,
                         "party": r["party"], "position": CAST[r["cast"]], "position_detail": CAST_LABEL[r["cast"]]}
                        for r in rows]}


def member_rows(member_id: str):
    if re.fullmatch(r"[A-Z]\d{6}", member_id):
        where, p = "m.bioguide_id = %(id)s", {"id": member_id}
    elif member_id.isdigit():
        where, p = "m.icpsr = %(id)s", {"id": int(member_id)}
    else:
        raise HTTPException(400, "A member ID looks like L000313 or a Voteview number")
    rows = fetch(f"""
        select mc.chamber, mc.congress, mc.icpsr, m.bioguide_id, m.name, m.born, m.died, mc.state, mc.district,
               p.name as party, mc.votes_total, mc.yea, mc.nay, mc.present, mc.not_voting, mc.party_votes,
               mc.with_party, mc.first_vote, mc.last_vote, mc.casts
          from history.member_congress mc join history.member m using (icpsr)
          left join history.party p using (party_code)
         where {where} and mc.votes_total > 0 order by mc.congress, mc.chamber""", p)
    if not rows:
        raise HTTPException(404, "No member with that ID in the historical record")
    return rows


@router.get("/members/{member_id}")
def member(member_id: str, response: Response):
    rows = member_rows(member_id)
    first = rows[-1]
    bioguide = next((r["bioguide_id"] for r in rows if r["bioguide_id"]), None)
    later = bool(bioguide and fetch("select 1 from core.term where bioguide_id = %(b)s and end_date > '1973-01-03'",
                                    {"b": bioguide}))
    total = sum(r["votes_total"] for r in rows)
    response.headers["Cache-Control"] = CACHE
    return {"id": member_id, "bioguide_id": bioguide, "name": display_name(first["name"]),
            "born": first["born"], "died": first["died"], "on_main_site": later,
            "votes_total": total, "not_voting": sum(r["not_voting"] for r in rows),
            "missed_pct": pct(sum(r["not_voting"] for r in rows), total),
            "congresses": [{
                "congress": r["congress"], "years": years(r["congress"]), "chamber": r["chamber"],
                "state": r["state"], "district": r["district"] if r["chamber"] == "house" and r["district"] else None,
                "party": r["party"], "votes_total": r["votes_total"], "yea": r["yea"], "nay": r["nay"],
                "present": r["present"], "not_voting": r["not_voting"],
                "missed_pct": pct(r["not_voting"], r["votes_total"]),
                "with_party_pct": pct(r["with_party"], r["party_votes"]),
                "first_vote": r["first_vote"], "last_vote": r["last_vote"]} for r in rows]}


@router.get("/members/{member_id}/votes")
def member_votes(member_id: str, congress: int, response: Response, chamber: str = CHAMBER):
    rows = [r for r in member_rows(member_id) if r["congress"] == congress and r["chamber"] == chamber]
    if not rows:
        raise HTTPException(404, "They didn't serve in that chamber in that Congress")
    rolls = {r["rollnumber"]: r for r in fetch(
        "select * from history.roll_call where congress = %(c)s and chamber = %(ch)s",
        {"c": congress, "ch": chamber})}
    out = []
    for row in rows:
        for i, c in enumerate(row["casts"], start=1):
            if c != "0" and i in rolls:
                out.append({**vote_row(chamber, congress, rolls[i]), "position": CAST[c], "position_detail": CAST_LABEL[c]})
    out.sort(key=lambda v: v["roll"])
    response.headers["Cache-Control"] = CACHE
    return {"congress": congress, "chamber": chamber, "votes": out}
