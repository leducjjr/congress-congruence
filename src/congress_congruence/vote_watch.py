"""Emails the maintainer when a newly loaded vote may need a look: a matched survey question could
have a better (or another) vote to compare with, or a reader-facing note counts votes that just grew.

    python -m congress_congruence.vote_watch            # check and email (the daily cron job)
    python -m congress_congruence.vote_watch --dry-run  # show what would be emailed, change nothing

Two kinds of watch:

1. Automatic. Any new vote on a bill that a survey question is already compared with (another vote
   on the same measure: a later passage vote, a veto override, the other chamber's vote).
2. Topics in config/vote_watch.yaml: words to look for in new votes' titles and questions, and what
   to check when one appears (for example, the Iran notes count the Senate's war powers votes).

Nothing on the site changes: the email only asks for a review, and any change still goes through
the maintainer's approval. The first run only records the votes already loaded. What has been
reported is kept in logs/vote-watch.json, so each vote is reported once. Mail settings and the
address are the reminders' (REMINDERS_TO or FEEDBACK_TO; VOTE_WATCH_EMAIL=off sends nothing).
"""

import json
import logging
import os
import sys
from datetime import date, timedelta
from email.message import EmailMessage
from email.utils import formataddr

import yaml

from . import config

log = logging.getLogger(__name__)

LOOK_BACK_DAYS = 30        # only votes this recent are considered (older ones were already seen)

NEW_VOTES = """
select r.roll_call_id, r.chamber, r.vote_date, r.roll_number, r.question, r.result,
       r.yea_total, r.nay_total, r.description, r.source_url, r.bill_type, r.bill_number,
       coalesce(r.bill_congress, r.congress) as bill_congress, b.title as bill_title
  from core.roll_call r
  left join core.bill b on b.congress = coalesce(r.bill_congress, r.congress)
                       and b.bill_type = r.bill_type and b.bill_number = r.bill_number
 where r.vote_date >= %(since)s
 order by r.vote_date, r.chamber, r.roll_number
"""

# The bills survey questions are compared with, and which questions.
MATCHED_BILLS = """
select coalesce(r.bill_congress, r.congress) as bill_congress, r.bill_type, r.bill_number,
       v.roll_call_id, v.survey, si.question
  from core.survey_item_vote v
  join core.survey_item si using (survey, variable)
  join core.roll_call r using (roll_call_id)
 where r.bill_type is not null
"""


def load_topics(path=None) -> list[dict]:
    path = path or config.PROJECT_ROOT / "config" / "vote_watch.yaml"
    topics = (yaml.safe_load(path.read_text()) or {}).get("topics") or []
    for t in topics:
        missing = {"id", "title", "words", "check"} - set(t)
        if missing:
            raise ValueError(f"vote watch topic {t.get('id', '?')}: missing {sorted(missing)}")
        if t.get("chamber") not in (None, "house", "senate"):
            raise ValueError(f"vote watch topic {t['id']}: chamber must be house or senate")
    return topics


def bill_key(row: dict):
    return (row["bill_congress"], row["bill_type"], row["bill_number"]) if row.get("bill_type") else None


def vote_text(v: dict) -> str:
    return " ".join(str(v.get(k) or "") for k in ("description", "bill_title", "question")).lower()


def topic_matches(topic: dict, v: dict) -> bool:
    if topic.get("chamber") and topic["chamber"] != v["chamber"]:
        return False
    text = vote_text(v)
    return any(w.lower() in text for w in topic["words"])


def findings(votes: list[dict], matched: list[dict], topics: list[dict], seen: set[str]) -> list[dict]:
    """One entry per new vote that needs a look, with the reasons."""
    by_bill: dict = {}
    for m in matched:
        by_bill.setdefault(bill_key(m), []).append(m)
    compared = {m["roll_call_id"] for m in matched}
    out = []
    for v in votes:
        if v["roll_call_id"] in seen or v["roll_call_id"] in compared:
            continue
        reasons = []
        same = by_bill.get(bill_key(v)) if bill_key(v) else None
        if same:
            qs = sorted({f"{m['survey']}: {m['question']}" for m in same})
            reasons.append("Another vote on a bill that survey questions are compared with. Check whether "
                           "it's a closer match, or worth a mention in the note:\n" + "\n".join(f"    - {q}" for q in qs))
        for t in topics:
            if topic_matches(t, v):
                reasons.append(f"{t['title']}: {t['check'].strip()}")
        if reasons:
            out.append({"vote": v, "reasons": reasons})
    return out


