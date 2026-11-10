"""The website builder: every page gets the shared frame, its nav item marked, and versioned assets."""

import importlib.util
import re
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


TEXT_SELECTORS = re.compile(r"(^|[\s,>])(main|section|article|p|h[1-6]|ul|ol|li|blockquote|\.[\w-]*(page|lede|prose|hero|text|head)[\w-]*)\b")


def text_width_limits(css: str) -> list[str]:
    """Rules (outside @media) that cap the width of running text: max-width on main, its
    sections, headings, paragraphs and lists, or on page, lede, prose, hero, text and head classes."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    found = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if re.search(r"(^|;|\s)max-width\s*:(?!\s*(none|100%))", body) and TEXT_SELECTORS.search(selector.strip()):
            found.append(selector.strip())
    return found


def test_page_text_fills_the_screen_width():
    """Site rule: text adjusts to the screen width; no page caps it (see site.css, "Main")."""
    sheets = {"site.css": (build_site.SITE / "site.css").read_text()}
    for page in (build_site.SITE / "pages").glob("*"):
        if page.suffix in (".md", ".html"):
            meta, _ = build_site.read_page(page)
            sheets[page.name] = meta.get("head", "")
    limits = {name: text_width_limits(css) for name, css in sheets.items()}
    assert {k: v for k, v in limits.items() if v} == {}
    assert text_width_limits(".x-page { max-width: 60rem; } .card img { max-width: 20rem; } main.prose { max-width: none; }"
                             " @media (max-width: 500px) { p { max-width: 10rem; } }") == [".x-page"]


def test_updates_feed(tmp_path):
    import xml.etree.ElementTree as ET
    build_site.build(tmp_path, "x")
    rss = ET.parse(tmp_path / "feed.xml").getroot()
    items = rss.findall("./channel/item")
    titles = [i.findtext("title") for i in items]
    assert "New: Hide party labels" in titles and "Correction: TikTok bill (CES 2024)" in titles
    assert len({i.findtext("guid") for i in items}) == len(items)            # every entry its own ID
    dates = [i.findtext("pubDate") for i in items]
    assert dates[0].startswith("Tue, 10 Nov 2026") and dates[-1].startswith("Sat, 07 Nov 2026")
    first = items[0].findtext("description")
    assert 'href="https://uscongressvsvoters.org/sources.html#senate"' in first   # links work in a reader
    home = (tmp_path / "index.html").read_text()
    assert 'type="application/rss+xml"' in home and 'href="feed.xml"' in home


def test_text_on_the_accent_colour_follows_dark_mode():
    """In dark mode the accent (--mark) is light, so text on it must use --surface, not white
    (white on it measured 2:1 contrast; 4.5:1 is the minimum)."""
    site = ROOT / "site"
    files = [site / "site.css", *(site / "pages").glob("*.html"), ROOT / "web" / "cc-member-panel.js"]
    for f in files:
        for rule in re.findall(r"\{[^{}]*\}", f.read_text()):
            if re.search(r"background(-color)?\s*:\s*var\(--mark\)", rule):
                assert not re.search(r"(?<![-\w])color\s*:\s*(#fff\b|#ffffff\b|white\b)", rule), (f.name, rule)
