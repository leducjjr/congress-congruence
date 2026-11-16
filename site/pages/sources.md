---
title: Sources
description: Where every voting record, survey and population figure on this site comes from, how often it is updated, and links to the originals.
---
# Sources

<p class="lede">Everything on this site comes from public records and published surveys. This page
lists each source, what we take from it, how often we check it, and where to find the original.</p>

<p class="coverage" data-coverage></p>

[TOC]

## Voting records

### House of Representatives {#house}

**Source:** the Office of the Clerk of the U.S. House, which publishes an official record of every
roll-call vote: [clerk.house.gov/Votes](https://clerk.house.gov/Votes).

**What we use:** for each vote, the question, the result, the date, the bill, and how each
representative voted (Yea, Nay, Present or Not Voting).

**How often:** checked every 2 hours. Each vote is checked before it is stored: every member's vote
must add up to the Clerk's published totals.

**Earlier votes:** the Clerk's files from 2003 on. The Clerk's files before 2003 name representatives
without the ID that matches a vote to a member, and there are none before 1990, so House votes from
1973 to 2002 come from [Voteview](https://voteview.com), which has the IDs. A vote from before 1990
links to its Voteview page, since the Clerk's site has none. Their totals match the
Congressional Research Service's published counts. In 1993–94, delegates could vote in the Committee
of the Whole; their votes are shown, but as the official totals do, those totals leave them out.

### Senate {#senate}

**Official source:** the U.S. Senate's roll-call records:
[senate.gov](https://www.senate.gov/legislative/votes_new.htm).

**What we use:** the Senate's own roll-call files, the same official record, for each vote: the
question, the result, the date, the bill, and how each senator voted. Each vote is checked before it
is stored: every senator's vote must add up to the Senate's published totals.

**How often:** checked daily. We download them slowly, a few seconds apart, as the Senate's website
asks of automated downloads. Every Senate vote of 2026 so far has been loaded from the Senate's own
files this way, and each new vote is added the morning after it's posted.

**Votes not yet loaded from the Senate's files** come from [Voteview](https://voteview.com), a
long-running research project at UCLA that republishes every Senate and House roll call. Voteview can
be days to weeks behind the official record. When the Senate's own file for a vote is loaded, it
replaces the Voteview copy. Earlier Senate votes, from 1973, also come from Voteview; those before 1989,
when senate.gov's own records begin, link to their Voteview page. Voteview occasionally still lists a
senator who had left (resigned or died) as "not voting" while their successor votes; where the member
list shows they weren't serving that day, that entry is left out. Each vote on
this site says which record it came from, and the footer of every page shows how current each
chamber is.

**Paired and announced votes:** a senator who is absent can "pair" with one on the other side or
announce a position. These aren't counted in the official tally, so we treat them as not voting, as the
Senate does.

### The historical record, 1789–1972 {#historical-record}

**Source:** [Voteview](https://voteview.com), which has every recorded House and Senate vote from the
1st Congress in 1789, compiled from the official records of Congress.

**What we use:** for each vote, the question, the result, the date and how each member voted, plus
Voteview's list of who was a member when. These votes are shown in their own section,
[the historical record](history/), with each vote linked to its Voteview page. There were no surveys
of what people wanted back then, so these votes aren't compared with anything; they're there so you
can see a member's whole record.

**How often:** loaded once, in November 2026. Voteview's records this old rarely change.

### Members of Congress {#members}

**Source:** [congress-legislators](https://github.com/unitedstates/congress-legislators), a public
dataset of every member's terms, seats, parties and official IDs, maintained by volunteers and widely
used by news organizations and researchers.

**How often:** checked daily, so new members appear before their first vote.

**How we use it:** every vote is matched to the seat the member held **on the day of the vote**, so
redrawn districts, special elections and moves between the House and Senate are handled correctly.

**Corrections:** a few members who arrived by special election are listed as starting on the
Congress's opening day. Where an official record gives the real date, we use it, so time in office
isn't overstated. Each correction and its source is listed in
[the corrections file](https://github.com/leducjjr/congress-congruence/blob/main/config/term_corrections.yaml).

### Bills {#bills}

Bill names and links go to [Congress.gov](https://www.congress.gov/), the official site for federal
legislation, run by the Library of Congress.

**What we use:** for each bill with a recorded vote, its official title, its policy area and the
subject tags the Library of Congress assigns (for example, "Immigration status and procedures"), from
the [Congress.gov API](https://api.congress.gov/). Search uses them, so a search for a topic finds
bills whose names don't mention it.

**How often:** checked daily for bills with new votes, and every bill again each month, since subject
tags are added over time.

## Surveys of what people want {#surveys}

We compare votes with what people said in independent, published surveys. We use more than one survey
organization, and we **show each one separately**, never combined into a single score, so you can see
where they agree.

**Who was asked differs by source:** most surveys here ask all adults, because members of Congress
represent everyone where they live, not only voters; some ask registered voters only; ballot measures
are votes actually cast. Each source below says which, and so does every comparison on the site.

We only compare a vote with a survey question when both are about the same proposal. See
[Methods](methods.html) for how votes and questions are matched. Other surveys we've looked at, and why
each is or isn't used yet, are listed [below](sources.html#not-used).

### Cooperative Election Study {#cooperative-election-study}

**Who runs it:** a consortium of universities led by Harvard University and Tufts University, fielded by
YouGov. Its website is at [Tufts University](https://tischcollege.tufts.edu/ces) (formerly
cces.gov.harvard.edu); its data are published on [Harvard Dataverse](https://dataverse.harvard.edu/dataverse/cces).

**What it is:** one of the largest academic surveys of U.S. adults, run every year since 2006. Each
year it asks whether people support specific actions Congress has voted on.

**Who was asked:** adults (18 and over), whether or not they're registered to vote.

**What we use:** each person's state, House district and answers, with the survey's own weights.
House districts have only a few dozen respondents each, so we estimate each district's opinion with
help from statewide answers; see [Methods](methods.html#estimates-ces).

**Data:** published openly on [Harvard Dataverse](https://dataverse.harvard.edu/dataverse/cces).

**Loaded on this site:**

<div data-surveys="Cooperative Election Study"><p class="note">Loading the list…</p></div>

### Program for Public Consultation {#program-for-public-consultation}

**Who runs it:** the Program for Public Consultation at the University of Maryland's School of Public
Policy. [publicconsultation.org](https://publicconsultation.org/)

**What it is:** surveys in which people are given brief background on a proposal before saying whether
they favor or oppose it. Its 2026 "Common Ground in the Battlegrounds" series surveyed 11 competitive
states and 28 competitive House districts, with samples of several hundred to 2,000 people in each.
Respondents come from online panels and are weighted to Census figures.

**Who was asked:** adults (18 and over), whether or not they're registered to vote.

**What we use:** the published results for each state and district, taken from the questionnaires on
[vop.org](https://vop.org/battlegrounds-aggregate/), with each sample's size and margin of error.
Only members from the states and districts it surveyed get these comparisons.

**Loaded on this site:**

<div data-surveys="Program for Public Consultation"><p class="note">Loading the list…</p></div>

### Democracy Fund + UCLA Nationscape {#democracy-fund-ucla-nationscape}

**Who runs it:** the Democracy Fund Voter Study Group and UCLA.
[voterstudygroup.org/data/nationscape](https://www.voterstudygroup.org/data/nationscape)

**What it is:** a survey of about 6,250 people a week from July 2019 to February 2021, nearly half a
million interviews in all, conducted online and weighted to Census figures. Respondents said whether
they agree or disagree with specific policy proposals.

**Who was asked:** adults (18 and over), whether or not they're registered to vote.

**What we use:** the answers to the proposals Congress actually voted on, from the published data
files, pooled across the weeks each question was asked. Its size allows an estimate for nearly every
congressional district. Districts are as drawn for the 116th Congress (2019-2020), which the 117th
also used everywhere except North Carolina, so North Carolina's representatives are compared only on
votes from 2019-2020.

**Loaded on this site:**

<div data-surveys="Democracy Fund + UCLA Nationscape"><p class="note">Loading the list…</p></div>

### University of Texas / Texas Politics Project {#texas-politics-project}

**Who runs it:** the Texas Politics Project at the University of Texas at Austin, which polls registered
Texas voters several times a year, conducted online by YouGov.
[texaspolitics.utexas.edu](https://texaspolitics.utexas.edu/polling-data-archive)

**What it is:** about 1,200 registered Texas voters per poll, weighted to the state's voters. Most of its
questions are about Texas, but some ask about federal laws and actions.

**Who was asked:** registered voters only.

**What we use:** the published statewide results (the "topline" for each poll) for the few questions
that a Senate vote answers, with each poll's margin of error. "Neither" and "don't know" answers are
left out, as with every survey here. The polls cover Texas only, so only Texas's two senators get these
comparisons; House districts have too few respondents. Each question links to the poll's published
results.

**Data:** the project makes its results and data [available for public use](https://texaspolitics.utexas.edu/polling-data-archive).

**Loaded on this site:**

<div data-surveys="Texas Politics Project"><p class="note">Loading the list…</p></div>

### University of New Hampshire Survey Center {#unh-survey-center}

**Who runs it:** the Survey Center at the University of New Hampshire, which runs the Granite State Poll
(New Hampshire), the Pine Tree State Poll (Maine), the Green Mountain State Poll (Vermont) and the Bay
State Poll (Massachusetts). [cola.unh.edu/unh-survey-center](https://cola.unh.edu/unh-survey-center)

**What it is:** online polls of each state's adults, drawn from panels recruited at random by phone,
text and mail, and weighted to Census figures and the state's 2024 results. Samples run from about 700
to 2,200 people.

**Who was asked:** adults (18 and over), whether or not they're registered to vote.

**What we use:** the published statewide results for the few questions that a vote in Congress answers,
with each poll's margin of error, widened by the design effect each poll reports. "Neutral" and "don't
know" answers are left out. Results are statewide, so they're compared with each state's two senators,
and with Vermont's one House member (an at-large seat covering the whole state); never with members for
a single district. Each question links to its poll's published results.

**Data:** the polls and their full results are published openly in the
[University of New Hampshire Scholars' Repository](https://scholars.unh.edu/survey_center_polls/).

**Loaded on this site:**

<div data-surveys="UNH Survey Center"><p class="note">Loading the list…</p></div>

## State ballot measures {#state-ballot-measures}

**What they are:** questions a state's voters decided themselves on the ballot, such as a
constitutional amendment. These aren't surveys: they are certified counts of votes actually cast, so
there is no sample and no margin of error.

**Who was asked:** voters themselves: these are the votes actually cast, not a survey.

**What we use:** each measure's certified statewide Yes and No totals, as compiled by
[Ballotpedia](https://ballotpedia.org/2024_ballot_measure_election_results), with a link to each
measure's own page. A statewide result is compared only with members who represent the whole state:
senators, and the representative of a state with a single House seat. Representatives of states with
several districts aren't compared, because a statewide result doesn't say what their own district voted.

**How they're shown:** no ballot measure asks exactly what a bill in Congress does, so every
comparison is marked as a **related vote** and none is counted in a member's score. For example,
several states amended their constitutions in 2024 to say only U.S. citizens may vote; the SAVE
America Act in Congress would also require documents proving citizenship to register. Measures with
no matching vote in Congress (for example on abortion or the minimum wage) are left out.

**Loaded on this site:**

<div data-surveys="State ballot measures"><p class="note">Loading the list…</p></div>

## Population {#population}

**Source:** the Census Bureau's American Community Survey, 1-year estimates for every state and House
district, from [api.census.gov](https://www.census.gov/data/developers.html):

- **Residents:** total population (table [B01003](https://data.census.gov/table/ACSDT1Y2025.B01003)).
- **U.S. citizens:** residents minus those who are not U.S. citizens (table
  [B05001](https://data.census.gov/table/ACSDT1Y2025.B05001), citizenship status).
- **Citizens 18 and over:** the citizen voting-age population (table
  [B29001](https://data.census.gov/table/ACSDT1Y2025.B29001)).

**Years:** the 2025 figures for the 119th Congress's districts (2025–26) and the 2023 figures for the
118th's (2023–24).

**How we use it:** to show how many people each member represents, how many of them are U.S. citizens
and citizens 18 and over, and how many a survey reached. Each year's figures are matched to the district
lines in use at the time. These are the Census Bureau's own estimates, shown as published. Puerto Rico's
citizenship figures are in separate tables and aren't shown.

**How often:** a new year's figures are released each September and loaded automatically.

## Other surveys: their status {#not-used}

Why isn't a particular survey here? A survey can be used only if it asks people
about a **specific proposal Congress voted on**, has **enough people in each state or district** to say
what that area wanted, comes from an **independent** organization, and **publishes its data** so anyone
can check it. This list is updated as things change; last reviewed November 16, 2026.

### Waiting for permission

- **AP VoteCast** (AP-NORC Center for Public Affairs Research): a survey of over 100,000 voters at each
  federal election, with results for every state and questions on major issues, some about specific
  proposals.
  Its terms allow non-commercial use but need clarifying for a site like this one, so we asked AP-NORC
  for written permission on November 10, 2026, and won't use the data until they reply.
- **Yale Climate Opinion Maps** (Yale Program on Climate Change Communication): estimates for every
  state and House district on climate and energy proposals, such as regulating carbon dioxide as a
  pollutant or funding renewable-energy research. The figures are statistical estimates from a
  national survey, not direct answers from each area, and the questions are general policies, so they
  would be shown as "related" votes, not counted in any score. Their terms don't allow the data to be
  republished, so we asked for written permission on November 15, 2026, and won't use the data until
  they reply.

### Being looked into

- **Other statewide university polls** (for example Marist, Quinnipiac, Siena and Marquette Law
  School): these publish detailed results and occasionally ask about a specific bill. Each covers one
  state at a time and asks such questions only now and then, so they're added one question at a time,
  where one clearly matches a vote, as with the [Texas Politics Project](sources.html#texas-politics-project)
  and [UNH Survey Center](sources.html#unh-survey-center) questions above. Reviewed so far: Quinnipiac's
  Pennsylvania polls (no questions on federal bills), Siena's New York poll and Marquette's Wisconsin
  polls (mostly about a bill's effects rather than support for it; one Marquette question on health
  insurance subsidies is a possible match, still being checked).

### Not used

- **National-only surveys**, such as the American National Election Studies, the General Social Survey,
  Pew Research Center, Gallup and KFF: excellent surveys, but they interview too few people in each
  state or district to say what that area wanted, and many ask about attitudes, not specific bills.
- **America's Political Pulse** (Polarization Research Lab) and the **VOTER Survey** (Democracy Fund
  Voter Study Group): well-run surveys that track attitudes and values over time, not support for
  specific bills, so their answers can't be compared with votes.
- **Polls paid for by campaigns, parties or advocacy groups**, of any political leaning: left out so the
  site stays independent, however good the poll.
- **Polls run for newspapers and TV stations** (for example the Glengariff Group's Michigan polls for
  WDIV and The Detroit News): left out. Their questions are written for news coverage, often in the
  middle of a story, and their methods and full results are published less consistently, so we use
  polls from universities and research organizations instead.
- **Paid subscription trackers** (for example Morning Consult's state data): their figures can't be
  published or checked by readers.

## Updates and corrections {#updates}

Every downloaded file is kept unchanged, so any figure can be rebuilt and checked, and the code that
does it is [public]({{source_url}}). If you find an
error, please tell us at <span data-email="corrections">corrections (at) {{email_domain}}</span>.