def describe(v: dict) -> str:
    bill = f"{v['bill_type'].upper()} {v['bill_number']}: " if v.get("bill_type") else ""
    title = v.get("bill_title") or v.get("description") or ""
    tally = f"{v['yea_total']}-{v['nay_total']}" if v.get("yea_total") is not None else ""
    return (f"{v['chamber'].title()} roll call {v['roll_number']}, {v['vote_date']:%b %-d, %Y}: {bill}{title}\n"
            f"  {v.get('question') or ''}: {v.get('result') or ''} {tally}".rstrip())


def build_email(found: list[dict], today: date, to: str, sender: str) -> EmailMessage:
    msg = EmailMessage()
    n = len(found)
    msg["Subject"] = f"Votes to review: {n} new vote{'s' if n != 1 else ''} may affect survey matches or notes"
    msg["From"] = formataddr(("US Congress vs Voters vote watch", sender))
    msg["To"] = to
    msg["Auto-Submitted"] = "auto-generated"
    lines = [f"New votes loaded up to {today:%A, %B %-d, %Y} that may need a look. Nothing on the site has",
             "changed; any update still needs your approval.", ""]
    for f in found:
        lines += [describe(f["vote"]), ""]
        lines += [f"  Why: {r}" for r in f["reasons"]]
        v = f["vote"]
        if v.get("bill_type"):
            lines.append(f"  On the site: https://uscongressvsvoters.org/votes.html?chamber={v['chamber']}"
                         f"&q={v['bill_type']}{v['bill_number']}")
        if v.get("source_url"):
            lines.append(f"  Official record: {v['source_url']}")
        lines.append("")
    lines += ["Topics to watch are in config/vote_watch.yaml:",
              "https://github.com/uscongressvsvoters/congress-congruence/blob/main/config/vote_watch.yaml"]
    msg.set_content("\n".join(lines))
    return msg


def state_path():
    return config.PROJECT_ROOT / "logs" / "vote-watch.json"


def run(conn, today: date | None = None, dry_run: bool = False, sender=None, topics=None) -> int:
    today = today or date.today()
    topics = topics if topics is not None else load_topics()
    path = state_path()
    try:
        state = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        state = {}
    first_run = "seen" not in state
    seen = set(state.get("seen", []))
    since = today - timedelta(days=LOOK_BACK_DAYS)
    with conn.cursor() as cur:
        cur.execute(NEW_VOTES, {"since": since})
        cols = [c.name for c in cur.description]
        votes = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.execute(MATCHED_BILLS)
        cols = [c.name for c in cur.description]
        matched = [dict(zip(cols, row)) for row in cur.fetchall()]
    found = [] if first_run else findings(votes, matched, topics, seen)

    def save():
        recent = {v["roll_call_id"] for v in votes}
        state["seen"] = sorted(recent | {s for s in seen if s in recent})
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(state, indent=1) + "\n")

    if first_run:
        log.info("First run: recorded %d recent votes; from now on, new ones are checked", len(votes))
        if not dry_run:
            save()
        return 0
    if not found:
        log.info("No new votes need a look (%d recent votes checked)", len(votes))
        if not dry_run:
            save()
        return 0
    if os.environ.get("VOTE_WATCH_EMAIL", "").strip().lower() == "off" and not dry_run:
        for f in found:
            log.info("Needs a look: %s", describe(f["vote"]).splitlines()[0])
        save()
        return len(found)
    from .api import feedback
    cfg = feedback.settings()
    to = os.environ.get("REMINDERS_TO", "").strip() or (cfg or {}).get("to")
    if not dry_run and (not cfg or not to):
        raise RuntimeError("Mail isn't set up: FEEDBACK_SMTP_USER, FEEDBACK_SMTP_PASSWORD and FEEDBACK_TO "
                           "(or REMINDERS_TO) must be in .env")
    msg = build_email(found, today, to or "maintainer", (cfg or {}).get("user", "vote-watch"))
    if dry_run:
        print(msg)
        return len(found)
    (sender or feedback.send)(msg, cfg)
    save()
    log.info("Emailed %d vote(s) to review to %s", len(found), to)
    return len(found)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = argv[1:]
    if args not in ([], ["--dry-run"]):
        print(__doc__)
        return 2
    from .db import connect
    with connect() as conn:
        run(conn, dry_run=bool(args))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
