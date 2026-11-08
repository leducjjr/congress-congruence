"""SQL for the API. Every query is read-only."""

from datetime import date

BILL_LABEL = {
    "hr": ("H.R.", "house-bill"), "s": ("S.", "senate-bill"),
    "hres": ("H.Res.", "house-resolution"), "sres": ("S.Res.", "senate-resolution"),
    "hjres": ("H.J.Res.", "house-joint-resolution"), "sjres": ("S.J.Res.", "senate-joint-resolution"),
    "hconres": ("H.Con.Res.", "house-concurrent-resolution"),
    "sconres": ("S.Con.Res.", "senate-concurrent-resolution"),
}


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def seat_label(state: str, district: int | None, chamber: str) -> str:
    if chamber == "senate":
        return state
    if district is None or district < 0:
        return state
    return f"{state}-AL" if district == 0 else f"{state}-{district}"


def bill_info(congress: int | None, bill_type: str | None, number: int | None) -> dict | None:
    if not (congress and bill_type and number) or bill_type not in BILL_LABEL:
        return None
    label, path = BILL_LABEL[bill_type]
    return {"label": f"{label} {number}",
            "url": f"https://www.congress.gov/bill/{ordinal(congress)}-congress/{path}/{number}"}


def official_vote_url(chamber: str, congress: int, session: int, roll: int, vote_date: date) -> str:
    if chamber == "house":
        return f"https://clerk.house.gov/Votes/{vote_date.year}{roll:03d}"   # e.g. /Votes/2025069
    return ("https://www.senate.gov/legislative/LIS/roll_call_votes/"
            f"vote{congress}{session}/vote_{congress}_{session}_{roll:05d}.htm")


# A member's party for a vote is the party of the term covering the vote date;
# caucus is used where it differs (independents who caucus with a party).
CURRENT_MEMBERS = """
select distinct on (t.bioguide_id)
       t.bioguide_id, coalesce(m.official_full, m.first_name || ' ' || m.last_name) as name,
       m.last_name, t.chamber, t.state, t.district, t.party, t.caucus
  from core.term t join core.member m using (bioguide_id)
 where %(on)s between t.start_date and t.end_date
   and (%(state)s::text is null or t.state = %(state)s)
   and (%(chamber)s::text is null or t.chamber = %(chamber)s)
 order by t.bioguide_id, t.start_date desc
"""

MEMBER = """
select m.bioguide_id, coalesce(m.official_full, m.first_name || ' ' || m.last_name) as name,
       t.chamber, t.state, t.district, t.party, t.caucus, t.start_date, t.end_date,
       (%(on)s between t.start_date and t.end_date) as serving
  from core.member m join core.term t using (bioguide_id)
 where m.bioguide_id = %(id)s
 order by t.start_date desc
 limit 1
"""

# Attendance and party alignment for one member in one Congress and chamber.
# Party majority on a vote = the position (yea/nay) most members of that party took.
# Ties and votes where the member's party is unknown are left out of alignment.
STATS = """
with mine as (
    select v.roll_call_id, v.position, r.vote_date,
           (select coalesce(t.caucus, t.party) from core.term t
             where t.bioguide_id = v.bioguide_id and t.chamber = r.chamber
               and r.vote_date between t.start_date and t.end_date
             order by t.start_date desc limit 1) as grp
      from core.member_vote v join core.roll_call r using (roll_call_id)
     where v.bioguide_id = %(id)s and r.congress = %(congress)s and r.chamber = %(chamber)s
),
majority as (
    select v.roll_call_id, coalesce(t.caucus, t.party) as grp,
           case when count(*) filter (where v.position = 'yea') > count(*) filter (where v.position = 'nay') then 'yea'
                when count(*) filter (where v.position = 'nay') > count(*) filter (where v.position = 'yea') then 'nay'
           end as position
      from core.member_vote v
      join core.roll_call r using (roll_call_id)
      join core.term t on t.bioguide_id = v.bioguide_id and t.chamber = r.chamber
                      and r.vote_date between t.start_date and t.end_date
     where v.roll_call_id in (select roll_call_id from mine)
     group by 1, 2
)
select count(*)                                                         as votes_total,
       count(*) filter (where mine.position = 'not_voting')             as votes_missed,
       count(*) filter (where mine.position in ('yea', 'nay')
                          and majority.position is not null)            as party_votes,
       count(*) filter (where mine.position = majority.position)        as with_party,
       min(mine.vote_date)                                              as first_vote,
       max(mine.vote_date)                                              as last_vote
  from mine left join majority on majority.roll_call_id = mine.roll_call_id and majority.grp = mine.grp
"""

RECENT_VOTES = """
select r.roll_call_id, r.chamber, r.congress, r.session, r.roll_number, r.vote_date,
       r.question, r.description, r.result, r.bill_congress, r.bill_type, r.bill_number,
       r.yea_total, r.nay_total, r.source, v.position, v.raw_position
  from core.member_vote v join core.roll_call r using (roll_call_id)
 where v.bioguide_id = %(id)s
 order by r.vote_date desc, r.chamber, r.roll_number desc
 limit %(limit)s
"""

FRESHNESS = """
select chamber, source, count(*) as votes, max(vote_date) as latest_vote
  from core.roll_call group by chamber, source order by chamber, source
"""

LAST_RUNS = """
select distinct on (job) job, status, finished_at
  from core.ingest_run where status = 'succeeded'
 order by job, run_id desc
"""

# Every surveyed vote the member cast, with the estimated opinion where they
# represented constituents ON THE DAY OF THAT VOTE (their state as a senator, their
# district as a representative). Using the seat at vote time matters across Congresses:
# districts are redrawn and members move between chambers.
OPINION = """
select si.survey, si.variable, si.question, coalesce(siv.reader_note, si.note) as note,
       r.roll_call_id, r.chamber, r.congress, r.session, r.roll_number, r.vote_date,
       r.question as vote_question, r.result, r.yea_total, r.nay_total,
       mv.position,
       t.state, t.district as seat_district,
       oe.support, oe.support_low, oe.support_high, oe.majority, oe.respondents, oe.district
  from core.member_vote mv
  join core.survey_item_vote siv on siv.roll_call_id = mv.roll_call_id
  join core.survey_item si on si.survey = siv.survey and si.variable = siv.variable
  join core.roll_call r on r.roll_call_id = mv.roll_call_id
  join lateral (
        select state, district from core.term t
         where t.bioguide_id = mv.bioguide_id and t.chamber = r.chamber
           and r.vote_date between t.start_date and t.end_date
         order by t.start_date desc limit 1) t on true
  join core.opinion_estimate oe on oe.survey = si.survey and oe.variable = si.variable
                               and oe.state = t.state
                               and ((r.chamber = 'senate' and oe.district is null)
                                 or (r.chamber = 'house' and oe.district = t.district))
 where mv.bioguide_id = %(id)s
 order by r.vote_date, si.variable
"""

# Where each survey comes from (title, when, size, links).
SURVEYS = """
select survey, title, fielded, respondents, dataset_url, guide_url, about_url
  from core.survey order by survey
"""
