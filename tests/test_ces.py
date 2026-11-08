"""Tests for the CES inspection tool, using a tiny made-up Stata file shaped like CES."""

import pandas as pd
import pytest

from congress_congruence.ingest import ces

pyreadstat = pytest.importorskip("pyreadstat")

DATAVERSE_JSON = {"data": {"latestVersion": {
    "versionNumber": 1, "versionMinorNumber": 0, "releaseTime": "2026-03-20T12:00:00Z",
    "files": [
        {"restricted": False, "dataFile": {"id": 11, "filename": "CES25_Common.tab",
         "originalFileName": "CES25_Common.dta", "originalFileSize": 900, "filesize": 500,
         "originalFileFormat": "application/x-stata-14"}},
        {"restricted": False, "dataFile": {"id": 12, "filename": "CES25_Guide.pdf", "filesize": 4000,
         "contentType": "application/pdf"}},
        {"restricted": False, "dataFile": {"id": 13, "filename": "small.csv", "filesize": 10,
         "contentType": "text/csv"}},
    ]}}}


def test_summarize_and_pick_main_file():
    info = ces.summarize_dataset(DATAVERSE_JSON)
    assert info["version"] == "1.0" and len(info["files"]) == 3
    chosen = ces.pick_data_file(info["files"])
    assert (chosen["id"], chosen["name"], chosen["bytes"]) == (11, "CES25_Common.dta", 900)


@pytest.fixture
def stata_file(tmp_path):
    df = pd.DataFrame({
        "caseid": [1, 2, 3, 4],
        "inputstate": [48, 48, 6, 6],
        "cdid119": [8, 2, 12, 12],
        "commonweight": [1.0, 2.0, 1.0, 0.0],
        "CC25_330a": [1, 2, 1, 1],      # a bill item
        "CC25_401": [3, 2, 1, 4],       # unrelated item
    })
    path = tmp_path / "CES25_Common.dta"
    pyreadstat.write_dta(df, str(path),
        column_labels=["Case ID", "State", "Congressional district (119th)", "Common weight",
                       "Laken Riley Act: support or oppose", "How interested are you in politics"],
        variable_value_labels={"CC25_330a": {1: "Support", 2: "Oppose"}})
    return path


def test_finds_geography_weights_and_bill_items(stata_file):
    cols, labels, values, n = ces.read_metadata(stata_file)
    assert n == 4
    assert ces.find_items(cols, labels, values) == ["CC25_330a"]
    assert [c for c in cols if ces.matches(c, ces.GEO_PATTERNS)] == ["inputstate", "cdid119"]


def test_weighted_split(stata_file):
    df = ces.read_columns(stata_file, ["CC25_330a", "commonweight"])
    # Support: weights 1 + 1 + 0 = 2 of 4; Oppose: 2 of 4
    assert ces.weighted_split(df["CC25_330a"], df["commonweight"]) == {"1.0": 50.0, "2.0": 50.0}


def test_inspect_local_file_writes_report(stata_file, monkeypatch, tmp_path):
    monkeypatch.setattr(ces.config, "PROJECT_ROOT", tmp_path)
    report = ces.inspect(2025, stata_file).read_text()
    assert "Rows: 4" in report
    assert "CC25_330a: Laken Riley Act: support or oppose" in report
    assert "answers: 1.0=Support; 2.0=Oppose" in report or "answers: 1=Support; 2=Oppose" in report
    assert "CC25_401" not in report


def test_pick_guide_prefers_a_pdf_named_guide():
    files = [
        {"id": 1, "name": "CCES24_Common_OUTPUT.dta", "bytes": 10**9, "restricted": False},
        {"id": 2, "name": "Questionnaire_appendix.pdf", "bytes": 9_000_000, "restricted": False},
        {"id": 3, "name": "CES_2024_Guide.pdf", "bytes": 2_000_000, "restricted": False},
    ]
    assert ces.pick_guide_file(files)["id"] == 3
    assert ces.pick_guide_file(files[:2])["id"] == 2      # no 'guide' in any name: largest PDF
    assert ces.pick_guide_file(files[:1]) is None


def test_2024_items_file_is_well_formed():
    cfg = ces.load_config(2024)
    assert cfg["district_column"] == "cdid118" and cfg["weight_preference"] == ["commonweight"]
    assert set(cfg["items"]) == {"CC24_340a", "CC24_340c", "CC24_340d", "CC24_340e", "CC24_340f"}
    for item in cfg["items"].values():
        assert item["question"] and item["votes"]
        assert set(item["votes"]) <= {"house", "senate"}


def test_2024_tiktok_rule_accepts_a_suspension_vote():
    rule = ces.load_config(2024)["items"]["CC24_340d"]["votes"]["house"]
    assert "Suspend the Rules and Pass" in rule["questions"]


def test_district_lines_decide_which_congress_a_house_vote_may_come_from():
    assert ces.district_congress({"district_column": "cdid117"}, 117) == 117
    assert ces.district_congress({"district_column": "cdid", "district_congress": 112}, 112) == 112
    assert ces.district_congress({"district_column": "V250"}, 110) == 110
    old_house = {"survey": "CES 2023", "district_column": "cdid118",
                 "items": {"X": {"question": "q", "votes": {"house": {"congress": 117, "bill": ["hr", 1]}}}}}
    with pytest.raises(ValueError, match="117th Congress can't be compared"):
        ces.link(None, 2023, old_house)


def test_every_items_file_is_well_formed():
    """Shape checks for all item files, and that no House rule reaches across district lines."""
    for path in sorted((ces.config.PROJECT_ROOT / "config").glob("ces_*_items.yaml")):
        year = int(path.stem.split("_")[1])
        cfg = ces.load_config(year)
        survey_congress = cfg.get("congress") or ces.survey_congress(year)
        lines = {ces.district_congress(cfg, survey_congress), *cfg.get("district_lines_also", [])}
        assert cfg["survey"] == f"CES {year}" and cfg["district_column"] and cfg["weight_preference"], path
        for var, item in cfg["items"].items():
            assert item["question"] and item["votes"], (path, var)
            assert item.get("match", "same") in ("same", "related"), (path, var)
            for chamber, rule in item["votes"].items():
                assert chamber in ("house", "senate"), (path, var)
                assert rule.get("support_side", "yea") in ("yea", "nay"), (path, var)
                assert set(rule) <= {"roll_call", "date", "expect", "bill", "find", "questions", "congress",
                                     "note", "support_side"}, (path, var, set(rule))
                if chamber == "house":
                    assert int(rule.get("congress", survey_congress)) in lines, (path, var)
