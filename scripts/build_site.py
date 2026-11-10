"""Build the website: every page in site/pages/ wrapped in the shared header and footer.

    python scripts/build_site.py [--out build/site] [--version abc1234]

Pages are Markdown (.md) or HTML (.html) files that start with a short header:

    ---
    title: Sources
    description: One sentence for search results and link previews.
    ---

Optional header keys: head (extra tags for <head>), main_class, draft (true = not built yet).
Settings in site/site.yaml (e.g. source_url) fill {{source_url}}-style placeholders on any page.
Markdown pages get the "prose" layout; headings get link anchors; {#id} after a heading sets
its anchor. The panel script, site.css and site.js are copied alongside, and every reference
to them carries ?v=<version> so browsers fetch the new copy after each update.
"""

import argparse
import html
import re
import shutil
import subprocess
from pathlib import Path

import markdown
import yaml

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

# Header navigation, in order: (file, label). Pages not listed here still get built.
NAV = [
    ("index.html", "Find your members"),
    ("state.html", "States"),
    ("compare.html", "Compare"),
    ("votes.html", "All votes"),
    ("surveyed.html", "Surveyed votes"),
    ("sources.html", "Sources"),
    ("methods.html", "Methods"),
    ("faq.html", "FAQ"),
    ("about.html", "About"),
]
ASSETS = {"site.css": SITE / "site.css", "site.js": SITE / "site.js", "cards.js": SITE / "cards.js",
          "cc-member-panel.js": ROOT / "web" / "cc-member-panel.js"}


