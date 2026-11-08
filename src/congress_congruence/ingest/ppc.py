"""Program for Public Consultation (University of Maryland) surveys, from their published PDFs.

    python -m congress_congruence.ingest.ppc fetch 2026   # download PDFs, read the results, write a review file
    python -m congress_congruence.ingest.ppc link 2026    # which roll call answers each survey item
    python -m congress_congruence.ingest.ppc load 2026    # link + store each state's and district's results

PPC doesn't publish respondent-level data. For each state it surveys it posts one
questionnaire PDF per topic, with the exact question wording and a Favor / Oppose / Ref-DK
table for the state and any districts surveyed there, plus each sample's size and
confidence interval. config/ppc_<year>_items.yaml says which pages to read, which PDF holds
each item, and a phrase that finds the question in it.

fetch saves the PDFs under RAW_DATA_DIR/ppc/<year>/, writes the numbers it read to
data/ppc/ppc_<year>_results.csv, and writes logs/ppc_<year>_review.txt listing every figure
with the question text it was found under, and anything it couldn't read. Nothing reaches
the panel until load, so the review file can be checked first.

How results are turned into estimates (no pooling: these are each area's own sample):
  support = Favor / (Favor + Oppose)       (people who answered either way)
  range   = support +/- CI * (Z90 / 1.96) / (Favor + Oppose)
where CI is PPC's published 95% confidence interval for that sample (which already accounts
for weighting), converted to the same 90% level, and the Z90 multiplier, used for CES estimates.
"""

import csv
import html
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from .. import config, opinion
from . import ces
from .votes import http_session

log = logging.getLogger(__name__)

METHOD = "published-results-v1"

STATE_NAMES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}
CODES = set(STATE_NAMES.values())
SUBGROUPS = re.compile(r"^(republicans?|democrats?|independents?|other|men|women|ages?\b|\d{2}[-+])", re.I)

# One results row: a label, then Favor %, Oppose %, Ref/DK % (Ref/DK sometimes missing).
ROW = re.compile(r"^\s*(?P<label>\S.*?)\s{2,}(?P<favor>\d{1,3})%\s+(?P<oppose>\d{1,3})%(?:\s+(?P<dk>\d{1,3})%)?\s*$")
QUESTION = re.compile(r"^\s*Q(\d+[a-z]?)\.\s", re.M)


# ---------------------------------------------------------------- reading a questionnaire

def pdf_text(path: Path) -> str:
    import pypdf
    reader = pypdf.PdfReader(str(path))
    return "\n".join(p.extract_text(extraction_mode="layout") or "" for p in reader.pages)


def area_of(label: str, home: str | None) -> tuple[str, int | None] | None:
    """(state, district or None for statewide) for a row or header label; None if not an area
    (e.g. 'National') or not recognized. home = the state the PDF is about, for labels like
    'District 1'."""
    s = re.sub(r"\s+", " ", label).strip(" :")
    if re.fullmatch(r"(?i)national|nationally|us|u\.s\.|united states", s):
        return None
    if re.search(r"(?i)at[- ]large", s):
        st = next((c for c in CODES if re.search(rf"\b{c}\b", s)), None) or \
             next((c for n, c in STATE_NAMES.items() if n.lower() in s.lower()), None) or home
        return (st, 0) if st else None
    m = re.fullmatch(r"([A-Z]{2})[- ]?0?(\d{1,2})", s)                         # IA-1, NY-17, IA 01
    if m and m.group(1) in CODES:
        return m.group(1), int(m.group(2))
    m = re.search(r"(?i)(?:district|CD)\s*#?\s*0?(\d{1,2})\b", s) or \
        re.search(r"(?i)\b(\d{1,2})(?:st|nd|rd|th)\b.*district", s)               # District 1, CD-1, 1st District
    if m:
        st = next((c for n, c in STATE_NAMES.items() if n.lower() in s.lower()), None) or home
        return (st, int(m.group(1))) if st else None
    name = re.sub(r"(?i)^state of |\(?statewide\)?|\bstate\b", "", s).strip(" ()-")
    if not name and re.search(r"(?i)statewide", s):
        return (home, None) if home else None       # '(Statewide)' alone: the state name wrapped onto the line above
    if name in STATE_NAMES:
        return STATE_NAMES[name], None
    if name.upper() in CODES:
        return name.upper(), None
    return None


