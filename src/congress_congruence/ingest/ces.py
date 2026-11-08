"""Cooperative Election Study (CES) survey data, from Harvard Dataverse.

    python -m congress_congruence.ingest.ces inspect 2025   # what's in a release
    python -m congress_congruence.ingest.ces link 2025      # which roll call answers each survey item
    python -m congress_congruence.ingest.ces load 2025      # link + estimate state and district opinion
    (add --file path/to/local.dta to any of these to skip the download)

inspect downloads the year's main data file into RAW_DATA_DIR/ces/<year>/ (once)
and writes logs/ces_<year>_inspect.txt: files, rows, geography and weight columns,
and every question mentioning a bill, vote or Congress with a weighted split.

link and load read config/ces_<year>_items.yaml, which lists the survey items
about actions of Congress and how to find the vote that answers each one.
load replaces that year's items, links and estimates in one transaction.
"""

import json
import logging
import re
import sys
from pathlib import Path

from .. import config
from .votes import http_session

log = logging.getLogger(__name__)

DATAVERSE = "https://dataverse.harvard.edu"
# From the CES data downloads page (Tufts). Add years as they are released.
DATASETS = {
    2025: "doi:10.7910/DVN/DFUGJR",
    2024: "doi:10.7910/DVN/X11EP6",
    2023: "doi:10.7910/DVN/JQJTCC",
    2022: "doi:10.7910/DVN/PR4L8P",
}

GEO_PATTERNS = [r"^cdid", r"^cd\d", r"district", r"^inputstate", r"^state", r"^countyfips", r"^lookupzip", r"^region"]
WEIGHT_PATTERNS = [r"weight"]
# Roll-call / bill items: CES labels them by bill name or "Congress considered..."
ITEM_LABEL_WORDS = re.compile(
    r"\b(act|bill|legislation|congress|senate|house|vote on|would you vote|support or oppose|resolution|amendment)\b",
    re.IGNORECASE)


# ---------------------------------------------------------------- Dataverse

def dataset_id(year: int) -> str:
    """Dataverse ID for a year: the built-in list, else one recorded by the survey watcher
    (data/ces_releases.json), else an error naming what to do."""
    if year in DATASETS:
        return DATASETS[year]
    found = config.PROJECT_ROOT / "data" / "ces_releases.json"
    if found.exists():
        known = json.loads(found.read_text())
        if str(year) in known:
            return known[str(year)]["id"]
    raise KeyError(f"No Dataverse ID known for CES {year}. Run the survey watcher, or add it to DATASETS.")


def dataset_files(persistent_id: str, http=None) -> dict:
    http = http or http_session()
    url = f"{DATAVERSE}/api/datasets/:persistentId/?persistentId={persistent_id}"
    resp = http.get(url, timeout=60)
    resp.raise_for_status()
    return summarize_dataset(resp.json())


def summarize_dataset(payload: dict) -> dict:
    v = payload["data"]["latestVersion"]
    files = []
    for f in v.get("files", []):
        d = f["dataFile"]
        files.append({
            "id": d["id"],
            "name": d.get("originalFileName") or d.get("filename"),
            "stored_name": d.get("filename"),
            "bytes": d.get("originalFileSize") or d.get("filesize"),
            "format": d.get("originalFileFormat") or d.get("contentType"),
            "restricted": f.get("restricted", False),
        })
    return {
        "version": f"{v.get('versionNumber')}.{v.get('versionMinorNumber')}",
        "released": v.get("releaseTime") or v.get("lastUpdateTime"),
        "files": files,
    }


def pick_data_file(files: list[dict]) -> dict | None:
    """The main respondent file: the largest .dta, else the largest .csv/.tab."""
    def kind(f):
        n = (f["name"] or "").lower()
        return "dta" if n.endswith(".dta") else "csv" if n.endswith((".csv", ".tab")) else None
    for wanted in ("dta", "csv"):
        cands = [f for f in files if kind(f) == wanted and not f["restricted"]]
        if cands:
            return max(cands, key=lambda f: f["bytes"] or 0)
    return None


def pick_guide_file(files: list[dict]) -> dict | None:
    """The questionnaire guide: a PDF with 'guide' in its name, else the largest PDF."""
    pdfs = [f for f in files if (f["name"] or "").lower().endswith(".pdf") and not f["restricted"]]
    named = [f for f in pdfs if "guide" in f["name"].lower()]
    pool = named or pdfs
    return max(pool, key=lambda f: f["bytes"] or 0) if pool else None


