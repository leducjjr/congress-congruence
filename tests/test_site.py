"""The website builder: every page gets the shared frame, its nav item marked, and versioned assets."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
build_site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_site)


def test_builds_every_page_in_the_frame(tmp_path):
    built = build_site.build(tmp_path, "abc123")
    assert {"index.html", "surveyed.html", "search.html", "sources.html", "methods.html", "glossary.html", "about.html",
            "privacy.html", "contact.html", "state.html", "compare.html", "votes.html", "faq.html",
            "corrections.html"} <= set(built)
    assert (tmp_path / "cards.js").exists() and 'src="cards.js?v=abc123"' in (tmp_path / "surveyed.html").read_text()
    for name in built:
        page = (tmp_path / name).read_text()
        # The current page is marked once: its menu link, or the header's Features button.
        current = name in dict(build_site.NAV) or name == "features.html"
        assert page.count('aria-current="page"') == (1 if current else 0), name
        assert 'href="site.css?v=abc123"' in page and 'src="site.js?v=abc123"' in page
        assert "{{" not in page, f"{name}: unfilled placeholder"
        assert 'href="https://github.com/leducjjr/congress-congruence">Source code</a>' in page
        assert '<main id="main"' in page and 'class="site-footer"' in page
    assert 'src="cc-member-panel.js?v=abc123"' in (tmp_path / "index.html").read_text()
    for asset in ("cc-member-panel.js", "site.css", "site.js"):
        assert (tmp_path / asset).exists()


def test_contact_addresses_are_not_written_out_and_security_txt_is_published(tmp_path):
    build_site.build(tmp_path, "x")
    contact = (tmp_path / "contact.html").read_text()
    assert 'data-email="corrections"' in contact and "corrections (at) uscongressvsvoters.org" in contact
    for page in tmp_path.glob("*.html"):                       # nothing for address harvesters, anywhere
        assert "@uscongressvsvoters.org" not in page.read_text(), page.name
    assert 'data-email="corrections"' in (tmp_path / "about.html").read_text()
    sec = (tmp_path / ".well-known" / "security.txt").read_text()
    assert "Contact: mailto:security@uscongressvsvoters.org" in sec and "Expires: " in sec


def test_reference_anchors_the_panel_links_to_exist(tmp_path):
    build_site.build(tmp_path, "x")
    sources = (tmp_path / "sources.html").read_text()
    # The panel links each survey organization to sources.html#<slug of its name>.
    for anchor in ("surveys", "cooperative-election-study", "program-for-public-consultation",
                   "democracy-fund-ucla-nationscape"):
        assert f'id="{anchor}"' in sources
    assert 'data-surveys="Program for Public Consultation"' in sources
    assert 'id="too-close-to-call"' in (tmp_path / "glossary.html").read_text()
    assert '<div class="toc">' in sources and ">Sources</a>" not in sources.split('<div class="toc">')[1][:200]


def test_party_blind_switch_on_every_page(tmp_path):
    build_site.build(tmp_path, "x")
    for page in tmp_path.glob("*.html"):
        text = page.read_text()
        assert 'id="party-blind"' in text and 'data-party-blind' in text, page.name
