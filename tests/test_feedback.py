"""The feedback form: checks, spam defences, and that messages are emailed and never stored."""

import smtplib

import pytest

from congress_congruence.api import feedback as fb

GOOD = {"kind": "error", "message": "The vote on H.R. 1 shows the wrong date.", "reply_to": "",
        "page": "https://dev.uscongressvsvoters.org/index.html#TX/C001098", "member": "c001098",
        "member_name": "Ted Cruz", "website": "", "seconds_open": 12}


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("FEEDBACK_SMTP_USER", "feedback@uscongressvsvoters.org")
    monkeypatch.setenv("FEEDBACK_SMTP_PASSWORD", "pw")
    monkeypatch.setenv("FEEDBACK_TO", "contact@uscongressvsvoters.org")
    monkeypatch.setattr(fb, "limiter", fb.RateLimiter(fb.PER_HOUR, fb.GLOBAL_PER_HOUR))
    monkeypatch.setattr(fb, "copy_limiter", fb.RateLimiter(fb.COPIES_PER_ADDRESS, fb.COPIES_PER_HOUR))


def sent_messages(data, client="203.0.113.5"):
    out = []
    fb.submit(data, client, sender=lambda msg, cfg: out.append(msg))
    return out


def test_a_good_message_is_emailed_to_the_inbox():
    (msg,) = sent_messages(GOOD)
    assert msg["To"] == "contact@uscongressvsvoters.org" and "feedback@" in msg["From"]
    assert msg["Subject"] == "[Site feedback] Error report about Ted Cruz"
    body = msg.get_content()
    assert "wrong date" in body and "Member: Ted Cruz (C001098)" in body and "#TX/C001098" in body
    assert "stay anonymous" in body and msg["Reply-To"] is None
    assert "203.0.113.5" not in msg.as_string()                       # the sender's address isn't passed on


def test_reply_address_becomes_reply_to_and_gets_a_copy():
    msg, copy = sent_messages({**GOOD, "reply_to": "pat@example.com"})
    assert msg["Reply-To"] == "pat@example.com"
    assert copy["To"] == "pat@example.com" and copy["Reply-To"] == "contact@uscongressvsvoters.org"
    assert copy["From"] == "US Congress vs Voters <feedback@uscongressvsvoters.org>"
    assert copy["Subject"] == "Your message to US Congress vs Voters: Error report about Ted Cruz"
    body = copy.get_content()
    assert "wrong date" in body and "Member: Ted Cruz (C001098)" in body and "If you didn't send this" in body
    assert "203.0.113.5" not in copy.as_string()


def test_no_address_no_copy_and_copy_from_setting(monkeypatch):
    assert len(sent_messages(GOOD)) == 1
    monkeypatch.setenv("FEEDBACK_COPY_FROM", "contact@uscongressvsvoters.org")
    _, copy = sent_messages({**GOOD, "reply_to": "pat@example.com"})
    assert copy["From"] == "US Congress vs Voters <contact@uscongressvsvoters.org>"


def test_copies_are_limited_per_address_and_never_block_the_message():
    data = {**GOOD, "reply_to": "Victim@example.com"}
    results = []
    for i in range(fb.COPIES_PER_ADDRESS + 1):
        out = []
        results.append(fb.submit({**data, "reply_to": data["reply_to"] if i % 2 else "victim@EXAMPLE.com"},
                                 f"203.0.113.{i}", sender=lambda m, c: out.append(m)))
        assert out[0]["To"] == "contact@uscongressvsvoters.org"            # the message itself always goes
    assert [r["copy_sent"] for r in results] == [True] * fb.COPIES_PER_ADDRESS + [False]

    def copy_fails(msg, cfg):
        if msg["To"] != "contact@uscongressvsvoters.org":
            raise smtplib.SMTPRecipientsRefused({})
    assert fb.submit({**GOOD, "reply_to": "other@example.com"}, "x", sender=copy_fails) == {"copy_sent": False}


@pytest.mark.parametrize("change, status", [
    ({"website": "http://spam.example"}, 400),           # hidden field filled: a bot
    ({"seconds_open": 1}, 400),                          # sent too quickly
    ({"message": "hi"}, 400),
    ({"message": "x" * (fb.MAX_MESSAGE + 1)}, 400),
    ({"reply_to": "not an address"}, 400),
    ({"reply_to": "a@b.com\nBcc: everyone@example.com"}, 400),   # header injection
])
def test_rejections(change, status):
    with pytest.raises(fb.Rejected) as e:
        sent_messages({**GOOD, **change})
    assert e.value.status == status


def test_injected_text_in_names_and_pages_stays_on_one_line():
    (msg,) = sent_messages({**GOOD, "member_name": "Ted\r\nBcc: x@example.com", "page": "a\nb"})
    assert "\n" not in msg["Subject"] and msg["Bcc"] is None


def test_rate_limits_per_connection_and_overall():
    for _ in range(fb.PER_HOUR):
        sent_messages(GOOD)
    with pytest.raises(fb.Rejected) as e:
        sent_messages(GOOD)
    assert e.value.status == 429
    sent_messages(GOOD, client="198.51.100.7")                         # someone else is unaffected
    limiter = fb.RateLimiter(per_key=2, overall=3, window=60)
    assert [limiter.allow(k, now=0) for k in "aabcd"] == [True, True, True, False, False]
    assert limiter.allow("a", now=61) and list(limiter.hits) == ["a"]  # old entries forgotten


def test_not_configured_and_mail_failures(monkeypatch):
    def fail(msg, cfg):
        raise smtplib.SMTPAuthenticationError(535, b"bad")
    with pytest.raises(fb.Rejected) as e:
        fb.submit(GOOD, "x", sender=fail)
    assert e.value.status == 502
    monkeypatch.delenv("FEEDBACK_SMTP_PASSWORD")
    with pytest.raises(fb.Rejected) as e:
        sent_messages(GOOD)
    assert e.value.status == 503


def test_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from congress_congruence.api import app as api
    sent = []
    monkeypatch.setattr(fb, "send", lambda msg, cfg: sent.append(msg))
    client = TestClient(api.app)                       # no "with": the database pool isn't needed
    ok = client.post("/v1/feedback", json=GOOD)
    assert ok.status_code == 200 and ok.json() == {"ok": True, "copy_sent": None} and len(sent) == 1
    bad = client.post("/v1/feedback", json={**GOOD, "seconds_open": 0})
    assert bad.status_code == 400 and "quick" in bad.json()["message"]