def guide_url_for(year: int) -> str | None:
    try:
        f = pick_guide_file(dataset_files(dataset_id(year))["files"])
    except Exception as e:      # the guide link is a nicety; never block a load on it
        log.warning("Couldn't look up the CES %s guide: %s", year, e)
        return None
    return f"{DATAVERSE}/file.xhtml?fileId={f['id']}" if f else None


def download(file: dict, dest_dir: Path, http=None) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / file["name"]
    if path.exists() and (not file["bytes"] or path.stat().st_size == file["bytes"]):
        log.info("Already downloaded: %s", path)
        return path
    http = http or http_session()
    url = f"{DATAVERSE}/api/access/datafile/{file['id']}?format=original"
    log.info("Downloading %s (%s MB)...", file["name"], round((file["bytes"] or 0) / 1e6, 1))
    with http.get(url, timeout=600, stream=True) as resp:
        if resp.status_code in (401, 403):
            raise PermissionError(
                f"Dataverse refused {file['name']} ({resp.status_code}). It may require accepting terms "
                f"in a browser: {DATAVERSE}/file.xhtml?fileId={file['id']}  Download it there and rerun "
                "with --file <path>.")
        resp.raise_for_status()
        tmp = path.with_suffix(path.suffix + ".part")
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(1 << 20):
                fh.write(chunk)
        tmp.rename(path)
    return path


# ---------------------------------------------------------------- reading

def read_metadata(path: Path) -> tuple[list[str], dict[str, str], dict[str, dict], int]:
    """(columns, column labels, value labels per column, row count). Reads no data rows for .dta."""
    if path.suffix.lower() == ".dta":
        import pyreadstat
        _, meta = pyreadstat.read_dta(str(path), metadataonly=True)
        return (meta.column_names, meta.column_names_to_labels or {},
                meta.variable_value_labels or {}, meta.number_rows or 0)
    import pandas as pd
    head = pd.read_csv(path, nrows=0, sep=None, engine="python")
    rows = sum(1 for _ in open(path, "rb")) - 1
    return list(head.columns), {}, {}, rows


def read_columns(path: Path, columns: list[str]):
    import pandas as pd
    if path.suffix.lower() == ".dta":
        import pyreadstat
        df, _ = pyreadstat.read_dta(str(path), usecols=columns, apply_value_formats=False)
        return df
    return pd.read_csv(path, usecols=columns, sep=None, engine="python")


def matches(name: str, patterns: list[str]) -> bool:
    return any(re.search(p, name, re.IGNORECASE) for p in patterns)


def find_items(columns, labels, value_labels) -> list[str]:
    """Columns that look like questions about a bill or vote."""
    out = []
    for c in columns:
        label = labels.get(c) or ""
        if matches(c, GEO_PATTERNS + WEIGHT_PATTERNS):
            continue
        if ITEM_LABEL_WORDS.search(label):
            out.append(c)
    return out


def weighted_split(series, weights) -> dict:
    import pandas as pd
    df = pd.DataFrame({"v": series, "w": weights}).dropna()
    total = df["w"].sum()
    if not total:
        return {}
    return {str(k): round(100 * w / total, 1) for k, w in df.groupby("v")["w"].sum().items()}


def inspect(year: int, local_file: Path | None = None) -> Path:
    out_lines = []
    say = out_lines.append
    say(f"CES {year} inspection")

    if local_file:
        path = local_file
        say(f"Local file: {path}")
    else:
        info = dataset_files(dataset_id(year))
        say(f"Dataset {dataset_id(year)}  version {info['version']}  released {info['released']}")
        say("Files:")
        for f in info["files"]:
            mb = round((f["bytes"] or 0) / 1e6, 1)
            say(f"  id={f['id']}  {f['name']}  {mb} MB  {f['format']}{'  RESTRICTED' if f['restricted'] else ''}")
        chosen = pick_data_file(info["files"])
        if not chosen:
            say("No .dta or .csv data file found; see the file list above.")
            return write_report(year, out_lines)
        path = download(chosen, config.raw_data_dir() / "ces" / str(year))
        say(f"Main data file: {chosen['name']}")

    columns, labels, value_labels, nrows = read_metadata(path)
    say(f"Rows: {nrows:,}   Columns: {len(columns):,}")

    geo = [c for c in columns if matches(c, GEO_PATTERNS)]
    wts = [c for c in columns if matches(c, WEIGHT_PATTERNS)]
    say("\nGeography columns:")
    for c in geo:
        say(f"  {c}: {labels.get(c, '')}")
    say("\nWeight columns:")
    for c in wts:
        say(f"  {c}: {labels.get(c, '')}")

    items = find_items(columns, labels, value_labels)
    weight_col = next((w for w in ("commonpostweight", "commonweight") if w in columns), wts[0] if wts else None)
    data = read_columns(path, items + ([weight_col] if weight_col else [])) if items else None

    say(f"\nQuestions that mention a bill, vote or Congress ({len(items)}), weighted by {weight_col}:")
    for c in items:
        say(f"\n  {c}: {labels.get(c, '')}")
        vl = value_labels.get(c)
        if vl:
            say("    answers: " + "; ".join(f"{k}={v}" for k, v in vl.items()))
        if data is not None and weight_col:
            say(f"    weighted %: {json.dumps(weighted_split(data[c], data[weight_col]))}")
    return write_report(year, out_lines)


