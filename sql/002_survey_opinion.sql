-- Constituent opinion from surveys (CES), and the roll calls each survey item asked about.

-- One survey question about an action of Congress.
create table core.survey_item (
    survey        text not null,            -- e.g. 'CES 2025'
    variable      text not null,            -- e.g. 'CC25_340c'
    question      text not null,            -- plain-language summary shown to readers
    survey_label  text,                     -- the label stored in the survey file (may be cut short)
    note          text,
    primary key (survey, variable)
);

-- The vote that answers the question in each chamber: the last decisive floor vote.
-- Voting Yea = the "support" side of the survey question.
create table core.survey_item_vote (
    survey        text not null,
    variable      text not null,
    chamber       text not null check (chamber in ('house', 'senate')),
    roll_call_id  text not null references core.roll_call on delete cascade,
    match_note    text,                     -- why this vote was chosen
    primary key (survey, variable, chamber),
    foreign key (survey, variable) references core.survey_item on delete cascade
);

-- Estimated share supporting, per state (for senators) and per district (for representatives).
-- district is null for a statewide estimate; 0 for an at-large House seat.
create table core.opinion_estimate (
    survey          text not null,
    variable        text not null,
    state           char(2) not null,
    district        smallint,
    respondents     integer not null,       -- people in this area who answered
    effective_n     real not null,          -- respondents after accounting for unequal weights
    raw_support     real,                   -- weighted share supporting, before pooling (null if none answered)
    support         real not null,          -- estimate after partial pooling, 0..1
    support_low     real not null,          -- 90% interval
    support_high    real not null,
    majority        text not null check (majority in ('support', 'oppose', 'too_close')),
    method          text not null,
    computed_at     timestamptz not null default now(),
    foreign key (survey, variable) references core.survey_item on delete cascade
);
create unique index opinion_estimate_area on core.opinion_estimate (survey, variable, state, coalesce(district, -1));
