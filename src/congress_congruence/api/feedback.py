"""The site's feedback form: a visitor's message is emailed to the project inbox and nothing is kept.

POST /v1/feedback (JSON). The message goes by email from a send-only mailbox (feedback@) to the
public inbox (contact@). It is never written to the database, a file or a log. The API's database
login stays read-only; this endpoint doesn't touch the database at all.

Settings (.env):
    FEEDBACK_SMTP_USER       the sending mailbox, e.g. feedback@uscongressvsvoters.org
    FEEDBACK_SMTP_PASSWORD   its password
    FEEDBACK_TO              where messages go, e.g. contact@uscongressvsvoters.org
    FEEDBACK_SMTP_HOST       default smtp.titan.email (Bluehost Professional Email)
    FEEDBACK_SMTP_PORT       default 465 (SSL)
Without the first three, the endpoint answers 503 and the page shows the email addresses instead.

Abuse protection, with no tracking and no third-party services:
  - a hidden "website" field that people never see but bots fill in;
  - the form must have been open for a few seconds;
  - length limits on every field, and a reply address must look like one address;
  - at most PER_HOUR messages per connection address and GLOBAL_PER_HOUR in all, counted in
    memory only (never written anywhere) and forgotten after an hour. Each API worker process
    counts separately.
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


def settings() -> dict | None:
    user, password, to = (os.environ.get(k, "").strip() for k in
                          ("FEEDBACK_SMTP_USER", "FEEDBACK_SMTP_PASSWORD", "FEEDBACK_TO"))
    if not (user and password and to):
        return None
    return {"user": user, "password": password, "to": to,
            "host": os.environ.get("FEEDBACK_SMTP_HOST", "smtp.titan.email").strip(),
            "port": int(os.environ.get("FEEDBACK_SMTP_PORT", "465"))}


def one_line(text: str, limit: int) -> str:
    return re.sub(r"[\r\n\t]+", " ", text or "").strip()[:limit]


def build_message(data: dict, cfg: dict) -> EmailMessage:
    """Check what was submitted and turn it into the email. Raises Rejected."""
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

    about = f" about {member_name or member}" if member else ""
    msg = EmailMessage()
    msg["Subject"] = f"[Site feedback] {KINDS[kind]}{about}"
    msg["From"] = formataddr(("US Congress vs Voters feedback form", cfg["user"]))
    msg["To"] = cfg["to"]
    if reply_to:
        msg["Reply-To"] = reply_to
    lines = [message, "", "—", f"Type: {KINDS[kind]}"]
    if member:
        lines.append(f"Member: {member_name} ({member})" if member_name else f"Member: {member}")
    if page:
        lines.append(f"Sent from: {page}")
    lines.append(f"Reply to: {reply_to}" if reply_to else "Reply to: (none given; the sender chose to stay anonymous)")
    lines.append(f"Received: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines += ["", "Sent through the site's feedback form. The site keeps no copy."]
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


def submit(data: dict, client: str, sender=None) -> None:
    """Validate, rate-limit and send one message. Raises Rejected with what to tell the visitor."""
    cfg = settings()
    if cfg is None:
        raise Rejected(503, "The form isn't available right now. Please use one of the email addresses on this page.")
    msg = build_message(data, cfg)
    if not limiter.allow(client or "unknown"):
        raise Rejected(429, "Too many messages just now. Please try again later, or use email.")
    try:
        (sender or send)(msg, cfg)
    except (smtplib.SMTPException, OSError):
        raise Rejected(502, "Your message couldn't be sent just now. Please try again later, or use email.")