def write_report(year: int, lines: list[str]) -> Path:
    out = config.PROJECT_ROOT / "logs" / f"ces_{year}_inspect.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))
    print(f"... full report: {out}")
    return out


# ---------------------------------------------------------------- link and load

STATE_FIPS = {
    1: "AL", 2: "AK", 4: "AZ", 5: "AR", 6: "CA", 8: "CO", 9: "CT", 10: "DE", 11: "DC", 12: "FL",
    13: "GA", 15: "HI", 16: "ID", 17: "IL", 18: "IN", 19: "IA", 20: "KS", 21: "KY", 22: "LA",
    23: "ME", 24: "MD", 25: "MA", 26: "MI", 27: "MN", 28: "MS", 29: "MO", 30: "MT", 31: "NE",
    32: "NV", 33: "NH", 34: "NJ", 35: "NM", 36: "NY", 37: "NC", 38: "ND", 39: "OH", 40: "OK",
    41: "OR", 42: "PA", 44: "RI", 45: "SC", 46: "SD", 47: "TN", 48: "TX", 49: "UT", 50: "VT",
    51: "VA", 53: "WA", 54: "WV", 55: "WI", 56: "WY",
}
SUPPORT, OPPOSE = 1, 2


def load_config(year: int) -> dict:
    import yaml
    path = config.PROJECT_ROOT / "config" / f"ces_{year}_items.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No item list for {year}: create {path}")
    return yaml.safe_load(path.read_text())


def find_data_file(year: int, local_file: Path | None) -> Path:
    if local_file:
        return local_file
    folder = config.raw_data_dir() / "ces" / str(year)
    found = sorted(folder.glob("*.dta")) + sorted(folder.glob("*.csv"))
    if found:
        return found[0]
    info = dataset_files(dataset_id(year))
    chosen = pick_data_file(info["files"])
    if not chosen:
        raise FileNotFoundError(f"No data file in the CES {year} release")
    return download(chosen, folder)


def survey_congress(year: int) -> int:
    from .votes import current_session
    from datetime import date
    return current_session(date(year, 11, 15))[0]


def match_vote(conn, chamber: str, congress: int, rule: dict) -> tuple[dict | None, int]:
    """The last vote matching a rule, and how many matched in all.

    Rule keys (all optional, combined with AND): roll_call (an exact ID), bill [type, number],
    find (text in the description), questions (any of these in the question), date (YYYY-MM-DD).
    expect "Yea-Nay" (e.g. "230-196") only accepts a vote with that tally, so a rule can't quietly
    pick up a different vote (a wrong guess finds nothing and is reported as NO MATCH)."""
    where, params = ["chamber = %s", "congress = %s"], [chamber, congress]
    if "roll_call" in rule:
        where.append("roll_call_id = %s")
        params.append(rule["roll_call"])
    if "date" in rule:
        where.append("vote_date = %s")
        params.append(str(rule["date"]))
    if "expect" in rule:
        yea, nay = (int(x) for x in str(rule["expect"]).split("-"))
        where.append("yea_total = %s and nay_total = %s")
        params += [yea, nay]
    if "bill" in rule:
        where.append("bill_type = %s and bill_number = %s")
        params += [rule["bill"][0], int(rule["bill"][1])]
    if "find" in rule:
        where.append("description ilike %s")
        params.append(f"%{rule['find']}%")
    qs = rule.get("questions") or []
    if qs:
        where.append("(" + " or ".join(["question ilike %s"] * len(qs)) + ")")
        params += [f"%{q}%" for q in qs]
    sql = ("select roll_call_id, vote_date, question, description, result, yea_total, nay_total "
           f"from core.roll_call where {' and '.join(where)} order by vote_date desc, roll_number desc")
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return (rows[0] if rows else None), len(rows)


