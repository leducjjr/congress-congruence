"""Parse official roll-call vote XML from both chambers into one common shape.

House:  Clerk of the House, https://clerk.house.gov/evs/<year>/roll<NNN>.xml
Senate: Senate LIS, https://www.senate.gov/legislative/LIS/roll_call_votes/
        vote<congress><session>/vote_<congress>_<session>_<NNNNN>.xml

Both parsers return a ParsedRollCall. Nothing here touches the database.
House files identify members by Bioguide ID; Senate files by LIS ID, which
the loader translates to Bioguide.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time

from lxml import etree

# Normalized positions. Anything else (e.g. candidate names in a vote for
# Speaker) becomes 'other'; the original wording is always kept as raw_position.
POSITIONS = {
    "yea": "yea", "aye": "yea", "guilty": "yea",
    "nay": "nay", "no": "nay", "not guilty": "nay",
    "present": "present",
    "not voting": "not_voting", "absent": "not_voting",
}

# Bill prefixes after removing spaces and dots, longest first so HRES wins over HR.
BILL_RE = re.compile(r"^(HCONRES|HJRES|HRES|HR|SCONRES|SJRES|SRES|S)(\d+)$")


@dataclass
class MemberVote:
    member_id: str          # Bioguide (House) or LIS ID (Senate)
    id_type: str            # 'bioguide' or 'lis'
    position: str
    raw_position: str
    party: str | None
    state: str | None


@dataclass
class ParsedRollCall:
    chamber: str
    congress: int
    session: int
    roll_number: int
    vote_date: date
    vote_time: time | None
    question: str | None
    vote_type: str | None
    result: str | None
    description: str | None
    bill_type: str | None
    bill_number: int | None
    amendment_number: str | None
    yea_total: int | None
    nay_total: int | None
    present_total: int | None
    not_voting_total: int | None
    tie_breaker: str | None = None
    votes: list[MemberVote] = field(default_factory=list)

    @property
    def roll_call_id(self) -> str:
        return f"{self.chamber[0]}-{self.congress}-{self.session}-{self.roll_number}"


def normalize_position(raw: str) -> str:
    return POSITIONS.get(clean(raw).lower(), "other")


def parse_bill_ref(text: str | None) -> tuple[str | None, int | None]:
    """'H R 498' / 'S.Con.Res. 7' / 'H.J.Res.12' -> ('hr', 498) / ('sconres', 7) / ('hjres', 12).
    Returns (None, None) for things that aren't bills (quorum calls, nominations, motions)."""
    if not text:
        return None, None
    m = BILL_RE.match(re.sub(r"[\s.]", "", text).upper())
    return (m.group(1).lower(), int(m.group(2))) if m else (None, None)


def clean(text: str | None) -> str | None:
    """Collapse runs of whitespace; return None for empty text."""
    if text is None:
        return None
    text = " ".join(text.split())
    return text or None


def to_int(text: str | None) -> int | None:
    text = clean(text)
    return int(text) if text and text.isdigit() else None


def parse_xml(content: bytes):
    parser = etree.XMLParser(resolve_entities=False, no_network=True)  # never fetch anything the file points at
    return etree.fromstring(content, parser)


# ---------------------------------------------------------------- House

def parse_house(content: bytes) -> ParsedRollCall:
    root = parse_xml(content)
    meta = root.find("vote-metadata")
    if root.tag != "rollcall-vote" or meta is None:
        raise ValueError("Not a House Clerk roll-call file")
    t = lambda path: clean(meta.findtext(path))  # noqa: E731

    session = int(re.match(r"\d+", t("session")).group())          # '1st' -> 1
    vote_date = datetime.strptime(t("action-date"), "%d-%b-%Y").date()  # '18-Dec-2025'
    time_el = meta.find("action-time")
    vote_time = None
    if time_el is not None and time_el.get("time-etz"):
        vote_time = datetime.strptime(time_el.get("time-etz"), "%H:%M").time()
    bill_type, bill_number = parse_bill_ref(t("legis-num"))

    rc = ParsedRollCall(
        chamber="house",
        congress=int(t("congress")),
        session=session,
        roll_number=int(t("rollcall-num")),
        vote_date=vote_date,
        vote_time=vote_time,
        question=t("vote-question"),
        vote_type=t("vote-type"),
        result=t("vote-result"),
        description=t("vote-desc"),
        bill_type=bill_type,
        bill_number=bill_number,
        amendment_number=t("amendment-num"),
        yea_total=to_int(t("vote-totals/totals-by-vote/yea-total")),
        nay_total=to_int(t("vote-totals/totals-by-vote/nay-total")),
        present_total=to_int(t("vote-totals/totals-by-vote/present-total")),
        not_voting_total=to_int(t("vote-totals/totals-by-vote/not-voting-total")),
    )
    for rv in root.iterfind("vote-data/recorded-vote"):
        leg = rv.find("legislator")
        raw = clean(rv.findtext("vote")) or ""
        rc.votes.append(MemberVote(
            member_id=leg.get("name-id"),
            id_type="bioguide",
            position=normalize_position(raw),
            raw_position=raw,
            party=leg.get("party"),
            state=leg.get("state"),
        ))
    return rc


# ---------------------------------------------------------------- Senate

def parse_senate(content: bytes) -> ParsedRollCall:
    root = parse_xml(content)
    if root.tag != "roll_call_vote":
        raise ValueError("Not a Senate LIS roll-call file")
    t = lambda path: clean(root.findtext(path))  # noqa: E731

    stamp = datetime.strptime(t("vote_date"), "%B %d, %Y, %I:%M %p")  # 'February 21, 2025, 12:54 AM'

    # For an amendment vote the bill is what the amendment would change.
    if t("document/document_type") == "S.Amdt." or t("amendment/amendment_number"):
        bill_ref = t("amendment/amendment_to_document_number")
    else:
        bill_ref = f"{t('document/document_type') or ''} {t('document/document_number') or ''}"
    bill_type, bill_number = parse_bill_ref(bill_ref)

    tie = None
    if t("tie_breaker/by_whom"):
        tie = f"{t('tie_breaker/by_whom')}: {t('tie_breaker/tie_breaker_vote')}"

    rc = ParsedRollCall(
        chamber="senate",
        congress=int(t("congress")),
        session=int(t("session")),
        roll_number=int(t("vote_number")),
        vote_date=stamp.date(),
        vote_time=stamp.time(),
        question=t("question"),
        vote_type=t("majority_requirement"),
        result=t("vote_result"),
        description=t("vote_document_text") or t("vote_title"),
        bill_type=bill_type,
        bill_number=bill_number,
        amendment_number=t("amendment/amendment_number"),
        yea_total=to_int(t("count/yeas")),
        nay_total=to_int(t("count/nays")),
        present_total=to_int(t("count/present")),
        not_voting_total=to_int(t("count/absent")),
        tie_breaker=tie,
    )
    for m in root.iterfind("members/member"):
        raw = clean(m.findtext("vote_cast")) or ""
        rc.votes.append(MemberVote(
            member_id=clean(m.findtext("lis_member_id")),
            id_type="lis",
            position=normalize_position(raw),
            raw_position=raw,
            party=clean(m.findtext("party")),
            state=clean(m.findtext("state")),
        ))
    return rc


def parse(chamber: str, content: bytes) -> ParsedRollCall:
    return {"house": parse_house, "senate": parse_senate}[chamber](content)
