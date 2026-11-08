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
select chamber, source, count(*) as votes, min(vote_date) as first_vote, max(vote_date) as latest_vote,
       min(congress) as first_congress, max(congress) as latest_congress
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
       mv.position, siv.support_side, siv.match_kind,
       t.state, t.district as seat_district,
       oe.support, oe.support_low, oe.support_high, oe.majority, oe.respondents, oe.district,
       oe.source_url,
       ap.population as residents
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
  left join core.area_population ap on ap.congress = r.congress and ap.state = t.state
                                   and ap.district is not distinct from
                                       (case when r.chamber = 'house' then t.district end)
 where mv.bioguide_id = %(id)s
 order by r.vote_date, si.variable
"""

# Where each survey comes from (title, when, size, links).
SURVEYS = """
select survey, title, fielded, respondents, dataset_url, guide_url, about_url,
       coalesce(organization, survey) as organization, description
  from core.survey order by survey
"""


# Residents of an area as drawn for a given Congress (district null = whole state).
AREA_POPULATION = """
select population, source, congress from core.area_population
 where congress = %(congress)s and state = %(state)s and district is not distinct from %(district)s
"""

# A whole state's residents don't depend on district lines: use the most recent figure.
STATE_POPULATION = """
select population, source, congress from core.area_population
 where state = %(state)s and district is null
 order by congress desc limit 1
"""

# For context: the average House district, and the smallest and largest states (50 states only).
POPULATION_CONTEXT = """
select (select round(avg(population)) from core.area_population
         where congress = %(congress)s and district is not null and state not in ('DC', 'PR')) as avg_district,
       (select state from core.area_population where congress = %(congress)s and district is null
           and state not in ('DC', 'PR') order by population limit 1) as smallest_state,
       (select min(population) from core.area_population where congress = %(congress)s and district is null
           and state not in ('DC', 'PR')) as smallest_pop,
       (select state from core.area_population where congress = %(congress)s and district is null
           and state not in ('DC', 'PR') order by population desc limit 1) as largest_state,
       (select max(population) from core.area_population where congress = %(congress)s and district is null
           and state not in ('DC', 'PR')) as largest_pop
"""

# Every survey loaded, for the Sources page, with how many of its questions are compared with votes.
SURVEY_LIST = """
select s.survey, s.title, s.fielded, s.respondents, s.dataset_url, s.guide_url, s.about_url,
       coalesce(s.organization, s.survey) as organization, s.description,
       (select count(distinct v.variable) from core.survey_item_vote v where v.survey = s.survey) as items
  from core.survey s
 order by coalesce(s.organization, s.survey), s.survey desc
"""

# ---------------------------------------------------------------- text search (votes, survey questions)
# %(tsq)s is a to_tsquery string built by app.build_tsquery from letters and digits only.

# Words a vote can be found by: its title and question, the bill number, and (once loaded from
# Congress.gov) the bill's official title, policy area and subject tags.
VOTE_DOC = """to_tsvector('english', coalesce(r.description, '') || ' ' || coalesce(r.question, '') || ' ' ||
           coalesce(r.bill_type || ' ' || r.bill_number || ' ' || r.bill_type || r.bill_number, '') || ' ' ||
           coalesce(b.title, '') || ' ' || coalesce(b.policy_area, '') || ' ' || coalesce(bs.subjects, ''))"""

# The same without subject tags: votes matching here are listed before those found only by a tag.
VOTE_TITLE_DOC = """to_tsvector('english', coalesce(r.description, '') || ' ' || coalesce(r.question, '') || ' ' ||
           coalesce(r.bill_type || ' ' || r.bill_number || ' ' || r.bill_type || r.bill_number, '') || ' ' ||
           coalesce(b.title, '') || ' ' || coalesce(b.policy_area, ''))"""

VOTE_BILL_JOIN = """
  left join core.bill b on b.congress = coalesce(r.bill_congress, r.congress)
                       and b.bill_type = r.bill_type and b.bill_number = r.bill_number
  left join lateral (select string_agg(s.subject, ' | ' order by s.subject) as subjects
                       from core.bill_subject s
                      where s.congress = b.congress and s.bill_type = b.bill_type
                        and s.bill_number = b.bill_number) bs on true"""

VOTE_SEARCH = f"""
select r.roll_call_id, r.chamber, r.congress, r.session, r.roll_number, r.vote_date, r.question,
       r.description, r.result, r.yea_total, r.nay_total, r.present_total, r.not_voting_total,
       r.bill_congress, r.bill_type, r.bill_number, r.amendment_number,
       b.title as bill_title, b.policy_area, bs.subjects,
       -- Long titles (e.g. dozens of nominations confirmed together) are shown as the part that
       -- matched; [[ ]] mark the matching words.
       case when length(r.description) > 220 then
            ts_headline('english', r.description, to_tsquery('english', %(tsq)s),
                        'MaxFragments=2, MinWords=8, MaxWords=24, StartSel=[[, StopSel=]], FragmentDelimiter=" … "')
       end as snippet,
       {VOTE_TITLE_DOC} @@ to_tsquery('english', %(tsq)s) as title_match,
       count(*) over () as total
  from core.roll_call r{VOTE_BILL_JOIN}
 where {VOTE_DOC} @@ to_tsquery('english', %(tsq)s)
   and (%(chamber)s::text is null or r.chamber = %(chamber)s)
 order by title_match desc, r.vote_date desc, r.chamber, r.roll_number desc
 limit %(limit)s
