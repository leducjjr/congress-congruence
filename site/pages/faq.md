---
title: FAQ
description: Common questions about US Congress vs Voters - what it shows, how the comparison works, what it doesn't claim, and how to report an error.
---
# Frequently asked questions

<p class="lede">Short answers, with links to the full details.</p>

## What does this site show? {#what}

How members of the House and Senate voted, and, where independent surveys asked people about the same
bills, how each member's vote compared with what most people where they live said. Everything comes from
public records and published surveys, listed on the [Sources](sources.html) page.

## Who runs it, and is it connected to a party? {#who}

It's an independent civic project. It isn't affiliated with the U.S. government, Congress, any political
party or campaign, or any survey organization, and it takes no advertising. The same methods, wording and
design apply to every member. See [About](about.html).

## Is this site made with AI? {#ai}

Partly. Most of the code and first drafts of the text are written by Claude, an AI model made by
Anthropic, working at the maintainer's direction. A person decides what the site uses and shows:
the sources, which survey questions match which votes, the wording, and what gets corrected, and
reviews changes before they're published. No AI is involved when you use the site: every figure is
calculated by fixed code from published data, and the code is public so anyone can check it.
More on the [About](about.html#how-built) page.

## Does "voted against the majority" mean a member did something wrong? {#wrong}

No. Members weigh many things: their own judgment, the details of a bill, what they promised voters,
and their party. A vote against a majority can be a principled one. The site shows the comparison and
leaves the judgment to you.

## How do you know what people in my district think? {#how-estimated}

Large surveys such as the Cooperative Election Study ask tens of thousands of people about specific bills.
We estimate each state's and district's support from the people surveyed there, leaning on the statewide
answers and on Census figures about the district where only a few people were asked. Each estimate comes
with a range. [Methods](methods.html) explains it step by step.

## What does "too close to call" mean? {#too-close}

The range of likely support crosses 50%, so the survey can't tell which side most people were on. Those
votes are shown but never counted for or against a member. See the [Glossary](glossary.html#too-close-to-call).

## Why are some votes marked "related" and not counted? {#related}

Sometimes Congress never voted on exactly what a survey asked, but voted on something close: a bill that
included the proposal among other things, for example. We show those votes so you can see them, but
only votes on the same proposal the survey asked about are counted.

## Why don't you combine the surveys into one score? {#one-score}

Surveys ask different questions in different ways at different times. Adding them together would hide
those differences, so each source is always shown on its own.

## Why is my member compared on only a few votes? {#few-votes}

Surveys ask about a small number of major bills each year, and only those can be compared. The rest of
the voting record is still shown in full, and the [All votes](votes.html) page lists every vote loaded.

## What does "Hide party labels" do? {#party-blind}

It removes party names, the way each party voted, and the party figures from every page, so you can look
at a member's votes on their own merits. Nothing else changes. Your browser remembers the choice on your
device only. You can also share a link with party labels hidden by adding `?parties=hidden` to it.

## What's on the state pages and the compare page? {#tools}

A [state page](state.html) lists the state's members, how each one's surveyed votes compared with the
people they represent, and what the state's residents told each survey. [Compare](compare.html) puts two
members side by side: attendance, how often they voted the same way when both voted, the votes where they
split, and their surveyed votes. Both pages only count what's in the records; open any vote to check it.

## How current is the information? {#current}

House votes are checked every two hours and Senate votes daily, both from each chamber's official
files. A Senate vote not yet loaded from the Senate's files comes from Voteview, which can trail the
official record by days or weeks; see [Sources](sources.html#senate). Surveys are added when their
data is published. The footer of every page shows
the latest vote loaded.

## Do you collect information about me? {#privacy}

No accounts, no cookies, no tracking. A few conveniences are kept in your own browser only. See
[Privacy](privacy.html).

## I found a mistake. What happens if I report it? {#mistakes}

Write to <span data-email="corrections">corrections (at) {{email_domain}}</span> or use the
[contact form](contact.html#feedback). We check every report against the original source. When a figure
on the site was wrong, we fix it and record the fix in the [corrections log](corrections.html).

## Can I check the work myself? {#check}

Yes. Every vote links to its official record, every survey to its published data, and all the code that
builds this site is [public]({{source_url}}).
