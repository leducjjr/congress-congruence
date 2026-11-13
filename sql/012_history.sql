-- Historical records, 1789-1972 (1st to 92nd Congresses), from Voteview: the site's /history/ section.
-- Kept in their own schema, apart from core, because the record differs (historical parties, changing
-- seats, short clerk descriptions, no surveys or topics) and so the main site's tables stay small.
--
-- Votes are stored one row per member per Congress: `casts` holds one character per roll call, in
-- roll-call order (character 1 is roll call 1), using Voteview's cast codes:
--   1 Yea  2 Paired Yea  3 Announced Yea  4 Announced Nay  5 Paired Nay  6 Nay
--   7 Present  8 Present (avoid conflict)  9 Not Voting  0 not a member at the time
-- Totals per member are worked out once when a Congress is loaded (ingest/history.py).

create schema if not exists history;

create table history.party (
    party_code integer primary key,
    name       text not null
);

create table history.member (
    icpsr       integer primary key,          -- Voteview's ID; a member who changed party may have two
    bioguide_id text,                         -- links to core.member / the main site where they match
    name        text not null,                -- as Voteview gives it: "LINCOLN, Abraham"
    born        smallint,
    died        smallint
);
create index on history.member (bioguide_id);

create table history.roll_call (
    chamber         text not null check (chamber in ('house', 'senate')),
    congress        smallint not null,
    rollnumber      smallint not null,        -- Voteview's number, through the whole Congress
    session         smallint,
    clerk_rollnumber smallint,
    vote_date       date not null,
    yea_count       smallint,
    nay_count       smallint,
    result          text,
    question        text,
    description     text,
    bill_number     text,
    totals_match    boolean,                  -- the members' votes add up to Voteview's published totals
    primary key (chamber, congress, rollnumber)
);
create index on history.roll_call (vote_date);

create table history.member_congress (
    chamber     text not null check (chamber in ('house', 'senate')),
    congress    smallint not null,
    icpsr       integer not null references history.member,
    state       text,
    district    smallint,                     -- 0 or null: at large / statewide; Voteview's numbering
    party_code  integer,
    casts       text not null,                -- see above
    votes_total integer not null,             -- roll calls while a member
    yea         integer not null,
    nay         integer not null,
    present     integer not null,
    not_voting  integer not null,             -- includes paired and announced
    party_votes integer not null,             -- votes where their party's majority took a side
    with_party  integer not null,
    first_vote  date,
    last_vote   date,
    primary key (chamber, congress, icpsr)
);
create index on history.member_congress (icpsr);

create table history.load_run (
    chamber    text not null,
    congress   smallint not null,
    loaded_at  timestamptz not null default now(),
    roll_calls integer not null,
    members    integer not null,
    totals_mismatched integer not null,
    primary key (chamber, congress)
);

-- The API's read-only login, where it exists (deploy/README.md, step 3).
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'ccapi') then
        grant usage on schema history to ccapi;
        grant select on all tables in schema history to ccapi;
    end if;
end $$;
