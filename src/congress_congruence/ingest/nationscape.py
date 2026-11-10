"""Democracy Fund + UCLA Nationscape survey data (July 2019 - February 2021), from Harvard Dataverse.

    python -m congress_congruence.ingest.nationscape inspect   # what's in the release (run first)
    python -m congress_congruence.ingest.nationscape link      # which roll call answers each question
    python -m congress_congruence.ingest.nationscape load      # link + estimate state and district opinion
    (add --dir path/to/folder to use weekly .dta files already on disk instead of downloading)

Nationscape interviewed about 6,250 people a week for 85 weeks (494,796 in all) and asked whether
they agree or disagree with specific policy proposals. Each week is its own data file. The whole
period is loaded as one survey ("Nationscape 2019-2021"): every week a question was asked is pooled,
unless the item file limits it to some weeks (asked_from / asked_to).

inspect downloads the release into RAW_DATA_DIR/nationscape/ (once; zips are unpacked), and writes
logs/nationscape_inspect.txt: the release's license and terms, its files, the weekly files found,
and every column with its label, its answer codes and the weeks it appears in. The item file's
variable names, state and district columns and weight are taken from that report.

link and load read config/nationscape_items.yaml (same rules as the CES item files). Agree and
disagree codes are read from each question's value labels ("Agree" = support, "Disagree" = oppose);
"Not sure" and skipped answers are left out, as in the CES.

District lines: interviews are placed in districts as drawn for the 116th Congress. The 117th used
the same lines everywhere except North Carolina (new map for the 2020 election), so an item compared
with a 117th Congress House vote lists NC under skip_district_states: NC residents still count toward
the state, but NC districts get no estimate, so NC's representatives aren't compared on it.
"""

import json
import logging
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

from .. import config
from . import ces
from .votes import http_session

log = logging.getLogger(__name__)

DATASET = "doi:10.7910/DVN/CQFP3Z"
SURVEY = "Nationscape 2019-2021"
ORGANIZATION = "Democracy Fund + UCLA Nationscape"
WEEK_RE = re.compile(r"ns(\d{8})", re.IGNORECASE)
STATE_CODES = set(ces.STATE_FIPS.values())


# ---------------------------------------------------------------- release, download, weekly files

