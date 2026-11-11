-- How each party's members voted on each roll call: yea or nay, whichever more of them chose
-- (null on a tie). "Party" is the caucus where it differs (independents). Worked out once when a
-- vote loads (congress_congruence.party), instead of on every member page, where it took about two
-- seconds per Congress. The member figures still work it out on the spot for any roll call not
-- listed here, so a missing row is slow, never wrong.
create table core.party_position (
    roll_call_id  text not null references core.roll_call on delete cascade,
    grp           text not null,
    position      text check (position in ('yea', 'nay')),
    primary key (roll_call_id, grp)
);

insert into core.party_position (roll_call_id, grp, position)
select v.roll_call_id, coalesce(t.caucus, t.party),
       case when count(*) filter (where v.position = 'yea') > count(*) filter (where v.position = 'nay') then 'yea'
            when count(*) filter (where v.position = 'nay') > count(*) filter (where v.position = 'yea') then 'nay'
       end
  from core.member_vote v
  join core.roll_call r using (roll_call_id)
  join core.term t on t.bioguide_id = v.bioguide_id and t.chamber = r.chamber
                  and r.vote_date between t.start_date and t.end_date
 where coalesce(t.caucus, t.party) is not null
 group by 1, 2;