def header_values(text: str, heading: str) -> list[tuple[str, str]]:
    """'label: value' lines under a heading such as 'Sample Sizes:' (up to the next blank line)."""
    m = re.search(rf"(?im)^\s*{heading}\s*:?\s*$", text)
    if not m:
        return []
    out = []
    for line in text[m.end():].lstrip("\r\n").splitlines():
        if not line.strip():
            if out:
                break
            continue
        if ":" not in line:
            break
        label, value = line.rsplit(":", 1)
        out.append((label.strip(), value.strip()))
    return out


def home_state(text: str) -> str | None:
    m = re.search(r"(?i)-\s*STATE OF ([A-Z ]+?)\s+(?:and|AND|-)", text[:600])
    if m:
        return STATE_NAMES.get(m.group(1).strip().title())
    for label, _ in header_values(text, "Sample Sizes"):
        a = area_of(label, None)
        if a and a[1] is None:
            return a[0]
    return None


def parse(text: str) -> dict:
    """Header (sample size and CI per area) and every question with its results rows."""
    home = home_state(text)
    sizes, cis = {}, {}
    for label, value in header_values(text, "Sample Sizes"):
        a = area_of(label, home)
        if a and re.sub(r"[,\s]", "", value).isdigit():
            sizes[a] = int(re.sub(r"[,\s]", "", value))
    for label, value in header_values(text, "Confidence Interval"):
        a = area_of(label, home)
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", value)
        if a and m:
            cis[a] = float(m.group(1)) / 100
    questions = []
    method = re.search(r"(?m)^\s*Methodology\s*$", text)       # questions end where the methodology starts
    body = text[:method.start()] if method else text
    starts = [m.start() for m in QUESTION.finditer(body)] + [len(body)]
    for i, start in enumerate(starts[:-1]):
        block = body[start:starts[i + 1]]
        num = QUESTION.match(block).group(1)
        lines = block.splitlines()
        rows, wording, unread = [], [], []
        for line in lines:
            r = ROW.match(line)
            if r:
                label = r.group("label").strip()
                if SUBGROUPS.match(label):
                    continue
                area = area_of(label, home)
                if area is None and not re.fullmatch(r"(?i)national(ly)?", label):
                    unread.append(label)
                rows.append({"label": label, "area": area, "favor": int(r.group("favor")),
                             "oppose": int(r.group("oppose")),
                             "dk": int(r.group("dk")) if r.group("dk") else None})
            elif not rows:
                wording.append(line.strip())
        text_q = re.sub(r"\s+", " ", " ".join(wording)).strip()
        text_q = re.sub(r"\s*Favor\s+Oppose(\s+Ref/DK)?\s*$", "", text_q)
        questions.append({"number": num, "text": text_q, "rows": rows, "unread_labels": unread})
    return {"home": home, "sizes": sizes, "cis": cis, "questions": questions}


def find_question(parsed: dict, pattern: str) -> dict | None:
    """The first question whose wording matches the pattern and that has a results table."""
    rx = re.compile(pattern, re.I | re.S)
    return next((q for q in parsed["questions"] if q["rows"] and rx.search(q["text"])), None)


# ---------------------------------------------------------------- estimates

def estimate(favor: int, oppose: int, ci: float, n: int, state: str, district: int | None) -> opinion.Area:
    answered = (favor + oppose) / 100
    support = (favor / 100) / answered
    half = ci * (opinion.Z90 / 1.96) / answered
    return opinion.Area(state=state, district=district, respondents=n,
                        effective_n=round(1 / ci ** 2, 1),      # PPC: CI = sqrt((1 + weight variance) / n)
                        raw_support=support, support=support,
                        low=max(0.0, support - half), high=min(1.0, support + half))