def release_info(http=None) -> dict:
    """Files, version, license and terms of the Dataverse release."""
    http = http or http_session()
    resp = http.get(f"{ces.DATAVERSE}/api/datasets/:persistentId/?persistentId={DATASET}", timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    info = ces.summarize_dataset(payload)
    v = payload["data"]["latestVersion"]
    lic = v.get("license")
    info["license"] = (lic.get("name") if isinstance(lic, dict) else lic) or None
    info["license_url"] = lic.get("uri") if isinstance(lic, dict) else None
    info["terms"] = v.get("termsOfUse") or v.get("termsOfAccess") or None
    return info


def raw_dir() -> Path:
    return config.raw_data_dir() / "nationscape"


def pick_release_files(files: list[dict]) -> list[dict]:
    """The weekly Stata data: .dta files if listed one by one, else the zip with DTA in its name
    (else the largest zip). Restricted files are skipped."""
    open_files = [f for f in files if not f["restricted"]]
    dtas = [f for f in open_files if (f["name"] or "").lower().endswith(".dta")]
    if dtas:
        return dtas
    zips = [f for f in open_files if (f["name"] or "").lower().endswith(".zip")]
    named = [f for f in zips if "dta" in f["name"].lower()]
    pool = named or zips
    return [max(pool, key=lambda f: f["bytes"] or 0)] if pool else []


def fetch_release(folder: Path | None = None, http=None) -> tuple[Path, dict]:
    """Download (once) and unpack the weekly files; returns the folder and the release info."""
    folder = folder or raw_dir()
    info = release_info(http)
    chosen = pick_release_files(info["files"])
    if not chosen:
        raise FileNotFoundError("No .dta files or zip of them in the Nationscape release; see the inspect report")
    for f in chosen:
        path = ces.download(f, folder, http)
        if path.suffix.lower() == ".zip":
            marker = folder / f".unpacked-{path.name}"
            if not marker.exists():
                log.info("Unpacking %s...", path.name)
                with zipfile.ZipFile(path) as z:
                    for name in z.namelist():
                        if name.lower().endswith(".dta") and not name.startswith("__MACOSX"):
                            z.extract(name, folder)
                marker.write_text("done\n")
    return folder, info


def weekly_files(folder: Path) -> list[tuple[date, Path]]:
    """Every weekly .dta under the folder, by interview week (from names like ns20190718.dta)."""
    out = []
    for p in folder.rglob("*.dta"):
        m = WEEK_RE.search(p.name)
        if m:
            d = m.group(1)
            out.append((date(int(d[:4]), int(d[4:6]), int(d[6:])), p))
    return sorted(out)


# ---------------------------------------------------------------- answers and geography

def answer_codes(value_labels: dict) -> dict[int, int]:
    """{code: 1 support / 0 oppose} from a question's value labels: Agree/Support -> 1,
    Disagree/Oppose -> 0. Anything else (Not sure, skipped) is left out."""
    out = {}
    for code, label in (value_labels or {}).items():
        text = str(label).strip().lower()
        if text.startswith(("disagree", "oppose", "strongly disagree", "somewhat disagree")):
            out[int(code)] = 0
        elif text.startswith(("agree", "support", "strongly agree", "somewhat agree")):
            out[int(code)] = 1
    return out


def state_code(value) -> str | None:
    """'TX', 'tx' or a FIPS number (48) -> 'TX'."""
    if value is None or value != value:
        return None
    s = str(value).strip().upper()
    if s in STATE_CODES:
        return s
    try:
        return ces.STATE_FIPS.get(int(float(s)))
    except ValueError:
        return None


def district_number(value) -> int | None:
    """'TX07', 'TX-7', '7', 7.0, 'AL', '00' -> 7 / 0. None if unreadable."""
    if value is None or value != value:
        return None
    s = str(value).strip().upper()
    if s.endswith("AL") or s in ("0", "00"):
        return 0
    m = re.search(r"(\d+)(?:\.0+)?$", s)
    return int(m.group(1)) if m else None


def responses(df, column: str, codes: dict[int, int], cfg: dict, seats: dict[str, list[int]]) -> list[tuple]:
    """(state, district or None, 1/0, weight) for each usable answer to one question."""
    out = []
    for st_raw, cd_raw, ans, w in zip(df[cfg["state_column"]], df[cfg["district_column"]], df[column],
                                      df[cfg["weight_column"]]):
        try:
            side = codes.get(int(ans))
        except (TypeError, ValueError):
            side = None
        if side is None or w is None or w != w or w <= 0:
            continue
        st = state_code(st_raw)
        if not st or st == "DC" or st not in seats:
            continue
        dist = 0 if seats[st] == [0] else district_number(cd_raw)
        if dist not in seats[st]:
            dist = None                                    # still counts toward the state
        out.append((st, dist, side, float(w)))
    return out


# ---------------------------------------------------------------- config and reading

def load_config() -> dict:
    import yaml
    return yaml.safe_load((config.PROJECT_ROOT / "config" / "nationscape_items.yaml").read_text())


def item_column(var: str, item: dict) -> str:
    """The data column an item reads: `column` if set (two items can read one question, e.g. one
    for each Congress's vote), else the item's own name."""
    return item.get("column") or var


def asked_in(item: dict, week: date) -> bool:
    lo, hi = item.get("asked_from"), item.get("asked_to")
    return (not lo or week >= date.fromisoformat(str(lo))) and (not hi or week <= date.fromisoformat(str(hi)))


def read_weeks(folder: Path, cfg: dict):
    """One table of every week's respondents, with the columns the items need (absent in a week =
    not asked that week) plus `_week`; and each question's answer codes from its value labels."""
    import pandas as pd
    import pyreadstat
    weeks = weekly_files(folder)
    if not weeks:
        raise FileNotFoundError(f"No weekly Nationscape files (ns<date>.dta) under {folder}")
    wanted = {item_column(v, it) for v, it in cfg["items"].items()}
    base = [cfg["state_column"], cfg["district_column"], cfg["weight_column"]]
    frames, codes, labels, seen = [], {}, {}, set()
    for week, path in weeks:
        _, meta = pyreadstat.read_dta(str(path), metadataonly=True)
        cols = set(meta.column_names)
        missing_base = [c for c in base if c not in cols]
        if missing_base:
            raise ValueError(f"{path.name} has no {missing_base}; check the item file's columns against the inspect report")
        here = sorted(wanted & cols)
        if not here:
            continue
        for c in here:
            seen.add(c)
            labels.setdefault(c, (meta.column_names_to_labels or {}).get(c))
            found = answer_codes((meta.variable_value_labels or {}).get(c, {}))
            if found and c not in codes:
                codes[c] = found
        df, _ = pyreadstat.read_dta(str(path), usecols=base + here, apply_value_formats=False)
        df["_week"] = week
        frames.append(df)
    missing = sorted(wanted - seen)
    if missing:
        raise ValueError(f"Questions not in any weekly file: {missing}; check the names against the inspect report")
    for v, it in cfg["items"].items():                       # answer codes set by hand win over labels
        if it.get("answers"):
            codes[item_column(v, it)] = {int(it["answers"]["support"]): 1, int(it["answers"]["oppose"]): 0}
    no_codes = sorted(c for c in wanted if not codes.get(c))
    if no_codes:
        raise ValueError(f"No Agree/Disagree labels found for {no_codes}; set `answers: {{support: <code>, "
                         "oppose: <code>}}` for them in the item file")
    return pd.concat(frames, ignore_index=True), codes, labels, [w for w, _ in weeks]


# ---------------------------------------------------------------- inspect

def inspect(folder: Path | None = None) -> Path:
    import pyreadstat
    lines = ["Nationscape inspection"]
    say = lines.append
    if folder is None:
        folder, info = fetch_release()
        say(f"Dataset {DATASET}  version {info['version']}  released {info['released']}")
        say(f"License: {info['license'] or 'none stated'}  {info['license_url'] or ''}")
        say(f"Terms of use: {info['terms'] or 'none stated in the release record'}")
        say("Files:")
        for f in info["files"]:
            say(f"  id={f['id']}  {f['name']}  {round((f['bytes'] or 0) / 1e6, 1)} MB"
                f"{'  RESTRICTED' if f['restricted'] else ''}")
    else:
        say(f"Local folder: {folder}")
    weeks = weekly_files(folder)
    say(f"\nWeekly files: {len(weeks)}" + (f", {weeks[0][0]} to {weeks[-1][0]}" if weeks else ""))
    if not weeks:
        return write_report(lines)

    columns: dict[str, dict] = {}
    rows = 0
    for week, path in weeks:
        _, meta = pyreadstat.read_dta(str(path), metadataonly=True)
        rows += meta.number_rows or 0
        for c in meta.column_names:
            col = columns.setdefault(c, {"label": (meta.column_names_to_labels or {}).get(c), "weeks": [],
                                         "values": (meta.variable_value_labels or {}).get(c, {})})
            col["weeks"].append(week)
    say(f"Respondents in all weeks: {rows:,}")

    sample, _ = pyreadstat.read_dta(str(weeks[-1][1]), row_limit=5)
    say("\nGeography and weight columns (values from the last week's first rows):")
    for c in columns:
        if ces.matches(c, ces.GEO_PATTERNS + ces.WEIGHT_PATTERNS + [r"congress", r"^cd", r"zip", r"date"]):
            vals = list(sample[c]) if c in sample else []
            say(f"  {c:28} {columns[c]['label'] or ''}  e.g. {vals}")

    say("\nEvery column: name | weeks asked | first-last week | label | answer codes")
    for c, col in columns.items():
        ws = col["weeks"]
        codes = "; ".join(f"{k}={v}" for k, v in list(col["values"].items())[:8])
        agree = answer_codes(col["values"])
        flag = "  [agree/disagree]" if agree and set(agree.values()) == {0, 1} else ""
        say(f"  {c} | {len(ws)} | {ws[0]} to {ws[-1]} | {col['label'] or ''} | {codes}{flag}")
    return write_report(lines)


def write_report(lines: list[str]) -> Path:
    out = config.PROJECT_ROOT / "logs" / "nationscape_inspect.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:10]))
    print(f"... full report: {out}")
    return out


# ---------------------------------------------------------------- link and load

def first_year(congress: int) -> int:
    """The first year of a Congress (116th: 2019)."""
    return 2 * congress + 1787


def link(conn, cfg: dict) -> list[tuple]:
    """The CES linker does the matching (same rules); the item file sets `congress` (the default
    Congress of its votes) and `district_congress` (the lines respondents' districts use)."""
    return ces.link(conn, first_year(int(cfg["congress"])), cfg)


def load(conn, folder: Path | None = None) -> dict:
    from .. import opinion
    from . import district_profile
    cfg = load_config()
    if folder is None:
        folder, info = fetch_release()
    else:
        info = {}
    df, codes, labels, weeks = read_weeks(folder, cfg)
    seats = ces.house_seats(conn, first_year(int(cfg["district_congress"])))
    links = link(conn, cfg)
    profiles = district_profile.profiles_for(conn, cfg["district_congress"])
    keys = sorted((st, d) for st, ds in seats.items() for d in ds)
    if profiles and opinion.profile_matrix(keys, profiles) is not None:
        method = opinion.METHOD_WITH_PROFILES
    else:
        profiles, method = None, opinion.METHOD
    conn.commit()     # end the read-only transaction the lookups opened (see ces.load)

    src = {"organization": ORGANIZATION, "description": "a weekly survey of about 6,250 U.S. adults, 2019-2021",
           "dataset_url": f"https://doi.org/{DATASET.removeprefix('doi:')}", **cfg.get("source", {})}
    items = list(cfg["items"])
    summary = {"respondents": len(df), "weeks": len(weeks), "items": len(items), "votes_linked": len(links),
               "method": method, "license": info.get("license")}
    counts = {"support": 0, "oppose": 0, "too_close": 0}
    with conn.transaction(), conn.cursor() as cur:
        ces.save_items(cur, cfg["survey"], src, src.get("respondents") or len(df),
                       [(v, cfg["items"][v], labels.get(item_column(v, cfg["items"][v]))) for v in items], links)
        for var in items:
            item = cfg["items"][var]
            col = item_column(var, item)
            rows = df[df[col].notna() & df["_week"].map(lambda w: asked_in(item, w))]
            resp = responses(rows, col, codes[col], cfg, seats)
            states, districts = opinion.estimate(resp, seats, profiles)
            skip = set(item.get("skip_district_states") or [])
            for a in states + [d for d in districts if d.state not in skip]:
                cur.execute(
                    """insert into core.opinion_estimate (survey, variable, state, district, respondents,
                       effective_n, raw_support, support, support_low, support_high, majority, method)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (cfg["survey"], var, a.state, a.district, a.respondents, a.effective_n, a.raw_support,
                     a.support, a.low, a.high, a.majority, method))
                if a.district is not None:
                    counts[a.majority] += 1
    summary["district_calls"] = counts
    return summary


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = argv[1:]
    folder = None
    if "--dir" in args:
        i = args.index("--dir")
        folder = Path(args[i + 1])
        args = args[:i] + args[i + 2:]
    if len(args) != 1 or args[0] not in ("inspect", "link", "load"):
        print(__doc__)
        return 2
    if args[0] == "inspect":
        inspect(folder)
        return 0
    from .. import db
    from .votes import record_run
    with db.connect() as conn:
        if args[0] == "link":
            link(conn, load_config())
        else:
            print(json.dumps(record_run(conn, "nationscape", lambda: load(conn, folder)), default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
