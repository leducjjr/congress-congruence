---
title: Corrections
description: Every correction made to figures shown on US Congress vs Voters, newest first, with what was wrong and what changed.
---
# Corrections log

<p class="lede">When something this site showed turns out to be wrong, we fix it and list it here: the date,
what was wrong, and what changed. Newest first.</p>

To report an error, write to <span data-email="corrections">corrections (at) {{email_domain}}</span> or use
the [contact form](contact.html#feedback). We check every report against the original source. Small changes
to wording or layout that don't change any figure aren't listed. The complete history of every change, large
or small, is in the [source code]({{source_url}}/commits/main).

## Since launch {#since-launch}

**November 12, 2026**

- **When members who joined partway through a Congress started.** The member list this site uses gave the
  first day of the Congress as the start date for 40 members who actually arrived later, mostly by special
  election (for example Steny Hoyer, who began on May 19, 1981, not January 5). That overstated their time
  in Congress by up to two years. Each date was checked against the roll calls and the official record and
  corrected; the [list of corrections](https://github.com/leducjjr/congress-congruence/blob/main/config/term_corrections.yaml)
  gives each one and its source.
- **Links to members from Members by the numbers.** For a member whose last vote fell just after their term
  ended (Matt Gaetz, November 2024), the link opened an empty page and the Seat column was blank. Both now
  show the seat they held.

## During the preview, before launch {#preview}

Before the site opened to the public, we reviewed every match between a survey question and a vote. These
are the fixes that changed what a reader would have seen.

**November 8, 2026**

- **Children's health insurance (CES 2008).** The question was compared with the February 2007 passage of
  H.R. 976, which at that point was an unrelated small-business tax bill. It is now compared with the bill's
  final votes in September 2007 (House 265–159, Senate 67–29).
- **Help for homeowners facing foreclosure (CES 2008).** Senators were compared on the Senate's April 2008
  vote on an earlier draft. They are now compared on its final vote of July 26, 2008 (72–13).
- **Trade agreement with Peru (CES 2008).** The House vote matched to this question was corrected to the
  House's passage of the agreement.
- **House health care bill (CES 2009).** The bill number, H.R. 3962, was later reused for an unrelated
  Medicare bill (June 2010, 417–1), and that vote was also being matched. Only the November 2009 passage vote
  is compared now.
- **Senate votes of 2015–2016 (114th Congress) were missing.** The source file wrote member IDs in a
  different format, so none of its 502 votes loaded. All are loaded now.
- **Appointed senators shown as former members too soon.** A senator appointed to fill a vacancy was listed
  as former once their appointment's listed end date passed, even before a successor was recorded. They now
  stay listed as serving until a successor appears in the member list.

**November 7, 2026**

- **TikTok bill (CES 2024).** The House passed H.R. 7521 under a suspension of the rules, which the matching
  rule didn't recognize, so representatives weren't compared on it. They are now.