"""

# How each party voted, by the party of the term covering the vote date.
VOTE_PARTY_SPLIT = """
select v.roll_call_id, coalesce(t.caucus, t.party) as party, v.position, count(*) as n
  from core.member_vote v
  join core.roll_call r using (roll_call_id)
  cross join lateral (select t.party, t.caucus from core.term t
                       where t.bioguide_id = v.bioguide_id and t.chamber = r.chamber
                         and r.vote_date between t.start_date and t.end_date
                       order by t.start_date desc limit 1) t
 where v.roll_call_id = any(%(ids)s)
 group by 1, 2, 3
"""

# Which of these votes a survey question is compared with.
VOTE_SURVEYED = """
select siv.roll_call_id, siv.survey, siv.variable, siv.match_kind, si.question
  from core.survey_item_vote siv join core.survey_item si using (survey, variable)
 where siv.roll_call_id = any(%(ids)s)
"""

# How particular members voted on particular votes ("your members").
MEMBER_POSITIONS = """
select v.roll_call_id, v.bioguide_id, v.position,
       coalesce(m.official_full, m.first_name || ' ' || m.last_name) as name, m.last_name
  from core.member_vote v join core.member m using (bioguide_id)
 where v.roll_call_id = any(%(ids)s) and v.bioguide_id = any(%(members)s)
"""

QUESTION_SEARCH = """
select si.survey, si.variable, si.question, si.note, s.title, s.fielded,
       coalesce(s.organization, s.survey) as organization, s.guide_url,
       count(*) over () as total
  from core.survey_item si join core.survey s using (survey)
  -- A question can also be found by the official title and main topic (policy area) of the bills
  -- it's compared with. Not by their full subject lists: a large bill such as the annual defense
  -- bill carries hundreds of subjects and would match almost any search.
  left join lateral (select string_agg(coalesce(b.title, '') || ' ' || coalesce(b.policy_area, ''), ' ') as words
                       from core.survey_item_vote siv
                       join core.roll_call r using (roll_call_id)
                       join core.bill b on b.congress = coalesce(r.bill_congress, r.congress)
                                       and b.bill_type = r.bill_type and b.bill_number = r.bill_number
                      where siv.survey = si.survey and siv.variable = si.variable) tags on true
 where to_tsvector('english', si.question || ' ' || coalesce(si.survey_label, '') || ' ' || coalesce(si.note, '')
                   || ' ' || coalesce(tags.words, ''))
       @@ to_tsquery('english', %(tsq)s)
   and exists (select 1 from core.survey_item_vote v where v.survey = si.survey and v.variable = si.variable)
 order by si.survey desc, si.variable
 limit %(limit)s
