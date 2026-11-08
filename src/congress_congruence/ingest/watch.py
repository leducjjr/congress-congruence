"""Watch survey sources for new or updated releases, and prepare them for review.

    python -m congress_congruence.ingest.watch          # check every source (the monthly job)
    python -m congress_congruence.ingest.watch --list   # show what has been seen

Nothing here loads data into the panel. When a source publishes something new, the
watcher records it, does the preparation that needs no judgment, and asks for review:

  New CES year     -> download it, write the inspection report, and draft
                      config/drafts/ces_<year>_items.yaml: every support/oppose question
                      about Congress, with the closest-matching votes listed as comments.
                      A person checks the matches, saves the file as
                      config/ces_<year>_items.yaml, and runs `ces link` / `ces load`.
  Updated release  -> (a new version of a year already seen) note it; reload after review.

What has been seen is kept in data/ces_releases.json. The first run only records what
exists today, so it doesn't ask about years published long ago.

Notifications: if .env has NOTIFY_URL, a short message is POSTed to it (works with
ntfy.sh topics, which push to a phone app). Every run also writes logs/review_needed.txt
when something is waiting.

New sources are added as another `check_<source>` function in SOURCES.
"""

import json
import logging
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from .. import config, db
from . import ces
from .votes import http_session

log = logging.getLogger(__name__)

CES_COLLECTION = "cces"    # https://dataverse.harvard.edu/dataverse/cces
NOT_A_YEARLY_STUDY = re.compile(r"cumulative|panel|recontact|module|policy|district-level", re.I)
STOPWORDS = set("""a an and the of to for in on that which with without by from or as at be is are was were this
these those all any each other such would will shall act bill congress bills actions require prohibit
provide provision government federal united states u.s us who what when where their its it""".split())


# ---------------------------------------------------------------- state

def state_path() -> Path:
    return config.PROJECT_ROOT / "data" / "ces_releases.json"


def load_state() -> dict:
    p = state_path()
    return json.loads(p.read_text()) if p.exists() else {}


def save_state(state: dict) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------- CES on Dataverse

def ces_releases(http=None) -> dict[int, dict]:
    """Yearly CES studies in the Dataverse collection: {year: {id, title, version, published}}."""
    http = http or http_session()
    found, start = {}, 0
    while True:
        resp = http.get(f"{ces.DATAVERSE}/api/search", timeout=60, params={
            "q": "*", "type": "dataset", "subtree": CES_COLLECTION,
            "per_page": 100, "start": start, "sort": "date", "order": "desc"})
        resp.raise_for_status()
        data = resp.json()["data"]
        for item in data.get("items", []):
            rel = parse_release(item)
            if rel:
                year = rel.pop("year")
                # keep the newest-looking entry if a year appears twice
                if year not in found or rel["version"] > found[year]["version"]:
                    found[year] = rel
        start += 100
        if start >= data.get("total_count", 0):
            return found


def parse_release(item: dict) -> dict | None:
    title = item.get("name") or ""
    if NOT_A_YEARLY_STUDY.search(title):
        return None
    if not re.search(r"\bC{1,2}ES\b|Cooperative (Congressional )?Election Study", title, re.I):
        return None
    years = {int(y) for y in re.findall(r"\b(20\d\d)\b", title)}
    if len(years) != 1:
        return None
    return {
        "year": years.pop(),
        "id": item.get("global_id"),
        "title": title,
        "version": f"{item.get('majorVersion', 0)}.{item.get('minorVersion', 0)}",
        "published": item.get("published_at"),
    }


def check_ces(conn, http=None) -> list[str]:
    """Compare Dataverse with what has been seen. Returns messages for anything needing review."""
    state, messages = load_state(), []
    first_run = not state
    for year, rel in sorted(ces_releases(http).items()):
        key = str(year)
        seen = state.get(key)
        if seen is None:
            state[key] = {**rel, "first_seen": date.today().isoformat()}
            if first_run or year in ces.DATASETS:
                continue                        # existed before the watcher started
            save_state(state)                   # so ces.dataset_id() can find it
            messages.append(prepare_new_year(conn, year, rel))
        elif rel["version"] != seen.get("version"):
            messages.append(
                f"CES {year} has a new version ({seen.get('version')} -> {rel['version']}). "
                f"Re-run `ces inspect {year}`, check the item file still matches, then `ces load {year}`.")
            state[key] = {**seen, **rel}
    save_state(state)
    if first_run:
        log.info("First run: recorded %d existing CES releases; nothing to review.", len(state))
    return messages


# ---------------------------------------------------------------- drafting an item file

def prepare_new_year(conn, year: int, rel: dict) -> str:
    out = config.PROJECT_ROOT / "config" / "drafts" / f"ces_{year}_items.yaml"
    try:
        report = ces.inspect(year)
        path = ces.find_data_file(year, None)
        columns, labels, values, nrows = ces.read_metadata(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(draft_items(conn, year, rel, columns, labels, values, nrows))
    except Exception as e:                       # report it; a person takes it from here
        log.exception("Preparing CES %s failed", year)
        return f"New release: {rel['title']} ({rel['id']}). Automatic preparation failed ({e}); run `ces inspect {year}` by hand."
    return (f"New release: {rel['title']} ({rel['id']}). Report: {report}. "
            f"Draft item list for review: {out}")


def congress_items(columns, labels, values) -> list[tuple[str, str]]:
    """(variable, question) for support/oppose questions about actions of Congress."""
    out = []
    for c in columns:
        label = labels.get(c) or ""
        answers = {str(k).split(".")[0]: str(v).strip().lower() for k, v in (values.get(c) or {}).items()}
        if answers.get("1") == "support" and answers.get("2") == "oppose" and re.search(r"congress", label, re.I):
            question = label.split("--", 1)[-1].strip()
            out.append((c, question))
    return out


def keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in STOPWORDS}


