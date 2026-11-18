---
title: How this site was built
description: How one volunteer and an AI model built US Congress vs Voters in 12 days - who did what, the technology in plain language, what it costs, and how to do something similar.
---
# How this site was built

<p class="lede">One volunteer and an AI model built this site in 12 days, from November 7 to November 18,
2026. The maintainer, John LeDuc, made every decision. Claude, an AI model made by Anthropic, did the
research and wrote the code. This page explains how that worked, in plain language, for anyone with an
idea of their own.</p>

You don't need to know how to code to follow it. For what the AI does and doesn't do on the site
itself, see [About](about.html#how-built). In short, no AI is involved when you visit.

## How it started {#start}

It began as a question, and no code was written until there was a plan.

1. **A question.** The maintainer asked whether any website measured how members of Congress vote
   against what voters want. A few apps came close, but they score members against the app's own
   users, not a fair sample of the people they represent.
2. **What do voters want?** No official count exists. The best source is large academic surveys,
   such as the Cooperative Election Study, which asks tens of thousands of Americans how they would
   have voted on real bills.
3. **A plan.** He asked for "a systems inventory needed to do data collection, storage, and
   maintenance." Claude wrote it:
    - every free public data source, and which ones had shut down;
    - the jobs that would fetch the data, and the database design;
    - how the site would serve the data, and the upkeep it would need;
    - rough costs and risks.
4. **Decisions.** He answered the plan's open questions. Cover the House and the Senate from the start.
   Use Python. Start on one small rented server.
5. **Building.** The first code was saved the same day.

## Who did what {#roles}

The maintainer made every decision that needed judgment, ownership or a signature. Claude did
everything that could be researched, designed, written or tested.

| Area | The maintainer | Claude |
| --- | --- | --- |
| The idea and its purpose | Defined it and kept it on course | Researched what already existed and what was possible |
| Rules the site follows | Set them (below) | Built them into the code and pages, and flagged anything that might break one |
| Technology | Agreed to the proposals | Chose the database, designed its tables, chose the language, the web framework and the hosting setup |
| Code | None written | All of it: data loaders, database changes, the data service, the website, the app, 271 automated tests |
| Data judgment | Approved every match between a survey question and a vote; decided which surveys to use or leave out | Proposed each match with the evidence, and wrote notes explaining it to readers |
| Server and accounts | Rented the server, bought the domain names and email; created the accounts; typed every password himself | Wrote the exact steps and commands, and explained each one |
| Publishing | Ran a few commands to put each change live | Prepared every change, tested it, and saved it with a note saying what changed and why |
| Outreach | Wrote to data providers and colleagues | Drafted the emails |
| Testing | Checked pages on a laptop, an iPhone and an Android phone | Fixed what he found |
| Writing for readers | Reviewed and asked for changes | Drafted the pages: methods, sources, FAQ, privacy, corrections, install guide |

## The technology, in plain language {#technology}

The common thread: free, long-established tools that one person can run on one small rented computer.

| Piece | What it is, in everyday terms | What was chosen | Why |
| --- | --- | --- | --- |
| Server | A computer you rent in a data center that is always on and connected | A small virtual private server running Ubuntu Linux | Cheap, and enough for this much data |
| Database | A filing system of linked spreadsheets that holds millions of rows and answers questions about them in a fraction of a second | PostgreSQL | Free, very reliable, decades old, handles text search, needs no special hardware |
| Programming language | The language the scripts and the data service are written in | Python | The best tools for the formats this data comes in: XML vote files, survey data files, PDFs and spreadsheets |
| Data service | A "waiter" between the database and the pages: a page asks for a member's votes, the service fetches them | FastAPI | Simple, fast, and read-only, so a page can never change the data |
| Website | The pages you see | Plain web pages built by a script, served by nginx | Nothing heavy to maintain; fast on phones; works offline once installed as an app |
| Code storage | A safe copy of every line of code and every change to it | GitHub, with the [code public]({{source_url}}) | Every change can be undone, and anyone can check the work |
| Automatic checks | Tests that check the code does what it should | 271 tests, run before every change | Catches mistakes before readers see them |

**The database** has two areas. The main one holds the record from 1973 on; a separate "history" area
holds every vote back to the 1st Congress in 1789. Its main tables:

- **Members and terms:** each person who served, every term they held, and their party in each term.
- **Votes:** each roll-call vote, and every member's position on it, one row per member per vote.
- **Bills:** titles, policy areas and subject tags, so votes can be searched.
- **Surveys:** each survey, each question, and which vote each question was matched to.
- **Opinion estimates:** for each question, the share of people in each state and district who
  supported it, with its margin of error.
- **Population:** residents, citizens and adult citizens in each state and district.
- **Housekeeping:** every download and every scheduled run, so any figure can be traced to the file it
  came from.

**The scripts:** each data source has a loader, a small program that downloads that source, checks it
against the official totals, and adds it to the database. A scheduler on the server runs them:

- House votes every 2 hours;
- Senate votes, member changes and bill details once a day;
- a check for new survey releases once a month;
- a backup of the database every night;
- an alert to the maintainer if a job fails.

## How the work went, day to day {#process}

Every change followed the same short loop, often in minutes:

1. **The maintainer asks, in plain words,** often with a screenshot: "I see apparent duplicates.
   Please can you review and adjust as needed?"
2. **Claude makes the change in its own private copy of the project.** It runs all the tests and looks
   at the page in a browser. Then it saves the change with a note explaining it.
3. **The maintainer puts it live** by running the same few commands on the server each time.
4. **He checks it** on his own devices, and the loop starts again.

A few habits made this work:

- **Ask before guessing on anything costly.** Claude started straight away on clear requests. It asked
  one short question first when a wrong guess would be expensive or hard to undo.
- **A person approves every data judgment.** No survey-to-vote match went live without the
  maintainer's yes.
- **Secrets never go through the chat.** Passwords and access keys were typed directly on the server.
  Claude wrote the instructions but never saw the values.
- **Standing rules get written down,** in a project-notes file, so a rule from day one is still kept on
  day ten.

## The rules that shaped it {#rules}

The maintainer's rules shaped the site more than any technical choice. Claude treated them as fixed
requirements:

- **Credibility comes first.** Every figure links to its source, and every fix is in the
  [corrections log](corrections.html).
- **Strictly neutral.** No links to or promotion of any party; a switch hides party labels entirely.
- **Never blend survey sources,** and **count only like-for-like votes.** A vote that's close to, but not
  the same as, what a survey asked is shown as "related" and not counted. See [Methods](methods.html).
- **Show the data, don't draw conclusions.** No rankings or trend claims.
- **Collect nothing about visitors.** No accounts, no cookies, no tracking, and no outside companies
  contacted. See [Privacy](privacy.html).
- **Respect data providers' terms.** Permission is asked for before using data whose terms require it.
- **Be open about everything.** Public code, and a [What's new](whats-new.html) log of every change.

## Timeline {#timeline}

The site went public on day 4 and was improved in small steps while live, with 208 saved changes in
12 days.

| Date (2026) | Milestone |
| --- | --- |
| Nov 7 | The first question, the plan and the database. House and Senate votes loaded. The first survey matched to votes. Census population. |
| Nov 8 | Domain and email set up. Sources, Methods, About and Privacy pages. Search. State ballot measures. Surveys back to 2008. |
| Nov 9 | Compare two members, state pages, All votes, FAQ, the corrections log, and the switch to hide party labels. |
| Nov 10 | **The site goes public**, with its code. The Features page. A fourth survey source. |
| Nov 11 | Members by the numbers. |
| Nov 12 to 13 | Voting records back to 1973, then a historical record back to 1789. |
| Nov 15 to 16 | Statewide university polls. Faster search and filter buttons across the site. |
| Nov 17 | Installable as an app; the typeface served from the site itself; What's new. |
| Nov 18 | This page. |

## What it costs {#cost}

The site is a volunteer project with no ads, donations or funding. Four things cost money. Every data
source and every piece of software is free.

| Item | Paid? | Notes |
| --- | --- | --- |
| A Claude subscription | Monthly | For all of the research, code and writing |
| A small rented server | Monthly | Runs the database, the scripts, the data service and the website |
| Domain names | Yearly | uscongressvsvoters.org, plus .com and .online addresses that point to it |
| Email hosting | Yearly | The [contact](contact.html) address for readers, the press and corrections |
| PostgreSQL, Python, FastAPI, nginx, Ubuntu | Free | Open-source software |
| GitHub | Free | Public code storage |
| House and Senate records, Census Bureau figures, university surveys | Free | Some needed a free access key; some providers were asked for permission first |

## Doing something similar {#yours}

You don't need to know how to code or run a server. You do need to know what you want, decide quickly,
and follow written instructions carefully. Here's the order that worked here:

1. **Start with the question, not the solution.** Ask whether something like your idea already exists,
   and what data or tools it would need. You may not need to build anything.
2. **Write down your purpose and your rules before building.** Who it's for, what it must do, and what
   it must never do. These steer hundreds of later decisions.
3. **Ask for a plan as a document,** with each piece in plain language and what it costs. Read it, and
   answer its open questions.
4. **Let the AI choose the technology, but ask why.** Say what matters to you, such as low cost, simple
   upkeep, or no lock-in to one company.
5. **Set up the accounts yourself:** hosting, a domain name, email, code storage. Type every password
   yourself, and never paste one into a chat.
6. **Build a small first version on a private test site.** React to it in plain words. Screenshots
   help more than descriptions.
7. **Keep the loop short:** one change, look at it, then the next.
8. **Keep every judgment call.** Wording that speaks for you, privacy, anything that affects other
   people. The AI can lay out the options and recommend one; you decide.
9. **Go live early, then improve in public,** with a visible log of changes and corrections.
10. **Check its work.** Test on your own devices, ask for sources, and treat its answers like a capable
    new colleague's: usually right, worth checking where it matters.

A good first message might be:

> I want to build a tool that [does what] for [whom]. I have no software or server experience. First
> tell me whether something like this already exists. If not, write a plain-language plan: what it
> needs, what it would cost each month, and what I'd have to do myself.

Anthropic doesn't review, endorse or fund this site.