# ---------------------------------------------------------------- fetching

def load_config(year: int) -> dict:
    import yaml
    path = config.PROJECT_ROOT / "config" / f"ppc_{year}_items.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No item list for {year}: create {path}")
    return yaml.safe_load(path.read_text())


def pdf_links(page_html: str, base: str) -> list[str]:
    hrefs = re.findall(r"""href\s*=\s*["']([^"']+?\.pdf)(?:#[^"']*)?["']""", page_html, re.I)
    seen, out = set(), []
    for h in hrefs:
        url = urljoin(base, html.unescape(h))
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def pick_pdf(links: list[str], words: list[str]) -> str | None:
    """The questionnaire PDF whose file name contains every word (case-insensitive; - _ and space alike)."""
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower().replace("%20", ""))   # 'Health-Care' == 'healthcare'
    cands = [u for u in links if "questionnaire" in norm(u.rsplit("/", 1)[-1])
             and all(norm(w) in norm(u.rsplit("/", 1)[-1]) for w in words)]
    return cands[-1] if cands else None      # later links on a page are usually the newer release


def download(url: str, folder: Path, http) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / url.rsplit("/", 1)[-1]
    if path.exists() and path.stat().st_size:
        return path
    resp = http.get(url, timeout=120)
    resp.raise_for_status()
    if not resp.content.startswith(b"%PDF"):
        raise ValueError(f"Not a PDF: {url}")
    path.write_bytes(resp.content)
    return path


RESULT_FIELDS = ["item", "state", "district", "favor", "oppose", "dk", "n", "ci", "question_number",
                 "source_url", "page"]


def results_path(year: int) -> Path:
    return config.PROJECT_ROOT / "data" / "ppc" / f"ppc_{year}_results.csv"


def fetch(year: int, http=None) -> dict:
    """Download every configured page's PDFs, read each item's results, write the results CSV and
    a review file. Returns counts."""
    import time
    cfg = load_config(year)
    http = http or http_session()
    folder = config.raw_data_dir() / "ppc" / str(year)
    results, review, problems = [], [], []
    for page in cfg["pages"]:
        resp = http.get(page, timeout=60)
        resp.raise_for_status()
        links = pdf_links(resp.text, page)
        for var, item in cfg["items"].items():
            url = pick_pdf(links, item["pdf"])
            if not url:
                problems.append(f"{page}: no questionnaire PDF with {item['pdf']} in its name (for {var})")
                continue
            try:
                parsed = parse(pdf_text(download(url, folder, http)))
            except Exception as e:                                   # one bad file mustn't stop the rest
                problems.append(f"{url}: couldn't read ({e})")
                continue
            time.sleep(0.5)
            q = find_question(parsed, item["find"])
            if not q:
                problems.append(f"{url}: no question matching {item['find']!r} (for {var})")
                continue
            review.append(f"\n{var}  Q{q['number']}  {url}\n  {q['text'][:400]}")
            for label in q["unread_labels"]:
                problems.append(f"{url} Q{q['number']}: row label not recognized as a place: {label!r}")
            for row in q["rows"]:
                area = row["area"]
                if area is None:
                    continue
                n, ci = parsed["sizes"].get(area), parsed["cis"].get(area)
                if not n or not ci:
                    problems.append(f"{url} Q{q['number']}: no sample size / confidence interval for {row['label']!r}")
                    continue
                results.append({"item": var, "state": area[0], "district": "" if area[1] is None else area[1],
                                "favor": row["favor"], "oppose": row["oppose"],
                                "dk": "" if row["dk"] is None else row["dk"], "n": n, "ci": ci,
                                "question_number": q["number"], "source_url": url, "page": page})
                review.append(f"  {row['label']:<28} -> {area[0]}{'' if area[1] is None else '-' + str(area[1]):<4}"
                              f"  favor {row['favor']}%  oppose {row['oppose']}%  n={n}  CI=+/-{ci:.1%}")

    # The same area can appear in more than one page's PDF (e.g. a district on its state's page): keep one.
    unique = {}
    for r in results:
        unique.setdefault((r["item"], r["state"], str(r["district"])), r)
    out = results_path(year)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=RESULT_FIELDS)
        w.writeheader()
        w.writerows(unique.values())
    rep = config.PROJECT_ROOT / "logs" / f"ppc_{year}_review.txt"
    rep.parent.mkdir(exist_ok=True)
    rep.write_text(f"PPC {year}: {len(unique)} area results read from {len(cfg['pages'])} pages\n"
                   + (f"\nPROBLEMS ({len(problems)}):\n  " + "\n  ".join(problems) + "\n" if problems else
                      "\nNo problems.\n")
                   + "\nWhat was read, under the question text it was found with:" + "\n".join(review) + "\n")
    print(f"{len(unique)} area results, {len(problems)} problems. Review: {rep}\nResults: {out}")
    return {"results": len(unique), "problems": len(problems)}