def candidate_votes(conn, congress: int, question: str, limit: int = 4) -> list[dict]:
    """Final-passage-type votes in that Congress whose description shares the most words with the question."""
    words = keywords(question)
    if not words:
        return []
    with conn.cursor() as cur:
        cur.execute("""select roll_call_id, chamber, vote_date, question, description, bill_type, bill_number,
                              yea_total, nay_total
                         from core.roll_call where congress = %s
                          and (question ilike any (array['%%Passage%%', '%%Concur%%', '%%Nomination%%',
                                                         '%%Cloture%%', '%%Agreeing to the Resolution%%']))""",
                    (congress,))
        cols = [d.name for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    scored = [(len(words & keywords(r["description"])), r) for r in rows]
    scored = [(n, r) for n, r in scored if n >= 2]
    scored.sort(key=lambda x: (-x[0], str(x[1]["vote_date"])))
    return [r for _, r in scored[:limit]]


def draft_items(conn, year: int, rel: dict, columns, labels, values, nrows) -> str:
    congress = ces.survey_congress(year)
    district_col = next((c for c in (f"cdid{congress}", f"cdid{congress + 1}") if c in columns), "CHECK")
    weight = [w for w in ("commonweight", "commonpostweight") if w in columns]
    lines = [
        f"# DRAFT written by the survey watcher on {date.today()}: needs review before use.",
        f"# {rel['title']} ({rel['id']}), version {rel['version']}, {nrows:,} respondents.",
        "# For each item: confirm the question is about a real floor vote, pick the decisive vote",
        "# (candidates below, found by matching words, may be wrong or missing), and fill in `votes`",
        "# as in config/ces_2025_items.yaml. Delete items with no matching vote, saying why.",
        "# Check which wave asked these questions (pre- or post-election) and set the weight to match.",
        f"# Then save as config/ces_{year}_items.yaml and run `ces link {year}`.",
        "",
        f"survey: CES {year}",
        f"dataset_id: {rel['id']}",
        f"weight_preference: {json.dumps(weight)}",
        f"district_column: {district_col}",
        "state_column: inputstate",
        "",
        "source:",
        f"  title: Cooperative Election Study {year}",
        "  fielded: CHECK",
        f"  dataset_url: https://doi.org/{rel['id'].removeprefix('doi:')}" if (rel.get("id") or "").startswith("doi:")
        else "  dataset_url: CHECK",
        "  about_url: https://cces.gov.harvard.edu/",
        "",
        "final_questions: &final",
        "  - On Passage", "  - Passage of the Bill", "  - Concur", "  - Agreeing to the Resolution",
        "  - Joint Resolution Passage",
        "",
        "items:",
    ]
    items = congress_items(columns, labels, values)
    if not items:
        lines.append("  {}   # no support/oppose questions about Congress were found; check the report")
    for var, question in items:
        lines += ["", f"  {var}:", f"    question: {json.dumps(question)}", "    votes: {}   # TO FILL IN"]
        cands = candidate_votes(conn, congress, question)
        if not cands:
            lines.append("    # no candidate votes found by word match")
        for c in cands:
            bill = f"{c['bill_type']} {c['bill_number']}" if c["bill_type"] else "no bill"
            lines.append(f"    # candidate {c['chamber']}: {c['roll_call_id']} {c['vote_date']} {c['question']} "
                         f"[{bill}] {c['yea_total']}-{c['nay_total']}: {(c['description'] or '')[:80]}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- running

SOURCES = {"CES": check_ces}


def notify(messages: list[str]) -> None:
    out = config.PROJECT_ROOT / "logs" / "review_needed.txt"
    out.parent.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(out, "a") as fh:
        for m in messages:
            fh.write(f"{stamp}  {m}\n")
    url = os.environ.get("NOTIFY_URL")
    if url:
        try:
            http_session().post(url, data="\n\n".join(messages).encode(), timeout=20,
                                headers={"Title": "congress-congruence: survey needs review"})
        except Exception as e:
            log.warning("Notification failed: %s", e)


def run(conn) -> dict:
    messages, errors = [], []
    for name, check in SOURCES.items():
        try:
            messages += check(conn)
        except Exception as e:
            log.exception("Checking %s failed", name)
            errors.append(f"{name}: {e}")
    if messages:
        notify(messages)
    for m in messages:
        print(m)
    return {"needs_review": len(messages), "errors": errors}


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if argv[1:] == ["--list"]:
        for year, rel in sorted(load_state().items()):
            print(f"CES {year}: {rel['id']}  version {rel['version']}  first seen {rel.get('first_seen')}")
        return 0
    if argv[1:]:
        print(__doc__)
        return 2
    from .votes import record_run
    with db.connect() as conn:
        result = record_run(conn, "survey_watch", lambda: run(conn))
    print(result)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
