"""Vote watch: which new votes are flagged for review, and the email that lists them."""

from datetime import date

from congress_congruence import vote_watch as w


def vote(rid, **kw):
    return {"roll_call_id": rid, "chamber": "senate", "vote_date": date(2026, 11, 19), "roll_number": 269,
            "question": "On the Concurrent Resolution", "result": "Concurrent Resolution Rejected",
            "yea_total": 48, "nay_total": 51, "description": "", "source_url": "https://www.senate.gov/x",
            "bill_type": "hconres", "bill_number": 93, "bill_congress": 119, "bill_title": None, **kw}


TOPICS = [{"id": "iran", "title": "Iran war powers", "chamber": "senate", "words": ["Iran"], "check": "Update the count."}]
MATCHED = [{"bill_congress": 119, "bill_type": "hr", "bill_number": 1, "roll_call_id": "s-old",
            "survey": "UNH 2025-07", "question": "Support the One Big Beautiful Bill Act"}]


def test_topic_words_and_chamber():
    iran = vote("s-1", bill_title="A concurrent resolution directing the President ... hostilities with Iran.")
    assert w.topic_matches(TOPICS[0], iran)
    assert not w.topic_matches(TOPICS[0], {**iran, "chamber": "house"})
    assert not w.topic_matches(TOPICS[0], vote("s-2", bill_title="Earth MRI Reauthorization Act"))


def test_findings_flag_same_bill_and_topics_once():
    iran = vote("s-1", bill_title="... hostilities with Iran.")
    same_bill = vote("s-2", bill_type="hr", bill_number=1, bill_title="One Big Beautiful Bill Act")
    other = vote("s-3", bill_type="hr", bill_number=9640, bill_title="Earth MRI Reauthorization Act")
    compared = vote("s-old", bill_type="hr", bill_number=1)            # the vote already compared: not new news
    found = w.findings([iran, same_bill, other, compared], MATCHED, TOPICS, seen=set())
    assert [f["vote"]["roll_call_id"] for f in found] == ["s-1", "s-2"]
    assert "Iran war powers: Update the count." in found[0]["reasons"]
    assert "UNH 2025-07: Support the One Big Beautiful Bill Act" in found[1]["reasons"][0]
    assert w.findings([iran], MATCHED, TOPICS, seen={"s-1"}) == []     # reported once


def test_email_lists_each_vote_with_links():
    found = w.findings([vote("s-1", bill_title="... Iran.")], [], TOPICS, set())
    text = w.build_email(found, date(2026, 11, 20), "me@example.org", "bot@example.org").get_content()
    assert "Senate roll call 269, Nov 19, 2026: HCONRES 93" in text
    assert "votes.html?chamber=senate&q=hconres93" in text and "https://www.senate.gov/x" in text
    assert "Nothing on the site has" in text


def test_shipped_topics_load():
    assert {t["id"] for t in w.load_topics()} >= {"iran-war-powers"}


def test_run_records_first_then_emails_new_votes(monkeypatch, tmp_path):
    import os
    import pytest
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    from congress_congruence import db
    monkeypatch.setattr(w, "state_path", lambda: tmp_path / "vote-watch.json")
    sent = []
    with db.connect(os.environ["TEST_DATABASE_URL"]) as c:
        with c.cursor() as cur:
            cur.execute("drop schema if exists core, history cascade")
        c.commit()
        db.migrate(c)

        def add(rid, roll, desc):
            with c.cursor() as cur:
                cur.execute("""insert into core.roll_call (roll_call_id, chamber, congress, session, roll_number,
                               vote_date, question, result, yea_total, nay_total, description, source)
                               values (%s, 'senate', 119, 2, %s, '2026-11-19', 'On the Concurrent Resolution',
                                       'Rejected', 48, 51, %s, 'senate_lis')""", (rid, roll, desc))
            c.commit()

        add("s-119-2-268", 268, "A resolution about Iran")
        assert w.run(c, today=date(2026, 11, 20), topics=TOPICS, sender=lambda m, cfg: sent.append(m)) == 0
        assert not sent                                                    # first run only records
        add("s-119-2-269", 269, "Hostilities with Iran")
        monkeypatch.setattr("congress_congruence.api.feedback.settings",
                            lambda: {"user": "bot@example.org", "to": "me@example.org"})
        assert w.run(c, today=date(2026, 11, 20), topics=TOPICS, sender=lambda m, cfg: sent.append(m)) == 1
        assert "roll call 269" in sent[0].get_content() and "roll call 268" not in sent[0].get_content()
        assert w.run(c, today=date(2026, 11, 20), topics=TOPICS, sender=lambda m, cfg: sent.append(m)) == 0
