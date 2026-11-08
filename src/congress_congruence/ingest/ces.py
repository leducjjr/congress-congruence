"""Cooperative Election Study (CES) survey data, from Harvard Dataverse.

Step 1 (now): inspect a year's release and summarize what's in it.
    python -m congress_congruence.ingest.ces inspect 2025
    python -m congress_congruence.ingest.ces inspect 2025 --file path/to/local.dta   # skip the download

This downloads the year's main data file into RAW_DATA_DIR/ces/<year>/ (once),
then writes logs/ces_<year>_inspect.txt listing:
  - the dataset's files and version
  - row count
  - geography and weight columns (district, state, weights)
  - every question that looks like a roll-call or bill item, with its wording,
    answer codes and a weighted support/oppose split

The loader and district estimates are built from what this finds.
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
        info = dataset_files(DATASETS[year])
        say(f"Dataset {DATASETS[year]}  version {info['version']}  released {info['released']}")
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


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = argv[1:]
    local = None
    if "--file" in args:
        i = args.index("--file")
        local = Path(args[i + 1])
        args = args[:i] + args[i + 2:]
    if len(args) != 2 or args[0] != "inspect" or not args[1].isdigit():
        print(__doc__)
        return 2
    year = int(args[1])
    if year not in DATASETS and not local:
        print(f"No Dataverse ID recorded for {year}. Known: {sorted(DATASETS)}")
        return 2
    inspect(year, local)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