LINK_COLUMNS = ("survey", "variable", "chamber", "roll_call_id", "match_note", "reader_note",
                "support_side", "match_kind")


def link(conn, year: int, cfg: dict) -> list[tuple]:
    """Resolve each item's vote per chamber. Returns rows for survey_item_vote (LINK_COLUMNS)
    and prints a review list.

    Per item: match: same (default) or related (a close but different bill: shown, never scored).
    Per chamber rule: support_side: yea (default) or nay (e.g. an amendment to block the proposal);
    congress: an earlier Congress than the survey's (surveys sometimes ask about bills passed years
    before). Such a rule is allowed for the House only when the survey's district column is for that
    Congress's lines; otherwise respondents' districts and the members' seats wouldn't be the same areas."""
    congress = cfg.get("congress") or survey_congress(year)
    lines = district_congress(cfg, congress)
    # Congresses with the same district lines as the survey's column (e.g. the 111th and 112th
    # both used the 2002 lines), listed in the item file after checking for mid-decade redraws.
    same_lines = {lines, *map(int, cfg.get("district_lines_also") or [])}
    out = []
    print(f"Linking {cfg['survey']} items to votes of the {congress}th Congress")
    for var, item in cfg["items"].items():
        print(f"\n{var}: {item['question']}")
        for chamber, rule in item.get("votes", {}).items():
            vote_congress = int(rule.get("congress", congress))
            if chamber == "house" and vote_congress not in same_lines:
                raise ValueError(f"{var}: a House vote of the {vote_congress}th Congress can't be compared with "
                                 f"districts as drawn for the {lines}th ({cfg.get('district_column')}); use the Senate only")
            vote, n = match_vote(conn, chamber, vote_congress, rule)
            if not vote:
                print(f"  {chamber:6} NO MATCH for {rule}")
                continue
            print(f"  {chamber:6} {vote['roll_call_id']}  {vote['vote_date']}  {vote['question']}  "
                  f"{vote['result']} {vote['yea_total']}-{vote['nay_total']}  ({n} matched; using the latest)")
            print(f"         {(vote['description'] or '')[:110]}")
            side, kind = rule.get("support_side", "yea"), item.get("match", "same")
            if side not in ("yea", "nay") or kind not in ("same", "related"):
                raise ValueError(f"{var}: support_side must be yea/nay and match same/related")
            if side == "nay" or kind == "related":
                print(f"         support side: {side.title()}   match: {kind}")
            if vote_congress != congress:
                print(f"         from the {vote_congress}th Congress")
            criteria = {k: v for k, v in rule.items() if k not in ("note", "support_side")}
            out.append((cfg["survey"], var, chamber, vote["roll_call_id"],
                        f"latest of {n} votes matching {json.dumps(criteria, default=str)}", rule.get("note"),
                        side, kind))
    return out


def district_congress(cfg: dict, default: int) -> int:
    """The Congress whose district lines the survey's district column uses: district_congress if
    set, else the number in a column named like cdid117, else the survey's own Congress."""
    if cfg.get("district_congress"):
        return int(cfg["district_congress"])
    m = re.search(r"cdid(\d+)", str(cfg.get("district_column") or ""))
    return int(m.group(1)) if m else default


def save_items(cur, survey: str, src: dict, respondents: int | None,
               items: list[tuple[str, dict, str | None]], links: list[tuple]) -> None:
    """Record the survey's source, replace its items (which cascades to links and estimates),
    and write the item-to-vote links. items: (variable, config entry, label in the data file)."""
    cur.execute(
        """insert into core.survey (survey, title, fielded, respondents, dataset_url, guide_url, about_url,
                                    organization, description, kind)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (survey) do update set title = excluded.title, fielded = excluded.fielded,
               respondents = excluded.respondents, dataset_url = excluded.dataset_url,
               guide_url = excluded.guide_url, about_url = excluded.about_url,
               organization = excluded.organization, description = excluded.description,
               kind = excluded.kind""",
        (survey, src.get("title", survey), src.get("fielded"), respondents, src.get("dataset_url"),
         src.get("guide_url"), src.get("about_url"), src.get("organization"), src.get("description"),
         src.get("kind", "survey")))
    cur.execute("delete from core.survey_item where survey = %s", (survey,))   # cascades
    for var, item, label in items:
        cur.execute("insert into core.survey_item (survey, variable, question, survey_label, note) "
                    "values (%s, %s, %s, %s, %s)", (survey, var, item["question"], label, item.get("note")))
    cur.executemany(f"insert into core.survey_item_vote ({', '.join(LINK_COLUMNS)}) "
                    f"values ({', '.join(['%s'] * len(LINK_COLUMNS))})", links)