"""

# For each matching question and chamber: the vote it's compared with, and how many members voted
# with or against a clear majority where they live, or where it was too close to call.
QUESTION_TALLY = """
with links as (
    select siv.survey, siv.variable, siv.chamber, siv.roll_call_id, siv.support_side, siv.match_kind,
           r.vote_date, r.question, r.result, r.yea_total, r.nay_total, r.congress, r.session, r.roll_number
      from core.survey_item_vote siv join core.roll_call r using (roll_call_id)
     where (siv.survey || '|' || siv.variable) = any(%(keys)s)
),
judged as (
    select l.*, v.bioguide_id,
           case when v.position not in ('yea', 'nay') then 'did_not_vote'
                when oe.majority is null then 'not_surveyed'
                when oe.majority = 'too_close' then 'too_close'
                when (v.position = l.support_side) = (oe.majority = 'support') then 'with'
                else 'against' end as agreement
      from links l
      join core.member_vote v using (roll_call_id)
      cross join lateral (select t.state, t.district from core.term t
                           where t.bioguide_id = v.bioguide_id and t.chamber = l.chamber
                             and l.vote_date between t.start_date and t.end_date
                           order by t.start_date desc limit 1) t
      left join core.opinion_estimate oe
             on oe.survey = l.survey and oe.variable = l.variable and oe.state = t.state
            and ((l.chamber = 'senate' and oe.district is null)
                 or (l.chamber = 'house' and oe.district = t.district))
)
select survey, variable, chamber, roll_call_id, support_side, match_kind, vote_date, question, result,
       yea_total, nay_total, congress, session, roll_number,
       count(*) filter (where agreement = 'with')         as with_majority,
       count(*) filter (where agreement = 'against')      as against_majority,
       count(*) filter (where agreement = 'too_close')    as too_close,
       count(*) filter (where agreement = 'not_surveyed') as not_surveyed,
       count(*) filter (where agreement = 'did_not_vote') as did_not_vote
  from judged
 group by survey, variable, chamber, roll_call_id, support_side, match_kind, vote_date, question, result,
          yea_total, nay_total, congress, session, roll_number
"""

# Spread of estimated support across the states (and districts) surveyed, per question.
QUESTION_SPREAD = """
select survey, variable, district is null as statewide, count(*) as areas,
       min(support) as lowest, max(support) as highest,
       count(*) filter (where majority = 'support') as support_areas,
       count(*) filter (where majority = 'oppose') as oppose_areas,
       count(*) filter (where majority = 'too_close') as too_close_areas
  from core.opinion_estimate
 where (survey || '|' || variable) = any(%(keys)s)
 group by survey, variable, district is null
"""


# ---------------------------------------------------------------- Surveyed votes page

QUESTION_COLUMNS = """si.survey, si.variable, si.question, si.note, s.title, s.fielded,
       coalesce(s.organization, s.survey) as organization, s.guide_url"""

# Every question compared with at least one vote: by organization, newest survey first.
QUESTION_LIST = f"""
select {QUESTION_COLUMNS}
  from core.survey_item si join core.survey s using (survey)
 where exists (select 1 from core.survey_item_vote v where v.survey = si.survey and v.variable = si.variable)
 order by coalesce(s.organization, s.survey), si.survey desc, si.variable
"""

QUESTION_ONE = f"""
select {QUESTION_COLUMNS}
  from core.survey_item si join core.survey s using (survey)
 where si.survey = %(survey)s and si.variable = %(item)s
"""

# Every member's vote on each vote linked to the question, with the estimate for the area they
# represented on the vote date (state for senators, district for representatives).
QUESTION_MEMBERS = """
select siv.roll_call_id, r.chamber, siv.support_side, v.bioguide_id, v.position,
       coalesce(m.official_full, m.first_name || ' ' || m.last_name) as name,
       t.state, t.district, coalesce(t.caucus, t.party) as party,
       oe.support, oe.support_low, oe.support_high, oe.majority, oe.respondents
  from core.survey_item_vote siv
  join core.roll_call r using (roll_call_id)
  join core.member_vote v using (roll_call_id)
  join core.member m using (bioguide_id)
  cross join lateral (select t.state, t.district, t.party, t.caucus from core.term t
                       where t.bioguide_id = v.bioguide_id and t.chamber = r.chamber
                         and r.vote_date between t.start_date and t.end_date
                       order by t.start_date desc limit 1) t
  left join core.opinion_estimate oe
         on oe.survey = siv.survey and oe.variable = siv.variable and oe.state = t.state
        and ((r.chamber = 'senate' and oe.district is null)
             or (r.chamber = 'house' and oe.district = t.district))
 where siv.survey = %(survey)s and siv.variable = %(item)s
"""
