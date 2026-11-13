"""Readable vote titles. Voteview's older records (mostly before the 1990s) are typed in capitals:
"TO CONFIRM THE NOMINATION OF WILLIAM P. CLEMENTS, JR., OF TEXAS TO BE DEPUTY SECRETARY OF DEFENSE."
tidy() turns text like that into sentence case for display, putting back the capitals that belong:
bill numbers, names in nominations, states, Congress and the chambers, departments, and so on.
Text that isn't in capitals is returned unchanged, and the stored record is never changed.
"""

import re

STATES = """Alabama Alaska Arizona Arkansas California Colorado Connecticut Delaware Florida Georgia Hawaii
Idaho Illinois Indiana Iowa Kansas Kentucky Louisiana Maine Maryland Massachusetts Michigan Minnesota
Mississippi Missouri Montana Nebraska Nevada Ohio Oklahoma Oregon Pennsylvania Tennessee Texas Utah
Vermont Virginia Washington Wisconsin Wyoming Guam""".split()
MULTI_WORD = ["New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota",
              "Rhode Island", "South Carolina", "South Dakota", "West Virginia", "District of Columbia",
              "Puerto Rico", "Virgin Islands", "American Samoa", "United States", "United Nations",
              "Soviet Union", "Social Security", "Supreme Court", "Vice President", "Panama Canal",
              "Middle East", "Great Lakes", "Equal Rights Amendment", "Federal Reserve", "Coast Guard",
              "Air Force", "Marine Corps", "Postal Service", "Library of Congress", "Strategic Petroleum Reserve",
              "Federal Election Commission", "Small Business Administration", "Veterans Administration",
              "Tennessee Valley Authority", "Export-Import Bank", "Peace Corps", "Civil Service",
              "Ways and Means", "Armed Services", "Foreign Relations", "Foreign Affairs", "Rules Committee",
              "Committee of the Whole", "Housing and Urban Development", "Health, Education, and Welfare",
              "Health and Human Services", "Veterans Affairs", "Urban Development"]
WORDS = """Congress Senate House Representatives President Speaker Constitution Amtrak Medicare Medicaid
Watergate Vietnam Cambodia Laos Israel Egypt China Taiwan Japan Korea Cuba Mexico Canada Panama Nicaragua
Salvador Angola Lebanon Iran Iraq Turkey Greece Cyprus Rhodesia Africa Europe European Asia Soviet Russia
Chile Brazil Philippines Poland Germany Britain British Jordan Saudi Arabia Libya Syria Afghanistan Pakistan India
American Americans January February March April May June July August September October November December
Monday Tuesday Wednesday Thursday Friday Saturday Sunday Christmas Columbus Defense Treasury Justice Interior
Agriculture Commerce Labor Energy Education Transportation State Navy Army Pentagon Alaskan Indian Indians
Olympic Olympics Atlantic Pacific Arctic Mississippi Potomac Chesapeake Appalachian""".split()
ACRONYMS = """U.S. U.N. U.S.S.R. D.C. NATO NASA FBI CIA EPA OSHA ERA OPEC SALT AID HEW HUD CETA ERDA FEA
ICC FCC FTC SEC TVA GAO OMB CBO NSF NIH IRS USA GSA FHA VA AFL-CIO MX ABM B-1 OEO IMF DOD DOE NOAA
SBA ACTION FAA NLRB""".split()
ROMAN = {"ii", "iii", "iv", "vi", "vii", "viii", "ix", "xi", "xii", "xiv", "xv", "xvi", "xx"}

# Bill and resolution labels, from however the clerk typed them ("H.RES. 6", "H. J. RES. 1", "S.CON.RES.2").
BILL_RE = re.compile(r"\b(h|s)\.?\s?(j\.?\s?res|con\.?\s?res|res|r)?\.?\s?(\d+)\b", re.I)
BILL_LABEL = {("h", "r"): "H.R.", ("h", "res"): "H.Res.", ("h", "jres"): "H.J.Res.", ("h", "conres"): "H.Con.Res.",
              ("s", ""): "S.", ("s", "res"): "S.Res.", ("s", "jres"): "S.J.Res.", ("s", "conres"): "S.Con.Res."}


def is_shouting(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 8 and sum(c.isupper() for c in letters) / len(letters) > 0.85


def _bill(m: re.Match) -> str:
    kind = re.sub(r"[.\s]", "", (m.group(2) or "")).lower()
    label = BILL_LABEL.get((m.group(1).lower(), kind))
    if label is None or (m.group(1).lower() == "h" and kind == ""):
        return m.group(0)                                   # "h 12" etc.: not a bill label
    return f"{label} {m.group(3)}"


def _title_words(name: str) -> str:
    out = []
    for w in name.split(" "):
        if re.fullmatch(r"[a-z]\.?", w):                    # initials
            out.append(w.upper())
        elif w.lower().rstrip(".,") in ROMAN:
            out.append(w.upper())
        elif w in ("de", "la", "van", "von", "der", "da", "du"):
            out.append(w)
        else:
            out.append("-".join(p[:1].upper() + p[1:] for p in w.split("-")))
    name = " ".join(out)
    name = re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), name)
    name = re.sub(r"\bO'([a-z])", lambda m: "O'" + m.group(1).upper(), name)
    return name


def tidy(text: str | None) -> str | None:
    if not text or not is_shouting(text):
        return text
    s = text.lower()
    # Names in nominations: "nomination of william p. clements, jr., of texas to be ..."
    s = re.sub(r"(nomination of )([a-z][a-z.' -]+?)(?=,| of | to | as | for |$)",
               lambda m: m.group(1) + _title_words(m.group(2)), s)
    for phrase in MULTI_WORD:
        s = re.sub(rf"\b{re.escape(phrase.lower())}\b", phrase, s)
    for word in STATES + WORDS:
        s = re.sub(rf"\b{word.lower()}\b", word, s)
    for a in ACRONYMS:
        s = re.sub(rf"(?<![\w.]){re.escape(a.lower())}(?![\w])", a, s)
    s = re.sub(r"\b(jr|sr)\.", lambda m: m.group(1).capitalize() + ".", s)
    s = re.sub(r"\b(\d+)(st|nd|rd|th) Congress", r"\1\2 Congress", s)
    s = re.sub(r"\btitle ([ivx]+)\b", lambda m: "Title " + m.group(1).upper(), s)
    s = re.sub(r"\b(amendment|amdt)\.? no\.", lambda m: m.group(1) + " no.", s)
    s = BILL_RE.sub(_bill, s)
    # "State" as in Department/Secretary of State only; otherwise "a state", "states".
    s = re.sub(r"\bState\b", "state", s)
    s = re.sub(r"\b(Department|Secretary|department|secretary) of state\b", lambda m: m.group(1) + " of State", s)
    s = re.sub(r"\bdepartment of (?=[A-Z])", "Department of ", s)
    s = re.sub(r"\b([A-Z][a-z]+) act\b", r"\1 Act", s)        # "Social Security Act"
    # Sentence case: the first letter, and the first after a full stop ending a word of 3+ letters
    # (so not after "U.S." or an initial).
    s = re.sub(r"^(\s*)([a-z])", lambda m: m.group(1) + m.group(2).upper(), s)
    s = re.sub(r"(?<=[A-Za-z][a-z]{2}[.!?])(\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), s)
    return s