def house_seats(conn, year: int) -> dict[str, list[int]]:
    """Voting House seats in each state on the survey date (excludes DC and territories)."""
    from datetime import date
    with conn.cursor() as cur:
        cur.execute("""select state, array_agg(distinct district order by district) from core.term
                        where chamber = 'house' and %s between start_date and end_date and district >= 0
                        group by state""", (date(year, 11, 15),))
        seats = dict(cur.fetchall())
    return {st: d for st, d in seats.items() if st in STATE_FIPS.values() and st != "DC"}


def responses_for(df, var: str, state_col: str, dist_col: str, weight_col: str,
                  seats: dict[str, list[int]]) -> list[tuple]:
    out = []
    for st_code, cd, ans, w in zip(df[state_col], df[dist_col], df[var], df[weight_col]):
        if ans not in (SUPPORT, OPPOSE) or w != w or w is None:   # skipped / not asked / missing weight
            continue
        try:
            st = STATE_FIPS.get(int(st_code))
        except (TypeError, ValueError):
            st = None
        if not st or st == "DC":
            continue
        if seats.get(st) == [0]:
            dist = 0                                           # at-large state
        else:
            try:
                dist = int(cd)
            except (TypeError, ValueError):
                dist = None
            if dist not in seats.get(st, []):
                dist = None                                    # still counts toward the state
        out.append((st, dist, 1 if ans == SUPPORT else 0, float(w)))
    return out


def load(conn, year: int, local_file: Path | None = None) -> dict:
    from .. import opinion
    cfg = load_config(year)
    path = find_data_file(year, local_file)
    columns, labels, _, nrows = read_metadata(path)
    weight_col = next((w for w in cfg["weight_preference"] if w in columns), None)
    if not weight_col:
        raise ValueError(f"None of the weight columns {cfg['weight_preference']} are in {path.name}")
    items = [v for v in cfg["items"] if v in columns]
    missing = [v for v in cfg["items"] if v not in columns]
    if missing:
        raise ValueError(f"Items not in the data file: {missing}")
    df = read_columns(path, [cfg["state_column"], cfg["district_column"], weight_col] + items)
    seats = house_seats(conn, year)
    links = link(conn, year, cfg)
    conn.commit()   # end the read-only transaction the lookups opened, so the block below is a real
                    # transaction (inside an open one it would only be a savepoint, committed later)

    survey = cfg["survey"]
    summary = {"respondents": nrows, "weight": weight_col, "items": len(items), "votes_linked": len(links)}
    with conn.transaction(), conn.cursor() as cur:
        src = {"organization": "Cooperative Election Study",
               "description": "a large academic survey of U.S. adults", **cfg.get("source", {})}
        if not src.get("guide_url"):
            src["guide_url"] = guide_url_for(year)
        save_items(cur, survey, src, src.get("respondents") or nrows,
                   [(var, cfg["items"][var], labels.get(var)) for var in items], links)
        counts = {"support": 0, "oppose": 0, "too_close": 0}
        for var in items:
            resp = responses_for(df, var, cfg["state_column"], cfg["district_column"], weight_col, seats)
            states, districts = opinion.estimate(resp, seats)
            for a in states + districts:
                cur.execute(
                    """insert into core.opinion_estimate (survey, variable, state, district, respondents,
                       effective_n, raw_support, support, support_low, support_high, majority, method)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (survey, var, a.state, a.district, a.respondents, a.effective_n, a.raw_support,
                     a.support, a.low, a.high, a.majority, opinion.METHOD))
                if a.district is not None:
                    counts[a.majority] += 1
        summary["district_calls"] = counts
    return summary


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = argv[1:]
    local = None
    if "--file" in args:
        i = args.index("--file")
        local = Path(args[i + 1])
        args = args[:i] + args[i + 2:]
    if len(args) != 2 or args[0] not in ("inspect", "link", "load") or not args[1].isdigit():
        print(__doc__)
        return 2
    cmd, year = args[0], int(args[1])
    if not local:
        try:
            dataset_id(year)
        except KeyError as e:
            print(e)
            return 2
    if cmd == "inspect":
        inspect(year, local)
        return 0
    from .. import db
    from .votes import record_run
    with db.connect() as conn:
        if cmd == "link":
            link(conn, year, load_config(year))
        else:
            print(record_run(conn, f"ces_{year}", lambda: load(conn, year, local)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
