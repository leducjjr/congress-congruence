"""Pre-built member and state pages, the sitemap and link previews (scripts/build_profiles.py),
built from a fake API that answers in the real API's shapes."""

import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("build_profiles", ROOT / "scripts" / "build_profiles.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)

SEN = {"bioguide_id": "C001098", "name": "Ted Cruz", "chamber": "senate", "state": "TX", "district": None,
       "seat": "TX", "party": "Republican", "caucus": None}
REP = {"bioguide_id": "F000001", "name": "Pat Fox", "chamber": "house", "state": "TX", "district": 7,
       "seat": "TX-7", "party": "Independent", "caucus": "Democrat"}
FORMER = {"bioguide_id": "F000002", "name": "Pat Fox", "chamber": "house", "state": "TX", "district": 2,
          "seat": "TX-2", "party": "Democrat", "caucus": None, "left_office": "2023-01-03"}
SCORES = [{"organization": "Cooperative Election Study", "surveyed_votes": 5, "clear_majority": 4, "with_majority": 3}]


def item(agreement, match="same", kind="survey"):
    return {"survey": "CES 2022", "kind": kind, "item": "CC22_1", "question": "Expand background checks <for guns>",
            "note": None, "match": match, "position": "yea", "support_side": "yea", "sided_with": "support",
            "agreement": agreement,
            "vote": {"roll_call_id": "s-117-2-1", "date": "2022-06-23", "question": "On Passage", "result": "Passed",
                     "yea_total": 65, "nay_total": 33, "congress": 117,
                     "official_url": "https://www.senate.gov/x"},
            "constituents": {"area": "state", "area_label": "TX", "support_pct": 71.2, "range_pct": [68.0, 74.4],
                             "majority": "support", "respondents": 3000, "residents": 29_000_000, "area_note": None}}


def fake_api(path):
    if path.startswith("/v1/states/"):
        code = path.rsplit("/", 1)[1]
        if code != "TX":
            return {"state": code, "name": bp.STATE_NAMES[code], "residents": None, "members": [], "former": [], "opinion": []}
        return {"state": "TX", "name": "Texas", "residents": 29_500_000,
                "members": [{**SEN, "scores": SCORES}, {**REP, "scores": []}],
                "former": [{**FORMER, "scores": []}],
                "opinion": [{"survey": "CES 2022", "item": "CC22_1", "question": "Expand background checks",
                             "kind": "survey", "source": {"organization": "Cooperative Election Study", "title": "CES",
                                                          "fielded": "Fall 2022"},
                             "support_pct": 71.2, "range_pct": [68.0, 74.4], "majority": "support",
                             "respondents": 3000, "area_note": None,
                             "senate_votes": [{"bioguide_id": "C001098", "name": "Ted Cruz", "sided_with": "oppose",
                                               "match": "same", "agreement": "against"}]}]}
    m = re.match(r"/v1/members/(\w+)(/\w+)?", path)
    mid, part = m.group(1), m.group(2)
    base = {"C001098": SEN, "F000001": REP, "F000002": FORMER}[mid]
    if part is None:
        return {**base, "serving": mid != "F000002", "left_office": base.get("left_office"),
                "population": {"residents": 29_500_000, "area": base["seat"]},
                "stats": {"congress": 119, "chamber": base["chamber"], "votes_total": 600, "votes_missed": 12,
                          "missed_pct": 2.0, "party_votes": 500, "with_party": 480, "with_party_pct": 96.0},
                "seats": [{"chamber": base["chamber"], "seat": base["seat"], "start": "2013-01-03", "end": None}]}
    if part == "/opinion":
        if mid != "C001098":
            return {"area": base["seat"], "summary": {"surveyed_votes": 0}, "by_source": [], "items": []}
        return {"area": "TX", "summary": SCORES[0], "by_source": SCORES,
                "items": [item("with"), item("against"), item("too_close"), item("with", match="related")]}
    return {"votes": [{"roll_call_id": "s-119-2-5", "chamber": "senate", "date": "2026-10-01", "question": "On Passage",
                       "description": "A bill <about> things", "result": "Passed", "bill": {"label": "S. 5"},
                       "position": "nay", "official_url": "https://www.senate.gov/y"}]}


def built(tmp_path, images=False):
    (tmp_path / "about.html").write_text("x")
    (tmp_path / "index.html").write_text("x")
    info = bp.build(tmp_path, fake_api, "abc123", today=date(2026, 11, 10), images=images, log=lambda *_: None)
    return info


def test_addresses_are_names_and_stay_unique():
    slugs = bp.assign_slugs([SEN, REP, FORMER, {**SEN, "bioguide_id": "X000001", "name": "José Ñúñez", "state": "NM"}])
    assert slugs["C001098"] == "ted-cruz"
    assert slugs["X000001"] == "jose-nunez"
    # Two Pat Foxes from the same state: both get their ID
    assert slugs["F000001"] == "pat-fox-tx-f000001" and slugs["F000002"] == "pat-fox-tx-f000002"
    assert bp.assign_slugs([REP, {**FORMER, "state": "OK"}]) == {"F000001": "pat-fox-tx", "F000002": "pat-fox-ok"}


def test_member_page_has_the_figures_as_text(tmp_path):
    built(tmp_path)
    page = (tmp_path / "members" / "ted-cruz" / "index.html").read_text()
    assert "<title>Ted Cruz: voting record vs. what voters said · US Congress vs Voters</title>" in page
    assert '<base href="/">' in page and 'href="/members/ted-cruz/#main"' in page      # skip link stays on the page
    assert '<link rel="canonical" href="https://uscongressvsvoters.org/members/ted-cruz/">' in page
    assert "voted with <strong>3 of 4</strong> surveyed votes where Texas's estimated majority was clear" in page
    assert "Senator for Texas" in page and 'href="index.html#TX/C001098_Ted_Cruz"' in page
    assert "Related bill, not counted" in page and "Too close to call" in page
    assert "&lt;for guns&gt;" in page and "<for guns>" not in page and "&lt;about&gt;" in page     # escaped
    assert "missed 12 of 600 Senate votes (2%)" in page
    assert "Figures as of November 10, 2026" in page
    assert "{{" not in page


def test_party_is_only_ever_inside_hideable_party_marks(tmp_path):
    built(tmp_path)
    for path in (tmp_path / "members").rglob("index.html"):
        page = path.read_text()
        head, body = page.split("<body", 1)
        assert "Republican" not in head and "Democrat" not in head, path      # title, description, previews
        body = re.sub(r'<(span|td|th)[^>]*class="party"[^>]*>.*?</\1>', "", body, flags=re.S)
        assert "Republican" not in body and "Democrat" not in body, path
    page = (tmp_path / "members" / "pat-fox-tx-f000001" / "index.html").read_text()
    assert '<span class="party"> · Independent, caucuses with the Democrats</span>' in page


def test_state_pages_index_and_sitemap(tmp_path):
    info = built(tmp_path)
    page = (tmp_path / "states" / "texas" / "index.html").read_text()
    assert "<h1>Texas</h1>" in page and "About 29.5 million residents" in page
    assert '<a href="members/ted-cruz/">Ted Cruz</a>' in page
    assert "<strong>3 of 4</strong> · Cooperative Election Study" in page
    assert "Former members with votes on this site (1)" in page
    assert "Most support: 71.2% (likely 68–74.4%)" in page and "against the proposal" in page
    assert (tmp_path / "states" / "new-york" / "index.html").exists()
    idx = (tmp_path / "members" / "index.html").read_text()
    assert '<a href="members/pat-fox-tx-f000002/">Pat Fox</a>' in idx
    assert json.loads((tmp_path / "members" / "slugs.json").read_text())["C001098"] == "ted-cruz"
    sm = (tmp_path / "sitemap.xml").read_text()
    for loc in ("https://uscongressvsvoters.org/", "https://uscongressvsvoters.org/about.html",
                "https://uscongressvsvoters.org/members/ted-cruz/", "https://uscongressvsvoters.org/states/texas/"):
        assert f"<loc>{loc}</loc>" in sm
    assert info["members"] == 3


def test_preview_images(tmp_path):
    import pytest
    pytest.importorskip("PIL")
    built(tmp_path, images=True)
    from PIL import Image
    img = Image.open(tmp_path / "members" / "ted-cruz" / "preview.png")
    assert img.size == (1200, 630)
    page = (tmp_path / "members" / "ted-cruz" / "index.html").read_text()
    assert '<meta property="og:image" content="https://uscongressvsvoters.org/members/ted-cruz/preview.png">' in page
    assert (tmp_path / "states" / "texas" / "preview.png").exists()


def test_regular_pages_have_link_previews(tmp_path):
    spec2 = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    bs = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(bs)
    bs.build(tmp_path, "v1")
    home = (tmp_path / "index.html").read_text()
    assert '<link rel="canonical" href="https://uscongressvsvoters.org/">' in home
    assert '<meta property="og:image" content="https://uscongressvsvoters.org/preview.png">' in home
    assert "<base" not in home
    assert (tmp_path / "preview.png").exists()
    assert "Sitemap: https://uscongressvsvoters.org/sitemap.xml" in (tmp_path / "robots.txt").read_text()


def test_time_in_office():
    assert bp.tenure_words(bp.months_between("2012-11-13", "2026-11-10")) == "13 years, 11 months"
    assert bp.tenure_words(bp.months_between("2019-01-03", "2023-01-03")) == "4 years"
    assert bp.tenure_words(bp.months_between("2026-11-01", "2026-11-10")) == "less than a month"


def test_member_page_says_how_long_in_each_seat(tmp_path):
    built(tmp_path)
    page = (tmp_path / "members" / "ted-cruz" / "index.html").read_text()
    assert "<strong>Seat held:</strong> Senator for TX, 2013–now (13 years, 10 months)." in page


def test_features_page_counts_come_from_the_api(tmp_path):
    spec2 = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    bs = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(bs)
    bs.build(tmp_path, "v1")

    def api(path):
        if path.startswith("/v1/votes/filters"):
            return {"congresses": [{"congress": 119, "votes": {"house": 1000, "senate": 500}},
                                   {"congress": 118, "votes": {"house": 2000}}],
                    "topics": [{"name": "Health", "votes": 9000}, {"name": "Taxation", "votes": 10},
                               {"name": "Economics and Public Finance", "votes": 7465},
                               {"name": "Civil Rights and Liberties, Minority Issues", "votes": 180}]
                              + [{"name": f"Other {i}", "votes": 1} for i in range(30)]}
        return {"total": 160}
    assert bp.fill_feature_counts(tmp_path, api, today=date(2026, 12, 1))
    page = (tmp_path / "features.html").read_text()
    assert '<span data-count="votes">3,500</span> House and Senate votes' in page
    assert '<span data-count="house">3,000</span>' in page and '<span data-count="senate">500</span>' in page
    assert '<span data-count="surveyed">160</span>' in page and '<span data-count="month">December 2026</span>' in page
    assert '<span data-count="topics">34</span> subject areas' in page and '<span data-count="more-topics">18</span>' in page
    assert '<span data-topic="Civil Rights and Liberties, Minority Issues">180</span>' in page
    chips = page.split("data-topics>")[1].split("</ul>")[0]
    assert chips.index('topic=Health"') < chips.index("topic=Economics") < chips.index("topic=Taxation")
    assert chips.count("<li") == 17 and chips.rstrip().endswith("</li>")       # 16 topics + "and N more"
