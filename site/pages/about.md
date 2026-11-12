---
title: About
description: What US Congress vs Voters is, why it exists, and the rules it follows to stay neutral.
---
# About

<p class="lede">US Congress vs Voters shows how members of the House and Senate vote, and how those
votes compare with what people where they live told independent surveys.</p>

## Why {#why}

Many sites track how Congress votes. Fewer show whether those votes match what constituents want. When
independent surveys ask people about the same bills Congress votes on, the two can be put side by side,
state by state and district by district. This site does that, openly and the same way for everyone.

## Our rules {#rules}

- **Same treatment for every member and party.** The same methods, wording and design apply to everyone.
  Votes are shown by shape, not party colors.
- **Public sources only.** Every figure comes from official records or published surveys, listed on the
  [Sources](sources.html) page with links to the originals.
- **Several surveys, shown side by side.** We never blend sources into one score.
- **Uncertainty shown.** When a survey can't tell what most people want, we say it's too close to call
  rather than guess.
- **No judgment on votes.** Voting against a majority can be a principled choice. We show the comparison;
  readers decide what it means.
- **No tracking.** No accounts, no cookies, no advertising. See [Privacy](privacy.html).

## Open source {#source-code}

Everything that produces this site is public: the code that downloads and checks each source, the
methods that estimate opinion, the rules that match survey questions to votes, and every special case
we've handled. Read it, check it, or reuse it: [source code]({{source_url}}). The full technical notes on
each data source are in [DATA_SOURCES.md]({{source_url}}/blob/main/docs/DATA_SOURCES.md). The code is
published under the [GNU Affero General Public License v3]({{source_url}}/blob/main/LICENSE): anyone may
reuse it, and anyone who runs a changed version as a public site must publish their changes too.
Suggestions and corrections are welcome as [issues]({{source_url}}/issues); every change is reviewed
before it's made.

## How this site is built {#how-built}

A person runs this site and makes the decisions. Most of the code, and first drafts of most page
text, are written by Claude, an AI model made by Anthropic, working at the maintainer's direction.

**What the AI does:** writes the code that downloads and checks each data source, the code that
estimates opinion and matches survey questions to votes, the tests that check that code, and drafts
of pages like this one. It also checks its own work: running the tests, comparing vote totals with
the official records, and looking at each page before it's published.

**What the maintainer does:** decides which sources to use and which survey questions count as the
same proposal as a vote, approves the wording, reviews changes before they're published, and decides
what to correct. The AI often proposes a match between a survey question and a vote; each one, and
every "related, not counted" call, is approved by the maintainer and written down in the item files
the code reads, where anyone can see it.

**What happens when you visit:** no AI is involved. Every figure is calculated by fixed code from the
published data, the same way for every member, and you can repeat the calculation from the
[source code]({{source_url}}). Nothing you do on the site is sent to an AI.

AI can make mistakes, and so can people. That's why every vote links to its official record, every
estimate to its survey, the code is public, and every fix to a figure is listed in the
[corrections log](corrections.html). Anthropic doesn't review, endorse or fund this site.

## Who runs this {#who}

US Congress vs Voters is built and maintained by **John LeDuc**, a software developer since 1990.
It's an independent personal project, separate from his professional work. Questions about the site
or its figures are welcome through the [Contact](contact.html) page.

## Independence {#independence}

This is an independent civic project. It isn't affiliated with the U.S. government, Congress, any
political party or campaign, or any of the survey organizations whose work it uses.

## Contact and corrections {#contact}

If you find an error, we want to fix it: write to <span data-email="corrections">corrections (at) {{email_domain}}</span>.
For anything else, see the [Contact](contact.html) page.
