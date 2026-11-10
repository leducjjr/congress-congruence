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


def build(out: Path, version: str) -> list[str]:
    frame = (SITE / "frame.html").read_text(encoding="utf-8")
    settings = yaml.safe_load((SITE / "site.yaml").read_text(encoding="utf-8")) or {}
    out.mkdir(parents=True, exist_ok=True)
    built = []
    for path in sorted((SITE / "pages").glob("*")):
        if path.suffix not in (".md", ".html"):
            continue
        meta, body = read_page(path)
        if meta.get("draft"):
            continue
        name = path.stem + ".html"
        page = (frame
                .replace("{{title}}", html.escape(meta["title"]))
                .replace("{{description}}", html.escape(meta["description"], quote=True))
                .replace("{{head}}", meta.get("head", "").rstrip())
                .replace("{{slug}}", path.stem)
                .replace("{{main_class}}", meta.get("main_class", "prose" if path.suffix == ".md" else ""))
                .replace("{{nav}}", nav_html(name))
                .replace("{{body}}", render_body(path, body)))
        for key, value in settings.items():                  # {{source_url}} etc. from site/site.yaml
            page = page.replace("{{" + key + "}}", html.escape(str(value), quote=True))
        (out / name).write_text(stamp(page, version), encoding="utf-8")
        built.append(name)
    for name, src in ASSETS.items():
        shutil.copyfile(src, out / name)
    # Files served as they are, e.g. .well-known/security.txt
    static = SITE / "static"
    if static.exists():
        shutil.copytree(static, out, dirs_exist_ok=True)
    return built


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
