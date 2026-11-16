-- Faster search and All votes.
--
-- 1. Each vote's search words, stored and indexed, instead of being worked out for every vote on every
--    search: its title and question, the bill number, and the bill's official title, policy area and
--    subject tags from Congress.gov. title_doc is the same without the subject tags (votes matching
--    there are listed first). Kept current by a trigger on core.roll_call, and refreshed in full after
--    each Congress.gov bills run (ingest/votes.record_run), since bill titles and tags arrive later.
-- 2. An index for looking up a member's term on a vote date ("how each party voted").

create index if not exists term_member_chamber on core.term (bioguide_id, chamber, start_date);

create table core.vote_search (
    roll_call_id text primary key references core.roll_call on delete cascade,
    doc          tsvector not null,
    title_doc    tsvector not null
);
create index vote_search_doc on core.vote_search using gin (doc);

-- The words for the given votes (all of them when ids is null).
create function core.vote_search_docs(ids text[]) returns table (roll_call_id text, doc tsvector, title_doc tsvector)
language sql stable as $$
    select r.roll_call_id,
           to_tsvector('english', words.title || ' ' || coalesce(bs.subjects, '')),
           to_tsvector('english', words.title)
      from core.roll_call r
      left join core.bill b on b.congress = coalesce(r.bill_congress, r.congress)
                           and b.bill_type = r.bill_type and b.bill_number = r.bill_number
      left join lateral (select string_agg(s.subject, ' | ' order by s.subject) as subjects
                           from core.bill_subject s
                          where s.congress = b.congress and s.bill_type = b.bill_type
                            and s.bill_number = b.bill_number) bs on true
      cross join lateral (select coalesce(r.description, '') || ' ' || coalesce(r.question, '') || ' ' ||
                                 coalesce(r.bill_type || ' ' || r.bill_number || ' ' || r.bill_type || r.bill_number, '') || ' ' ||
                                 coalesce(b.title, '') || ' ' || coalesce(b.policy_area, '') as title) words
     where ids is null or r.roll_call_id = any(ids)
$$;

-- Bring every vote's words up to date; returns how many changed.
create function core.refresh_vote_search() returns integer language sql as $$
    with up as (
        insert into core.vote_search (roll_call_id, doc, title_doc)
        select * from core.vote_search_docs(null)
        on conflict (roll_call_id) do update set doc = excluded.doc, title_doc = excluded.title_doc
         where core.vote_search.doc is distinct from excluded.doc
            or core.vote_search.title_doc is distinct from excluded.title_doc
        returning 1)
    select count(*)::integer from up
$$;

create function core.vote_search_row() returns trigger language plpgsql as $$
begin
    insert into core.vote_search (roll_call_id, doc, title_doc)
    select * from core.vote_search_docs(array[new.roll_call_id])
    on conflict (roll_call_id) do update set doc = excluded.doc, title_doc = excluded.title_doc;
    return null;
end $$;

create trigger vote_search_row after insert or update on core.roll_call
    for each row execute function core.vote_search_row();

select core.refresh_vote_search();

-- The API's read-only login, where it exists (deploy/README.md, step 3).
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'ccapi') then
        grant select on core.vote_search to ccapi;
    end if;
end $$;
