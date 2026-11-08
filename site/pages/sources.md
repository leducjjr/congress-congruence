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

### Senate {#senate}

**Official source:** the U.S. Senate's roll-call records:
[senate.gov](https://www.senate.gov/legislative/votes_new.htm).

**Source we use for now:** [Voteview](https://voteview.com), a long-running research project at UCLA
that republishes every Senate and House roll call. The Senate's website doesn't currently allow
automated downloads from our server, so we load Senate votes from Voteview instead. Voteview can be
days to weeks behind the official record; the footer of every page shows how current each chamber is.

**How often:** checked daily. If we load a vote from the Senate's own record later, it replaces the
Voteview copy.

**Paired and announced votes:** a senator who is absent can "pair" with one on the other side or
announce a position. These aren't counted in the official tally, so we treat them as not voting, as the
Senate does.

### Members of Congress {#members}

**Source:** [congress-legislators](https://github.com/unitedstates/congress-legislators), a public
dataset of every member's terms, seats, parties and official IDs, maintained by volunteers and widely
used by news organizations and researchers.

**How often:** checked daily, so new members appear before their first vote.

**How we use it:** every vote is matched to the seat the member held **on the day of the vote**, so
redrawn districts, special elections and moves between the House and Senate are handled correctly.

### Bills {#bills}

Bill names and links go to [Congress.gov](https://www.congress.gov/), the official site for federal
legislation, run by the Library of Congress.

## Surveys of what people want {#surveys}

We compare votes with what people said in independent, published surveys. We use more than one survey
organization, and we **show each one separately**, never combined into a single score, so you can see
where they agree.

We only compare a vote with a survey question when both are about the same proposal. See
[Methods](methods.html) for how votes and questions are matched.

### Cooperative Election Study {#cooperative-election-study}

**Who runs it:** a consortium of universities led by Harvard University and Tufts University, fielded by
YouGov. [cces.gov.harvard.edu](https://cces.gov.harvard.edu/)

**What it is:** one of the largest academic surveys of U.S. adults, run every year since 2006. Each
year it asks whether people support specific actions Congress has voted on.

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

**What we use:** the published results for each state and district, taken from the questionnaires on
[vop.org](https://vop.org/battlegrounds-aggregate/), with each sample's size and margin of error.
Only members from the states and districts it surveyed get these comparisons.

**Loaded on this site:**

<div data-surveys="Program for Public Consultation"><p class="note">Loading the list…</p></div>

## Population {#population}

**Source:** the Census Bureau's American Community Survey, 1-year estimates of total population for
every state and House district, from [api.census.gov](https://www.census.gov/data/developers.html).

**How we use it:** to show how many people each member represents, and how many of them a survey
reached. Each year's figures are matched to the district lines in use at the time.

**How often:** a new year's figures are released each September and loaded automatically.

## Considered and not used {#not-used}

- **America's Political Pulse** (Polarization Research Lab): a well-run weekly survey, but it asks about
  attitudes, not specific bills, so its answers can't be compared with votes.

## Updates and corrections {#updates}

Every downloaded file is kept unchanged, so any figure can be rebuilt and checked, and the code that
does it is [public]({{source_url}}). If you find an
error, please tell us (contact details are on the [About](about.html) page).
