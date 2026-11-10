"""The site's feedback form: a visitor's message is emailed to the project inbox and nothing is kept.

POST /v1/feedback (JSON). The message goes by email from a send-only mailbox (feedback@) to the
public inbox (contact@). It is never written to the database, a file or a log. The API's database
login stays read-only; this endpoint doesn't touch the database at all.

If the visitor gives an email address, they're also sent a copy of what they wrote, with replies
going to the inbox (Reply-To: FEEDBACK_TO), so they have a record and a thread to answer.

Settings (.env):
    FEEDBACK_SMTP_USER       the sending mailbox, e.g. feedback@uscongressvsvoters.org
    FEEDBACK_SMTP_PASSWORD   its password
    FEEDBACK_TO              where messages go, e.g. contact@uscongressvsvoters.org
    FEEDBACK_COPY_FROM       optional: the From address on the visitor's copy (default: the sending
                             mailbox). Set it to contact@ only if the mail service lets the sending
                             mailbox send as that address (see deploy/README.md).
    FEEDBACK_SMTP_HOST       default smtp.titan.email (Bluehost Professional Email)
    FEEDBACK_SMTP_PORT       default 465 (SSL)
Without the first three, the endpoint answers 503 and the page shows the email addresses instead.

Abuse protection, with no tracking and no third-party services:
  - a hidden "website" field that people never see but bots fill in;
  - the form must have been open for a few seconds;
  - length limits on every field, and a reply address must look like one address;
  - at most PER_HOUR messages per connection address and GLOBAL_PER_HOUR in all, counted in
    memory only (never written anywhere) and forgotten after an hour. Each API worker process
    counts separately;
  - copies to visitors: at most COPIES_PER_ADDRESS an hour to any one address and COPIES_PER_HOUR in
    all (same in-memory counting), so the form can't be used to send mail to someone repeatedly.
    The copy says plainly what it is, in case someone else typed the address.
"""

import os
import re
import smtplib
import ssl
import threading
import time
from collections import deque
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr

KINDS = {"error": "Error report", "question": "Question", "suggestion": "Suggestion", "other": "Message"}
MIN_SECONDS_OPEN = 3
PER_HOUR = 5
GLOBAL_PER_HOUR = 60
COPIES_PER_ADDRESS = 2
COPIES_PER_HOUR = 30
MAX_MESSAGE = 4000
EMAIL_RE = re.compile(r"^[^@\s<>\"',;]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")
BIOGUIDE_RE = re.compile(r"^[A-Z]\d{6}$")


class Rejected(Exception):
    """The message can't be accepted; .status is the HTTP status, str() is shown to the visitor."""
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class RateLimiter:
    """Counts recent sends per key in memory; nothing is persisted."""
    def __init__(self, per_key: int, overall: int, window: float = 3600.0):
        self.per_key, self.overall, self.window = per_key, overall, window
        self.hits: dict[str, deque] = {}
        self.all: deque = deque()
        self.lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self.lock:
            cutoff = now - self.window
            while self.all and self.all[0] < cutoff:
                self.all.popleft()
            for k in [k for k, d in self.hits.items() if not d or d[-1] < cutoff]:
                del self.hits[k]                                   # forget quiet addresses entirely
            mine = self.hits.setdefault(key, deque())
            while mine and mine[0] < cutoff:
                mine.popleft()
            if len(mine) >= self.per_key or len(self.all) >= self.overall:
                return False
            mine.append(now)
            self.all.append(now)
            return True


limiter = RateLimiter(PER_HOUR, GLOBAL_PER_HOUR)
copy_limiter = RateLimiter(COPIES_PER_ADDRESS, COPIES_PER_HOUR)
SITE_NAME = "US Congress vs Voters"


def settings() -> dict | None:
    user, password, to = (os.environ.get(k, "").strip() for k in
                          ("FEEDBACK_SMTP_USER", "FEEDBACK_SMTP_PASSWORD", "FEEDBACK_TO"))
    if not (user and password and to):
        return None
    return {"user": user, "password": password, "to": to,
            "copy_from": os.environ.get("FEEDBACK_COPY_FROM", "").strip() or user,
            "host": os.environ.get("FEEDBACK_SMTP_HOST", "smtp.titan.email").strip(),
            "port": int(os.environ.get("FEEDBACK_SMTP_PORT", "465"))}


def one_line(text: str, limit: int) -> str:
    return re.sub(r"[\r\n\t]+", " ", text or "").strip()[:limit]