# ---------------------------------------------------------------- load

def read_results(year: int) -> list[dict]:
    path = results_path(year)
    if not path.exists():
        raise FileNotFoundError(f"No results yet: run `ppc fetch {year}` first ({path})")
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def area_estimates(rows: list[dict], seats: dict[str, list[int]]) -> list[tuple[str, opinion.Area, str]]:
    """(item, estimate, source PDF) for every result row; a one-seat state's statewide figure
    also stands for its at-large district unless that district was reported separately."""
    out, have = [], {(r["item"], r["state"], r["district"]) for r in rows}
    for r in rows:
        district = int(r["district"]) if r["district"] != "" else None
        est = estimate(int(r["favor"]), int(r["oppose"]), float(r["ci"]), int(r["n"]), r["state"], district)
        out.append((r["item"], est, r["source_url"]))
        if district is None and seats.get(r["state"]) == [0] and (r["item"], r["state"], "0") not in have:
            out.append((r["item"], estimate(int(r["favor"]), int(r["oppose"]), float(r["ci"]), int(r["n"]),
                                            r["state"], 0), r["source_url"]))
    return out


def load(conn, year: int) -> dict:
    cfg = load_config(year)
    rows = read_results(year)
    unknown = {r["item"] for r in rows} - set(cfg["items"])
    if unknown:
        raise ValueError(f"Results for items not in the config: {sorted(unknown)}")
    seats = ces.house_seats(conn, year)
    links = ces.link(conn, year, cfg)
    conn.commit()     # close the lookups' transaction so the block below is a real transaction
    survey = cfg["survey"]
    items = [v for v in cfg["items"] if any(r["item"] == v for r in rows)]
    counts = {"support": 0, "oppose": 0, "too_close": 0}
    with conn.transaction(), conn.cursor() as cur:
        ces.save_items(cur, survey, cfg["source"], cfg["source"].get("respondents"),
                       [(v, cfg["items"][v], None) for v in items],
                       [lk for lk in links if lk[1] in items])
        for var, a, url in area_estimates(rows, seats):
            if var not in items:
                continue
            cur.execute(
                """insert into core.opinion_estimate (survey, variable, state, district, respondents, effective_n,
                       raw_support, support, support_low, support_high, majority, method, source_url)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (survey, var, a.state, a.district, a.respondents, a.effective_n, a.raw_support, a.support,
                 a.low, a.high, a.majority, METHOD, url))
            counts[a.majority] += 1
    return {"items": len(items), "votes_linked": len(links), "areas": len(rows), "calls": counts}


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = argv[1:]
    if len(args) != 2 or args[0] not in ("fetch", "link", "load") or not args[1].isdigit():
        print(__doc__)
        return 2
    cmd, year = args[0], int(args[1])
    if cmd == "fetch":
        return 0 if fetch(year)["results"] else 1
    from .. import db
    from .votes import record_run
    with db.connect() as conn:
        if cmd == "link":
            ces.link(conn, year, load_config(year))
        else:
            print(record_run(conn, f"ppc_{year}", lambda: load(conn, year)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
