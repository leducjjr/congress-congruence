-- Core schema: members, terms, roll-call votes for BOTH chambers.
-- Everything is keyed so House and Senate rows live in the same tables.

create schema if not exists core;

------------------------------------------------------------------------
-- Members
------------------------------------------------------------------------

-- One row per person who has ever served. Bioguide ID is the one key
-- used everywhere else in the database.
create table core.member (
    bioguide_id    text primary key,
    first_name     text not null,
    middle_name    text,
    last_name      text not null,
    suffix         text,
    nickname       text,
    official_full  text,
    birthday       date,
    gender         char(1)
);

-- Every other ID a member is known by, so any source can be translated
-- to a Bioguide ID. Senate vote files use 'lis'; Voteview uses 'icpsr';
-- FEC IDs are many per person (one per campaign), hence one row each.
create table core.member_external_id (
    id_type      text not null,
    id_value     text not null,
    bioguide_id  text not null references core.member on delete cascade,
    primary key (id_type, id_value)
);
create index on core.member_external_id (bioguide_id);

------------------------------------------------------------------------
-- Terms of service
------------------------------------------------------------------------

-- A term is one stint in one seat (House: usually 2 years; Senate: up to 6).
-- House terms have a district; Senate terms have a class (1, 2 or 3).
-- District 0 = at-large seat; -1 = historical seat with no district number.
create table core.term (
    term_id        bigserial primary key,
    bioguide_id    text not null references core.member on delete cascade,
    chamber        text not null check (chamber in ('house', 'senate')),
    state          char(2) not null,
    district       smallint,
    senate_class   smallint,
    party          text,
    caucus         text,                 -- set when caucus differs from party (e.g. independents)
    start_date     date not null,
    end_date       date not null,
    how            text,                 -- 'appointment', 'special-election', or null for regular
    end_type       text,
    unique (bioguide_id, chamber, start_date),
    check (end_date >= start_date),
    check (
        (chamber = 'house'  and district is not null and senate_class is null) or
        (chamber = 'senate' and district is null)
    )
);
create index on core.term (chamber, state, district);
create index on core.term (start_date, end_date);

-- Party switches in the middle of a term.
create table core.term_party (
    term_id     bigint not null references core.term on delete cascade,
    party       text not null,
    start_date  date not null,
    end_date    date not null,
    primary key (term_id, start_date)
);

------------------------------------------------------------------------
-- Bills (filled in by the Congress.gov job in a later step)
------------------------------------------------------------------------

create table core.bill (
    congress      smallint not null,
    bill_type     text not null,         -- hr, s, hjres, sjres, hconres, sconres, hres, sres
    bill_number   integer not null,
    title         text,
    introduced    date,
    policy_area   text,
    latest_action text,
    updated_at    timestamptz,
    primary key (congress, bill_type, bill_number)
);

------------------------------------------------------------------------
-- Roll-call votes
------------------------------------------------------------------------

-- One row per recorded vote in either chamber.
-- roll_call_id looks like 'h-119-1-362' (chamber-congress-session-roll).
create table core.roll_call (
    roll_call_id       text primary key,
    chamber            text not null check (chamber in ('house', 'senate')),
    congress           smallint not null,
    session            smallint not null,
    roll_number        integer not null,
    vote_date          date not null,
    vote_time          time,
    question           text,             -- e.g. 'On Passage', 'On the Cloture Motion'
    vote_type          text,             -- e.g. 'YEA-AND-NAY', '2/3 YEA-AND-NAY'
    result             text,             -- e.g. 'Passed', 'Agreed to', 'Rejected'
    description        text,
    -- the measure being voted on, when there is one
    bill_congress      smallint,
    bill_type          text,
    bill_number        integer,
    amendment_number   text,
    -- totals as published by the chamber, used to validate the member rows
    yea_total          integer,
    nay_total          integer,
    present_total      integer,
    not_voting_total   integer,
    tie_breaker        text,             -- Senate only: Vice President's vote, if any
    source             text not null,    -- 'house_clerk' | 'senate_lis' | 'voteview'
    source_url         text,
    raw_file_sha256    text,
    loaded_at          timestamptz not null default now(),
    unique (chamber, congress, session, roll_number)
);
create index on core.roll_call (vote_date);
create index on core.roll_call (bill_congress, bill_type, bill_number);

-- How each member voted. 'position' is normalized; 'raw_position' is
-- exactly what the source said (votes for Speaker list candidate names,
-- and some records say 'Aye'/'No' instead of 'Yea'/'Nay').
create table core.member_vote (
    roll_call_id   text not null references core.roll_call on delete cascade,
    bioguide_id    text not null references core.member,
    position       text not null
                   check (position in ('yea', 'nay', 'present', 'not_voting', 'other')),
    raw_position   text not null,
    party          text,                 -- as listed on the vote record
    state          char(2),
    primary key (roll_call_id, bioguide_id)
);
create index on core.member_vote (bioguide_id);

------------------------------------------------------------------------
-- Operations: what was downloaded and what each job did
------------------------------------------------------------------------

create table core.raw_file (
    sha256        text primary key,
    source        text not null,
    url           text,
    local_path    text not null,
    fetched_at    timestamptz not null default now(),
    bytes         bigint
);

create table core.ingest_run (
    run_id        bigserial primary key,
    job           text not null,
    started_at    timestamptz not null default now(),
    finished_at   timestamptz,
    status        text not null default 'running'
                  check (status in ('running', 'succeeded', 'failed')),
    rows_written  integer,
    message       text
);
