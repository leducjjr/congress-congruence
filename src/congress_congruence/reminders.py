"""Reminder emails for dated chores, sent from the server with the site's own mail account.

    python -m congress_congruence.reminders            # send today's reminders (the daily cron job)
    python -m congress_congruence.reminders --list     # every item and when it next reminds
    python -m congress_congruence.reminders --dry-run  # show today's email without sending it

The items live in config/reminders.yaml: id, title, due (a date), what to do (details), optional
lead_days (when to remind before the due date; default 14, 3 and 0) and optional repeat: yearly.
An item reminds on each lead day and, once overdue, every 7 days until it's marked `done: true`.
A yearly item instead moves on to next year's date a week after it falls due.

All of a day's reminders go out as one email, To: REMINDERS_TO from .env (kept out of the public
code, so it can be a private address), or FEEDBACK_TO if that isn't set. It's sent through the
contact form's mailbox (FEEDBACK_SMTP_USER / FEEDBACK_SMTP_PASSWORD). What has been sent is noted
in logs/reminders-sent.json, so running twice in a day sends nothing new.
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

DEFAULT_LEAD_DAYS = (14, 3, 0)
OVERDUE_EVERY = 7          # days between reminders once an item is overdue
YEARLY_GRACE = 7           # a yearly item moves to next year this many days after it falls due


def load_items(path=None) -> list[dict]:
    path = path or config.PROJECT_ROOT / "config" / "reminders.yaml"
    items = yaml.safe_load(path.read_text())["items"]
    seen = set()
    for it in items:
        missing = {"id", "title", "due", "details"} - set(it)
        if missing:
            raise ValueError(f"reminder {it.get('id', '?')}: missing {sorted(missing)}")
        if it["id"] in seen:
            raise ValueError(f"reminder id {it['id']} is listed twice")
        seen.add(it["id"])
        if not isinstance(it["due"], date):
            it["due"] = date.fromisoformat(str(it["due"]))
        if it.get("repeat") not in (None, "yearly"):
            raise ValueError(f"reminder {it['id']}: repeat must be 'yearly' or left out")
    return items


def next_due(item: dict, today: date) -> date:
    """The date an item is next due: its own date, or for a yearly item the first yearly date
    that isn't more than YEARLY_GRACE days past."""
    due = item["due"]
    if item.get("repeat") == "yearly":
        while due + timedelta(days=YEARLY_GRACE) < today:
            try:
                due = due.replace(year=due.year + 1)
            except ValueError:                       # Feb 29
                due = due.replace(year=due.year + 1, day=28)
    return due


def reminds_today(item: dict, today: date) -> tuple[bool, date]:
    """Whether an item reminds today, and the due date it's about."""
    due = next_due(item, today)
    if item.get("done") and item.get("repeat") != "yearly":
        return False, due
    days_left = (due - today).days
    leads = item.get("lead_days", DEFAULT_LEAD_DAYS)
    if days_left in leads:
        return True, due
    if days_left < 0 and item.get("repeat") != "yearly":
        return (-days_left) % OVERDUE_EVERY == 0, due
    return False, due


def when(due: date, today: date) -> str:
    d = (due - today).days
    if d == 0:
        return "due today"
    if d > 0:
        return f"due in {d} day{'s' if d != 1 else ''} ({due:%B %-d, %Y})"
    return f"overdue by {-d} day{'s' if d != -1 else ''} (was due {due:%B %-d, %Y})"


def build_email(due_items: list[tuple[dict, date]], today: date, to: str, sender: str) -> EmailMessage:
    msg = EmailMessage()
    n = len(due_items)
    first = due_items[0][0]["title"]
    msg["Subject"] = (f"Reminder: {first}" if n == 1 else f"Reminders: {first} and {n - 1} more")
    msg["From"] = formataddr(("US Congress vs Voters reminders", sender))
    msg["To"] = to
    msg["Auto-Submitted"] = "auto-generated"
    lines = [f"Reminders for {today:%A, %B %-d, %Y}.", ""]
    for item, due in sorted(due_items, key=lambda x: x[1]):
        lines += [f"* {item['title']}: {when(due, today)}", "", *[f"  {l}" for l in item["details"].strip().splitlines()], ""]
    lines += ["To stop a reminder, set `done: true` for it in config/reminders.yaml (yearly items move on",
              "by themselves). The list: https://github.com/leducjjr/congress-congruence/blob/main/config/reminders.yaml"]
    msg.set_content("\n".join(lines))
    return msg


def sent_log_path():
    return config.PROJECT_ROOT / "logs" / "reminders-sent.json"


def run(today: date | None = None, dry_run: bool = False, sender=None, items=None) -> int:
    today = today or date.today()
    items = items if items is not None else load_items()
    path = sent_log_path()
    try:
        sent = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        sent = {}
    due_items = []
    for it in items:
        yes, due = reminds_today(it, today)
        if yes and sent.get(it["id"]) != today.isoformat():
            due_items.append((it, due))
    if not due_items:
        log.info("No reminders today (%s)", today)
        return 0
    from .api import feedback
    cfg = feedback.settings()
    to = os.environ.get("REMINDERS_TO", "").strip() or (cfg or {}).get("to")
    if not cfg or not to:
        raise RuntimeError("Mail isn't set up: FEEDBACK_SMTP_USER, FEEDBACK_SMTP_PASSWORD and FEEDBACK_TO "
                           "(or REMINDERS_TO) must be in .env")
    msg = build_email(due_items, today, to, cfg["user"])
    if dry_run:
        print(msg)
        return len(due_items)
    (sender or feedback.send)(msg, cfg)
    for it, _ in due_items:
        sent[it["id"]] = today.isoformat()
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(sent, indent=1, sort_keys=True) + "\n")
    log.info("Sent %d reminder(s) to %s", len(due_items), to)
    return len(due_items)


def listing(today: date | None = None, items=None) -> str:
    today = today or date.today()
    rows = []
    for it in items if items is not None else load_items():
        due = next_due(it, today)
        state = "done" if it.get("done") and it.get("repeat") != "yearly" else when(due, today)
        rows.append((due, f"{due}  {it['id']:<24} {state}{'  (yearly)' if it.get('repeat') else ''}\n            {it['title']}"))
    return "\n".join(r for _, r in sorted(rows))


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = argv[1:]
    if args == ["--list"]:
        print(listing())
        return 0
    if args not in ([], ["--dry-run"]):
        print(__doc__)
        return 2
    run(dry_run=bool(args))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