def check(data: dict) -> dict:
    """Check what was submitted; return the cleaned fields. Raises Rejected."""
    if (data.get("website") or "").strip():
        raise Rejected(400, "Your message couldn't be sent.")              # the hidden field: a bot
    try:
        seconds_open = float(data.get("seconds_open") or 0)
    except (TypeError, ValueError):
        seconds_open = 0
    if seconds_open < MIN_SECONDS_OPEN:
        raise Rejected(400, "That was quick! Please wait a moment and send again.")
    kind = data.get("kind") if data.get("kind") in KINDS else "other"
    message = (data.get("message") or "").strip()
    if len(message) < 5:
        raise Rejected(400, "Please write a little more.")
    if len(message) > MAX_MESSAGE:
        raise Rejected(400, f"Please keep it under {MAX_MESSAGE:,} characters.")
    reply_to = (data.get("reply_to") or "").strip()
    if reply_to and not EMAIL_RE.match(reply_to):
        raise Rejected(400, "That email address doesn't look right. Leave it blank to stay anonymous.")
    page = one_line(data.get("page") or "", 300)
    member = (data.get("member") or "").strip().upper()
    member = member if BIOGUIDE_RE.match(member) else ""
    member_name = one_line(data.get("member_name") or "", 100) if member else ""
    return {"kind": kind, "message": message, "reply_to": reply_to, "page": page,
            "member": member, "member_name": member_name}


def details(f: dict) -> list[str]:
    """The lines under the message: what it's about and where it was sent from."""
    lines = [f"Type: {KINDS[f['kind']]}"]
    if f["member"]:
        lines.append(f"Member: {f['member_name']} ({f['member']})" if f["member_name"] else f"Member: {f['member']}")
    if f["page"]:
        lines.append(f"Sent from: {f['page']}")
    return lines


def subject(f: dict) -> str:
    about = f" about {f['member_name'] or f['member']}" if f["member"] else ""
    return f"{KINDS[f['kind']]}{about}"


def build_message(data: dict, cfg: dict) -> EmailMessage:
    """Check what was submitted and turn it into the email to the inbox. Raises Rejected."""
    f = check(data)
    kind, message, reply_to = f["kind"], f["message"], f["reply_to"]
    about = f" about {f['member_name'] or f['member']}" if f["member"] else ""
    msg = EmailMessage()
    msg["Subject"] = f"[Site feedback] {KINDS[kind]}{about}"
    msg["From"] = formataddr(("US Congress vs Voters feedback form", cfg["user"]))
    msg["To"] = cfg["to"]
    if reply_to:
        msg["Reply-To"] = reply_to
    lines = [message, "", "—", *details(f)]
    lines.append(f"Reply to: {reply_to}" if reply_to else "Reply to: (none given; the sender chose to stay anonymous)")
    lines.append(f"Received: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    if reply_to:
        lines.append(f"The form also emails the sender a copy (at most {COPIES_PER_ADDRESS} an hour to one address); "
                     "their replies to it come to this inbox.")
    lines += ["", "Sent through the site's feedback form. The site keeps no copy."]
    msg.set_content("\n".join(lines))
    return msg


def build_copy(data: dict, cfg: dict) -> EmailMessage | None:
    """The copy for the visitor, if they gave an address: what they sent, from the site, with
    replies going to the inbox so the conversation continues there."""
    f = check(data)
    if not f["reply_to"]:
        return None
    msg = EmailMessage()
    msg["Subject"] = f"Your message to {SITE_NAME}: {subject(f)}"
    msg["From"] = formataddr((SITE_NAME, cfg["copy_from"]))
    msg["To"] = f["reply_to"]
    msg["Reply-To"] = cfg["to"]
    msg["Auto-Submitted"] = "auto-generated"
    lines = [f"Thank you for writing to {SITE_NAME}. This is a copy of the message you sent through",
             "the form on our website, for your records. To add anything, reply to this email; your",
             "reply comes to our inbox.",
             "", "—", "", f["message"], "", "—", *details(f),
             f"Sent: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
             "", "If you didn't send this, someone typed your address into our contact form. You can",
             "ignore this email; you won't hear from us again unless you write to us.",
             "", "Our website keeps no copy of your message or your address."]
    msg.set_content("\n".join(lines))
    return msg


def send(msg: EmailMessage, cfg: dict) -> None:
    context = ssl.create_default_context()
    if cfg["port"] == 465:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context, timeout=20) as s:
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as s:
            s.starttls(context=context)
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)


def submit(data: dict, client: str, sender=None) -> dict:
    """Validate, rate-limit and send one message, then the visitor's copy if they gave an address.
    Raises Rejected with what to tell the visitor. Returns {"copy_sent": True/False/None}: None when
    no address was given; False when the copy couldn't go (the message itself still went)."""
    cfg = settings()
    if cfg is None:
        raise Rejected(503, "The form isn't available right now. Please use one of the email addresses on this page.")
    msg = build_message(data, cfg)
    copy = build_copy(data, cfg)
    if not limiter.allow(client or "unknown"):
        raise Rejected(429, "Too many messages just now. Please try again later, or use email.")
    deliver = sender or send
    try:
        deliver(msg, cfg)
    except (smtplib.SMTPException, OSError):
        raise Rejected(502, "Your message couldn't be sent just now. Please try again later, or use email.")
    if copy is None:
        return {"copy_sent": None}
    if not copy_limiter.allow(copy["To"].lower()):
        return {"copy_sent": False}
    try:
        deliver(copy, cfg)
    except (smtplib.SMTPException, OSError):
        return {"copy_sent": False}
    return {"copy_sent": True}
