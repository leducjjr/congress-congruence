-- An appointed senator serves until the winner of the special election is sworn in, but the member
-- list ends the appointment on election day. Until the list adds a successor, the loader keeps the
-- appointment running (end_date = the seat's regular end) and keeps the list's own date here.
alter table core.term add column listed_end_date date;
