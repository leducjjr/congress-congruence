-- More than one survey organization, each shown on its own (never blended).

-- Who runs each survey, and one line on how it asks, shown with the results.
alter table core.survey
    add column organization text,          -- e.g. 'Cooperative Election Study'
    add column description  text;          -- e.g. 'a large academic survey of U.S. adults'

update core.survey
   set organization = 'Cooperative Election Study',
       description  = 'a large academic survey of U.S. adults'
 where survey like 'CES %' and organization is null;

-- Which side of the question a Yea vote is on. Usually Yea = support, but a vote on an
-- amendment to block something (e.g. "prohibit aid to Ukraine") has Nay on the support side.
-- 'related' marks a vote on a bill that is close to, but not the same as, what was asked:
-- shown for context, never counted as voting with or against constituents.
alter table core.survey_item_vote
    add column support_side text not null default 'yea' check (support_side in ('yea', 'nay')),
    add column match_kind   text not null default 'same' check (match_kind in ('same', 'related'));

-- Surveys that publish results per area (rather than respondent data) do so in a separate
-- document for each state; link the one each figure came from.
alter table core.opinion_estimate
    add column source_url text;
