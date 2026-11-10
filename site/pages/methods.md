---
title: Methods
description: How this site matches votes to survey questions, estimates what people in each state and district want, and decides whether a member voted with them.
---
# Methods

<p class="lede">How we decide whether a member of Congress voted the way most people where they live
wanted, and what we do when the answer isn't clear.</p>

[TOC]

## The idea in three steps {#steps}

1. **Find survey questions about real votes.** Independent surveys ask people whether they support
   specific bills or actions of Congress. We use only questions that a recorded floor vote answers.
2. **Estimate what people in each area want.** For each state and House district, we estimate the
   share who support the proposal, with a range showing how sure we can be.
3. **Compare.** If the range is clearly above or below an even split, the area has a clear majority,
   and we show whether the member's vote went with it or against it. If the range crosses the even
   split, we say it's **too close to call** and make no judgment.

## Matching a survey question to a vote {#matching}

- **The decisive vote.** For each chamber we use the last decisive floor vote on the proposal: final
  passage, agreeing to the other chamber's version, or confirming a nominee. Every match is checked by
  hand before it's published, and a rule can require the exact vote count, so a different vote can't
  be picked up by mistake.
- **Members are compared with the area they represented when they voted**, even if district lines
  changed later.
- **Procedural votes are labeled.** When the Senate's only vote on a bill was on *cloture* (whether to
  end debate and proceed), we use that vote and say so beside it.
- **Unusual procedures are labeled too.** Some bills pass the House under *suspension of the rules*
  or through a *self-executing rule*; see the [Glossary](glossary.html). We use the vote that
  actually decided the question and explain it in a note.
- **Which side is "support".** Usually a Yea vote supports the proposal. When a vote was on blocking
  it, such as an amendment to prohibit aid, voting Nay is the supporting side. The bar shows each
  member's vote at the end of the scale it supported, so the picture always reads the same way.
- **Related votes are shown, never counted.** When the only vote was on a bill that's close to, but not
  the same as, what the survey asked, we show it with a **Related vote** label for context and leave
  it out of the score. Example: a survey asked about banning members from trading stocks; the House
  voted on a narrower bill that some members opposed because it didn't go far enough.
- **Some questions are left out.** If no floor vote answers a question, we don't use it.

## Estimating opinion {#estimates}

### Cooperative Election Study {#estimates-ces}

The Cooperative Election Study (CES) surveys tens of thousands of people a year, but that's only a few
dozen in a typical House district: too few to report a district's raw percentage reliably. So we use a
standard technique called **partial pooling**:

- each state's estimate is pulled toward the national figure;
- each district's is pulled toward what we'd expect for a district like it: its state's figure, adjusted
  for the district's Census profile (education, income, age, and racial and ethnic makeup), so a
  college-town district and a rural one in the same state aren't assumed to think alike. The Census
  figures are official and nonpartisan; no election results are used;
- the fewer people surveyed in an area, the stronger the pull;
- how strong to pull is learned from how much areas genuinely differ in the survey.

Each estimate comes with a **90% range**: the span the true figure very likely falls in. We tested the
method on simulated surveys where the right answer was known. Pooling cut district errors by about a
third compared with raw percentages, and our ranges contained the true figure 91–96% of the time.
Adding the Census profile cut district errors by up to a third again where districts in a state really
differ, made no difference where they don't, and gave more clear calls with fewer wrong ones.
Where a district's range crosses 50%, it's too close to call. That's common in House districts and is
the honest answer when few people were asked.

Senators are compared with their whole state, where samples are much larger.

### Program for Public Consultation {#estimates-ppc}

The Program for Public Consultation publishes results for each state and district it surveys, from
samples of several hundred to 2,000 people each, along with each sample's margin of error. We use those
published figures directly: support is the share in favor among people who answered either way, and the
range comes from the published margin of error, converted to the same 90% level we use for the CES.
Where one margin is given as a range for several districts, we use the larger figure, so our ranges are
never narrower than the survey supports.

### State ballot measures {#estimates-ballot}

For a state ballot measure, the figure is the share of votes cast that were Yes: Yes ÷ (Yes + No),
from the certified results. Blank ballots aren't counted, the same way surveys leave out people who
didn't answer. Because these are real votes rather than a sample, there is no range; the majority is
whichever side won, and only an exact tie would be too close to call. Each result is compared only
with members who represent the whole state, and always as a related vote that isn't counted.

## Showing the sources side by side {#side-by-side}

Different surveys ask different questions, in different years, in different ways. Rather than blend
them into one number, every member's page shows **one line per survey organization**, and every
comparison names its source. When sources agree, that's worth knowing; when they differ, you can see it.

## Other figures on member pages {#other}

- **Missed votes:** votes recorded as Not Voting, out of all votes the member could have cast in the
  current Congress.
- **Voted with their party's majority:** votes where the member voted the same way (Yea or Nay) as most
  members of their party. Ties are left out, and independents are counted with the party they caucus
  with.
- **Where their party and their state (or district) disagreed:** surveyed votes where most of the
  member's party in that chamber, on that day, took one side and the clear survey majority where the
  member's constituents live (their state, or their district for a representative) took the other.
  Independents who caucus with a party are compared with that caucus, and the page says so; an
  independent who caucuses with no one has no group to compare with, so the line isn't shown.
  It's a count with the votes listed, so you can open each one; it isn't a score. Only votes on the
  same proposal the survey asked about, with a clear majority, are included. District estimates are
  less certain than statewide ones, so fewer districts have a clear majority; a district that's too
  close to call is left out of this line, not counted either way.
- **Party-blind view:** the "Hide party labels" switch at the top of every page removes party names,
  party vote splits and the party figures above, so a member can be judged on their votes alone. It
  changes only what's shown on your screen; the switch is remembered in your browser only.
- **Residents:** Census Bureau estimates of the people living in the member's state or district.

## Limits {#limits}

- Surveys ask about a small number of bills, so each member is compared on a handful of votes, not their
  whole record.
- A survey measures opinion at one moment; a vote may come months earlier or later.
- Members weigh many things besides opinion polls: their own judgment, the details of a bill, their
  party, and what they promised voters. Voting against a majority isn't necessarily wrong, and this site
  doesn't say it is. It shows the comparison so you can judge.

The technical details, including every special case we've handled for each source, are in the
site's [source code]({{source_url}}): see [DATA_SOURCES.md]({{source_url}}/blob/main/docs/DATA_SOURCES.md)
and the estimate method in [opinion.py]({{source_url}}/blob/main/src/congress_congruence/opinion.py).
