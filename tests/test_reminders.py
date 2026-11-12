"""Reminder emails: when each item reminds, yearly roll-over, one email a day, nothing sent twice."""

from datetime import date

import pytest

from congress_congruence import reminders as r


def item(**kw):
    return {"id": "x", "title": "Do the thing", "details": "Steps.", "due": date(2026, 12, 10), **kw}


def test_reminds_on_lead_days_then_weekly_when_overdue():
    it = item()
    days = [date(2026, 11, 26), date(2026, 12, 7), date(2026, 12, 10), date(2026, 12, 17), date(2026, 12, 24)]
    assert all(r.reminds_today(it, d)[0] for d in days)
    assert not any(r.reminds_today(it, d)[0] for d in (date(2026, 11, 27), date(2026, 12, 11), date(2026, 12, 16)))
    assert not r.reminds_today(item(done=True), date(2026, 12, 10))[0]
    assert [d.day for d in (date(2026, 12, n) for n in range(1, 11)) if r.reminds_today(item(lead_days=[0]), d)[0]] == [10]


def test_yearly_items_roll_over_and_never_nag():
    it = item(due=date(2027, 11, 1), repeat="yearly", lead_days=[30, 0], done=True)
    assert r.reminds_today(it, date(2027, 10, 2)) == (True, date(2027, 11, 1))
    assert r.next_due(it, date(2027, 11, 8)) == date(2027, 11, 1)          # still this year within the grace week
    assert r.next_due(it, date(2027, 11, 9)) == date(2028, 11, 1)
    assert r.reminds_today(it, date(2028, 10, 2)) == (True, date(2028, 11, 1))
    assert not r.reminds_today(it, date(2027, 11, 8))[0]                    # no overdue nagging


def test_one_email_a_day_and_nothing_sent_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "sent_log_path", lambda: tmp_path / "sent.json")
    monkeypatch.setenv("FEEDBACK_SMTP_USER", "feedback@uscongressvsvoters.org")
    monkeypatch.setenv("FEEDBACK_SMTP_PASSWORD", "x")
    monkeypatch.setenv("FEEDBACK_TO", "contact@uscongressvsvoters.org")
    monkeypatch.setenv("REMINDERS_TO", "someone@example.org")
    items = [item(id="a", title="First"), item(id="b", title="Second", due=date(2026, 12, 13)), item(id="c", due=date(2027, 1, 1))]
    sent = []
    assert r.run(date(2026, 12, 10), sender=lambda m, c: sent.append(m), items=items) == 2
    (msg,) = sent
    assert msg["To"] == "someone@example.org" and msg["Subject"] == "Reminders: First and 1 more"
    body = msg.get_content()
    assert "First: due today" in body and "Second: due in 3 days (December 13, 2026)" in body and "Steps." in body
    assert r.run(date(2026, 12, 10), sender=lambda m, c: sent.append(m), items=items) == 0     # already sent today
    assert len(sent) == 1


def test_needs_mail_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "sent_log_path", lambda: tmp_path / "sent.json")
    for k in ("FEEDBACK_SMTP_USER", "FEEDBACK_SMTP_PASSWORD", "FEEDBACK_TO", "REMINDERS_TO"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match="Mail isn't set up"):
        r.run(date(2026, 12, 10), items=[item()])


def test_reminders_file_is_well_formed():
    items = r.load_items()
    assert len({i["id"] for i in items}) == len(items) >= 5
    for i in items:
        assert i["details"].strip() and i["title"]
        assert all(isinstance(d, int) and d >= 0 for d in i.get("lead_days", r.DEFAULT_LEAD_DAYS))
    assert "security-txt" in r.listing(date(2026, 11, 10), items)


def test_calendar_feed():
    from datetime import datetime, timezone
    items = [item(id="a", title="Check the domains, renewals; and \\ things", lead_days=[14, 3, 0]),
             item(id="b", done=True),
             item(id="c", due=date(2026, 11, 1)),                                   # overdue
             item(id="d", due=date(2027, 11, 1), repeat="yearly", lead_days=[30, 7, 0], done=True),
             item(id="e", details="x" * 200)]
    ics = r.calendar(items, today=date(2026, 11, 12), now=datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc))
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))
    events = ics.split("BEGIN:VEVENT")[1:]
    uids = [e.split("UID:")[1].split("@")[0] for e in events]
    assert uids == ["a", "c", "d", "e"]                                             # done one left out
    a, c, d, e = events
    assert r"SUMMARY:Check the domains\, renewals\; and \\ things" in a
    assert "DTSTART;VALUE=DATE:20261210" in a and "DTEND;VALUE=DATE:20261211" in a
    assert [l for l in a.split("\r\n") if l.startswith("TRIGGER")] == ["TRIGGER:-P13DT15H", "TRIGGER:-P2DT15H", "TRIGGER:PT9H"]
    assert "DTSTART;VALUE=DATE:20261112" in c and "SUMMARY:Overdue: Do the thing" in c and "Was due November 1" in c
    assert c.count("TRIGGER") == 1
    assert "RRULE:FREQ=YEARLY" in d and "DTSTART;VALUE=DATE:20271101" in d
    assert "\r\n " in e                                                             # long line folded


def test_emails_can_be_switched_off(monkeypatch, tmp_path):
    monkeypatch.setenv("REMINDERS_EMAIL", "off")
    monkeypatch.setattr(r, "sent_log_path", lambda: tmp_path / "sent.json")
    sent = []
    assert r.run(today=date(2026, 12, 10), items=[item()], sender=lambda m, c: sent.append(m)) == 0
    assert not sent


def test_calendar_rejoins_wrapped_lines_but_keeps_commands():
    assert r._reflow("Check the\nrenewal date.\n  curl -sI https://x\nThen done.") == \
        "Check the renewal date.\n  curl -sI https://x\nThen done."