def read_page(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise ValueError(f"{path.name}: must start with a --- header --- block")
    meta = yaml.safe_load(m.group(1)) or {}
    for key in ("title", "description"):
        if not meta.get(key):
            raise ValueError(f"{path.name}: header needs '{key}'")
    return meta, text[m.end():]


def render_body(path: Path, body: str) -> str:
    if path.suffix == ".md":
        md = markdown.Markdown(extensions=["tables", "attr_list", "toc", "def_list", "md_in_html"],
                               extension_configs={"toc": {"permalink": False, "toc_depth": "2-3"}})
        return f'<article class="prose-body">\n{md.convert(body)}\n</article>'
    return body


def nav_html(current: str) -> str:
    items = []
    for file, label in NAV:
        cur = ' aria-current="page"' if file == current else ""
        items.append(f'        <li><a href="{file}"{cur}>{html.escape(label)}</a></li>')
    return "\n".join(items)


def stamp(text: str, version: str) -> str:
    """Add ?v=<version> to references to our own assets so updates aren't hidden by caches."""
    for name in ASSETS:
        text = re.sub(rf'(["\']){re.escape(name)}(["\'])', rf"\g<1>{name}?v={version}\g<2>", text)
    return text


def load_settings() -> dict:
    return yaml.safe_load((SITE / "site.yaml").read_text(encoding="utf-8")) or {}


def wrap(frame: str, settings: dict, meta: dict, body_html: str, name: str, version: str,
         slug: str | None = None, main_class: str = "", url_path: str | None = None,
         image: str | None = None, base: bool = False) -> str:
    """One page in the shared header and footer. url_path is the page's address on the site
    (default: its file name; "" for the home page); image is its link-preview picture (default:
    the site's own). base=True is for pages in folders (members/..., states/...): every relative
    link then resolves from the site root, so the shared header, footer and scripts work there too."""
    site_url = str(settings.get("site_url", "")).rstrip("/")
    if url_path is None:
        url_path = "" if name == "index.html" else name
    canonical = f"{site_url}/{url_path}"
    image = image or "preview.png"
    page = (frame
            .replace("{{title}}", html.escape(meta["title"]))
            .replace("{{description}}", html.escape(meta["description"], quote=True))
            .replace("{{head}}", meta.get("head", "").rstrip())
            .replace("{{base}}", '  <base href="/">' if base else "")
            .replace("{{canonical}}", html.escape(canonical, quote=True))
            .replace("{{og_image}}", html.escape(f"{site_url}/{image}", quote=True))
            .replace("{{og_image_alt}}", html.escape(meta.get("image_alt", f"{meta['title']} · US Congress vs Voters"), quote=True))
            .replace("{{slug}}", slug or Path(name).stem)
            .replace("{{main_class}}", main_class)
            .replace("{{nav}}", nav_html(name))
            .replace("{{features_current}}", ' aria-current="page"' if name == "features.html" else "")
            .replace("{{body}}", body_html))
    if base:      # with <base href="/">, the skip link must name this page or it jumps to the home page
        page = page.replace('href="#main"', f'href="/{html.escape(url_path, quote=True)}#main"')
    for key, value in settings.items():                  # {{source_url}} etc. from site/site.yaml
        page = page.replace("{{" + key + "}}", html.escape(str(value), quote=True))
    return stamp(page, version)


def build(out: Path, version: str) -> list[str]:
    frame = (SITE / "frame.html").read_text(encoding="utf-8")
    settings = load_settings()
    out.mkdir(parents=True, exist_ok=True)
    built = []
    for path in sorted((SITE / "pages").glob("*")):
        if path.suffix not in (".md", ".html"):
            continue
        meta, body = read_page(path)
        if meta.get("draft"):
            continue
        name = path.stem + ".html"
        page = wrap(frame, settings, meta, render_body(path, body), name, version,
                    main_class=meta.get("main_class", "prose" if path.suffix == ".md" else ""))
        (out / name).write_text(page, encoding="utf-8")
        built.append(name)
    (out / "feed.xml").write_text(feed_xml(settings), encoding="utf-8")
    for name, src in ASSETS.items():
        shutil.copyfile(src, out / name)
    # Files served as they are, e.g. .well-known/security.txt
    static = SITE / "static"
    if static.exists():
        shutil.copytree(static, out, dirs_exist_ok=True)
    return built


# ---- the updates feed (feed.xml): "Recently added" (upcoming.md) and the corrections log, read
# from the pages themselves, so it needs no upkeep of its own. Each entry is a bullet under a date
# line in bold ("**November 10, 2026**").

FEED_SOURCES = [("upcoming.md", "recent", "New"), ("corrections.md", None, "Correction")]
DATE_LINE = re.compile(r"^\*\*([A-Z][a-z]+ \d{1,2}, \d{4})\*\*\s*$")


def feed_entries(settings: dict) -> list[dict]:
    from datetime import datetime
    site_url = str(settings.get("site_url", "")).rstrip("/")
    entries = []
    for page, section, kind in FEED_SOURCES:
        _, body = read_page(SITE / "pages" / page)
        if section:                       # only that section: from its heading to the next ## heading
            m = re.search(r"^## .*\{#" + section + r"\}\s*$(.*?)(?=^## |\Z)", body, re.M | re.S)
            body = m.group(1) if m else ""
        day, bullets = None, []
        for line in body.splitlines():
            d = DATE_LINE.match(line.strip())
            if d:
                day = datetime.strptime(d.group(1), "%B %d, %Y")
            elif line.startswith("- ") and day:
                bullets.append([day, line[2:].strip()])
            elif line.startswith("  ") and line.strip() and bullets and day:
                bullets[-1][1] += " " + line.strip()
        anchor = f"#{section}" if section else ""
        for n, (day, text) in enumerate(bullets):
            for key, value in settings.items():
                text = text.replace("{{" + key + "}}", str(value))
            html_text = markdown.markdown(text)
            html_text = re.sub(r'href="(?!https?:|mailto:|#)([^"]*)"', lambda m: f'href="{site_url}/{m.group(1)}"', html_text)
            plain = html.unescape(re.sub(r"<[^>]+>", "", html_text)).strip()
            first = re.match(r"\*\*(.+?)\*\*", text)
            title = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", first.group(1)).rstrip(".,:") if first else plain
            if first and not re.match(r"\*\*.+?[.,:]\*\*", text):     # "**Compare two members** side by side."
                title = re.split(r"(?<=[a-z])[.:](?:\s|$)", plain)[0].rstrip(".,")
            entries.append({"date": day, "kind": kind, "title": f"{kind}: {title}", "html": html_text,
                            "link": f"{site_url}/{page.replace('.md', '.html')}{anchor}",
                            "guid": f"{site_url}/{page.replace('.md', '.html')}#{day:%Y-%m-%d}-{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')}"})
    entries.sort(key=lambda e: e["date"], reverse=True)       # stable: page order kept within a day
    return entries


def feed_xml(settings: dict) -> str:
    from email.utils import format_datetime
    from datetime import timezone
    site_url = str(settings.get("site_url", "")).rstrip("/")
    entries = feed_entries(settings)
    items = []
    for e in entries:
        when = format_datetime(e["date"].replace(hour=12, tzinfo=timezone.utc))
        items.append(f"""  <item>
    <title>{html.escape(e['title'])}</title>
    <link>{html.escape(e['link'])}</link>
    <guid isPermaLink="false">{html.escape(e['guid'])}</guid>
    <pubDate>{when}</pubDate>
    <category>{e['kind']}</category>
    <description>{html.escape(e['html'])}</description>
  </item>""")
    built = format_datetime(entries[0]["date"].replace(hour=12, tzinfo=timezone.utc)) if entries else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>US Congress vs Voters: updates</title>
  <link>{site_url}/upcoming.html</link>
  <atom:link href="{site_url}/feed.xml" rel="self" type="application/rss+xml"/>
  <description>New sources, features and every correction to US Congress vs Voters.</description>
  <language>en-us</language>
  <lastBuildDate>{built}</lastBuildDate>
{chr(10).join(items)}
</channel>
</rss>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "build" / "site"))
    ap.add_argument("--version", default=None)
    args = ap.parse_args()
    version = args.version or subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                             capture_output=True, text=True).stdout.strip() or "dev"
    built = build(Path(args.out), version)
    print(f"Built {len(built)} pages into {args.out} (version {version}): {', '.join(built)}")


if __name__ == "__main__":
    main()
