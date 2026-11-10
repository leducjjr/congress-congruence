"""Pre-built pages for every member of Congress and every state, a sitemap, and link-preview images.

    python scripts/build_profiles.py --out build/site [--api http://127.0.0.1:8000] [--version abc1234]

The interactive pages (index.html#TX/C001098, state.html?s=TX) are drawn in the browser, so search
engines and link previews see one empty page for all of them. These pages carry the same figures as
plain text, at addresses that can be found and shared:

    members/<name>/     one per member (current, and former members with votes on the site)
    members/            every member, by state
    states/<name>/      one per state: its members and what its residents told surveys
    states/             every state
    members/slugs.json  member ID -> address, so the interactive page can offer the shareable link
    sitemap.xml         every page on the site, for search engines

They're built from the site's own read-only API (run on the server, where the API is), so they show
exactly what the interactive pages show, as of the day they're built; each one links to the
interactive page for the latest. scripts/publish_web.sh builds them, and the weekly `pages` job
(scripts/run_job.sh) rebuilds them. Preview images need Pillow; without it, pages use the site's
own preview image.
"""

import argparse
import concurrent.futures
import html
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_site  # noqa: E402

ROOT = build_site.ROOT
FONTS = ROOT / "assets" / "fonts"

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia", "PR": "Puerto Rico", "GU": "Guam",
    "VI": "U.S. Virgin Islands", "AS": "American Samoa", "MP": "Northern Mariana Islands",
}
POSITION = {"yea": "Yea", "nay": "Nay", "present": "Present", "not_voting": "Did not vote", "other": "Other"}
MAJORITY = {"support": "Most support", "oppose": "Most oppose", "too_close": "Too close to call"}
SIDE = {"support": "for the proposal", "oppose": "against the proposal"}

def e(text) -> str:
    """Escaped for HTML text and double-quoted attributes (apostrophes kept as they are)."""
    return html.escape(str(text)).replace("&#x27;", "'")


# ------------------------------------------------------------------------------------- helpers

def http_getter(base: str):
    base = base.rstrip("/")

    def get(path: str):
        req = Request(base + path, headers={"Accept": "application/json", "User-Agent": "build_profiles"})
        try:
            with urlopen(req, timeout=60) as r:
                return json.load(r)
        except HTTPError as err:
            if err.code == 404:
                return None
            raise
    return get


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "member"


def assign_slugs(members: list[dict]) -> dict[str, str]:
    """Member ID -> address. The name alone where it's unique; otherwise name and state; then the ID.
    Members are given in a stable order (current members first), so addresses don't shuffle."""
    by_name: dict[str, list[dict]] = {}
    for m in members:
        by_name.setdefault(slugify(m["name"]), []).append(m)
    out = {}
    for base, group in by_name.items():
        if len(group) == 1:
            out[group[0]["bioguide_id"]] = base
            continue
        states = [m["state"] for m in group]
        for m in group:
            s = f"{base}-{m['state'].lower()}"
            out[m["bioguide_id"]] = s if states.count(m["state"]) == 1 else f"{s}-{m['bioguide_id'].lower()}"
    return out


def state_slug(code: str) -> str:
    return slugify(STATE_NAMES.get(code, code))


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def fmt_date(d: str | None) -> str:
    if not d:
        return ""
    y, m, dd = (int(x) for x in str(d)[:10].split("-"))
    return f"{date(y, m, dd):%B} {dd}, {y}"


def people(n: int | None) -> str:
    if not n:
        return ""
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}".rstrip("0").rstrip(".") + " million"
    return f"{round(n, -3):,}"


def seat_words(m: dict) -> str:
    """'Senator for Texas' / 'Representative for Texas's 7th district' (no party: shown separately)."""
    name = STATE_NAMES.get(m["state"], m["state"])
    if m["chamber"] == "senate":
        return f"Senator for {name}"
    d = m.get("district")
    if d in (None, -1):
        return f"Delegate for {name}" if m["state"] in ("DC", "PR", "GU", "VI", "AS", "MP") else f"Representative for {name}"
    if d == 0:
        if m["state"] in ("DC", "PR", "GU", "VI", "AS", "MP"):
            return f"{'Resident Commissioner' if m['state'] == 'PR' else 'Delegate'} for {name}"
        return f"Representative for {name} (one district, the whole state)"
    return f"Representative for {name}'s {ordinal(d)} district"


def party_text(m: dict) -> str:
    if not m.get("party"):
        return ""
    if m.get("caucus") and m["caucus"] != m["party"]:
        return f"{m['party']}, caucuses with the {m['caucus']}s"
    return m["party"]


def score_line(s: dict, where: str) -> str:
    """One survey organization's count, in the panel's words."""
    org = f"<strong>{e(s['organization'])}</strong>: "
    if s.get("clear_majority"):
        return (f"{org}voted with <strong>{s['with_majority']} of {s['clear_majority']}</strong> surveyed votes "
                f"where {e(where)} estimated majority was clear.")
    if s.get("surveyed_votes"):
        return f"{org}on these votes, {e(where)} estimated opinion was too close to call."
    return f"{org}only related votes, which aren't counted."


def plain_score(s: dict) -> str:
    if s.get("clear_majority"):
        return f"voted with the majority of constituents on {s['with_majority']} of {s['clear_majority']} surveyed votes ({s['organization']})"
    return ""


# ------------------------------------------------------------------------------------- pages

def member_page(m: dict, opinion: dict | None, votes: list[dict], slugs: dict, today: date) -> tuple[dict, str]:
    sid, state = m["bioguide_id"], m["state"]
    sname = STATE_NAMES.get(state, state)
    serving = m.get("serving", True)
    role = seat_words(m)
    if not serving:
        role = "Former " + role[0].lower() + role[1:]
    by_source = (opinion or {}).get("by_source") or []
    where = f"{sname}'s" if m["chamber"] == "senate" else "the district's"

    scores = [plain_score(s) for s in by_source if plain_score(s)]
    desc = f"{m['name']}, {role[0].lower() + role[1:]}: how they voted"
    desc += (f", and how their votes compared with what people they represent told independent surveys. "
             f"They {scores[0]}." if scores else
             ", attendance, and how their votes compared with what people they represent told independent surveys.")
    meta = {"title": f"{m['name']}: voting record vs. what voters said", "description": desc,
            "image_alt": f"{m['name']}, {role}" + (f": {scores[0]}" if scores else "")}

    live = f"index.html#{state}/{sid}"
    p = [f'<div class="page-head profile-head">',
         f'<p class="crumbs"><a href="members/">All members</a> › <a href="states/{state_slug(state)}/">{e(sname)}</a></p>',
         f"<h1>{e(m['name'])}</h1>",
         f'<p class="lede">{e(role)}<span class="party">{" · " + e(party_text(m)) if party_text(m) else ""}</span>'
         + (f"; served until {fmt_date(m.get('left_office'))}" if not serving and m.get("left_office") else "")
         + "</p>",
         f'<p class="profile-actions"><a class="button" href="{e(live)}">Open the full interactive page</a> '
         f'<a href="compare.html?a={e(sid)}">Compare with another member</a> · '
         f'<a href="states/{state_slug(state)}/">All members from {e(sname)}</a></p>',
         "</div>"]

    seats = m.get("seats") or []
    if seats:
        bits = []
        for x in seats:
            r = "Senator for" if x["chamber"] == "senate" else "Representative for"
            span = f"{str(x['start'])[:4]}–{str(x['end'])[:4] if x.get('end') else 'now'}"
            bits.append(f"{r} {e(x['seat'])}, {span}")
        p.append(f'<p><strong>Seats held:</strong> {" · ".join(bits)}.</p>')
    pop = m.get("population")
    if pop and pop.get("residents"):
        if m["chamber"] == "senate":
            p.append(f"<p>{e(sname)} has about {people(pop['residents'])} residents, represented by two senators.</p>")
        else:
            p.append(f"<p>{e(pop['area'])} has about {people(pop['residents'])} residents.</p>")

    # ---- surveyed votes
    items = (opinion or {}).get("items") or []
    p.append('<h2 id="surveyed">Votes compared with what constituents said</h2>')
    if not items:
        p.append("<p>None of this member's votes on the site were on proposals that independent surveys asked "
                 "people about. Their full voting record is on the interactive page.</p>")
    else:
        if by_source:
            p.append('<ul class="score-lines">' + "".join(f"<li>{score_line(s, where)}</li>" for s in by_source) + "</ul>")
        p.append("<p class=\"meta\">Each survey is shown on its own, never combined. Votes marked "
                 "<em>related</em> were on a bill close to what was asked, and aren't counted. "
                 '<a href="methods.html">How the estimates work</a>.</p>')
        rows = []
        for i in reversed(items):
            c = i["constituents"]
            if i["match"] == "related":
                verdict, cls = "Related bill, not counted", "not_surveyed"
            else:
                verdict = {"with": "With the majority", "against": "Against the majority",
                           "too_close": "Too close to call", "did_not_vote": "Didn't vote"}[i["agreement"]]
                cls = i["agreement"]
            side = SIDE.get(i.get("sided_with") or "", "")
            voted = f"{POSITION.get(i['position'], i['position'])}" + (f" ({side})" if side else "")
            lo, hi = c["range_pct"]
            opinion_txt = (f"{MAJORITY[c['majority']]} ({c['support_pct']:g}% support"
                           + (")" if i.get("kind") == "ballot" else f", likely {lo:g}–{hi:g}%)"))
            if i.get("kind") == "ballot" and c.get("area_note"):
                opinion_txt += f" · {e(c['area_note'])}"
            rows.append(
                f"<tr><td class=\"lead\">{e(i['question'])}<br><span class=\"meta\">{e(i['survey'])}</span></td>"
                f"<td data-label=\"Vote\">{fmt_date(i['vote']['date'])} · <a class=\"meta\" href=\"{e(i['vote']['official_url'])}\">official record</a></td>"
                f"<td data-label=\"How they voted\">{e(voted)}</td><td data-label=\"{e(c['area_label'])}\">{opinion_txt}</td>"
                f"<td class=\"verdict {cls}\">{verdict}</td></tr>")
        p.append('<div class="table-scroll"><table class="data-table stack"><thead><tr><th scope="col">Survey question</th>'
                 '<th scope="col">Vote</th><th scope="col">How they voted</th><th scope="col">What constituents said</th>'
                 '<th scope="col">Compared</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")

    # ---- attendance
    st = m.get("stats") or {}
    if st.get("votes_total"):
        line = (f"In the {ordinal(st['congress'])} Congress, {e(m['name'])} missed {st['votes_missed']:,} of "
                f"{st['votes_total']:,} {st['chamber'].title()} votes ({st['missed_pct']:g}%).")
        party = ""
        if st.get("party_votes") and st.get("with_party_pct") is not None:
            party = (f' <span class="party">On votes where most of their party voted one way, they voted with '
                     f"their party {st['with_party_pct']:g}% of the time.</span>")
        p.append(f'<h2 id="attendance">Attendance</h2><p>{line}{party}</p>')

    # ---- recent votes
    if votes:
        rows = []
        for v in votes:
            what = (f"{e(v['bill']['label'])}: " if v.get("bill") else "") + e(v.get("description") or v.get("question") or "Vote")
            rows.append(f"<tr><td class=\"lead\"><a href=\"{e(v['official_url'])}\">{what}</a>"
                        f"<br><span class=\"meta\">{e(v.get('question') or '')} · {e(v.get('result') or '')}</span></td>"
                        f"<td data-label=\"Date\">{fmt_date(v['date'])}</td>"
                        f"<td data-label=\"Their vote\">{e(POSITION.get(v['position'], v['position']))}</td></tr>")
        p.append('<h2 id="recent">Most recent votes</h2><div class="table-scroll"><table class="data-table stack"><thead><tr>'
                 '<th scope="col">Vote</th><th scope="col">Date</th><th scope="col">Their vote</th></tr></thead><tbody>'
                 + "".join(rows) + "</tbody></table></div>"
                 + f'<p><a href="{e(live)}">Every vote, with filters, on the interactive page</a>.</p>')

    p.append(f'<p class="meta asof">Figures as of {fmt_date(today.isoformat())}, from the official vote records and '
             'published survey data listed on the <a href="sources.html">Sources</a> page. The '
             f'<a href="{e(live)}">interactive page</a> always shows the latest. Found an error? '
             '<a href="contact.html#feedback">Tell us</a>.</p>')
    return meta, "\n".join(p)


def member_row(m: dict, slugs: dict, former: bool = False) -> str:
    scores = m.get("scores") or []
    cell = ('<span class="meta">No surveyed votes</span>' if not scores else
            "<br>".join(f"<strong>{s['with_majority']} of {s['clear_majority']}</strong> · {e(s['organization'])}"
                        if s.get("clear_majority") else f'<span class="meta">{e(s["organization"])}: none with a clear majority</span>'
                        for s in scores))
    href = f"members/{slugs[m['bioguide_id']]}/" if m["bioguide_id"] in slugs else f"index.html#{m['state']}/{m['bioguide_id']}"
    left = f'<td data-label="Left office">{fmt_date(m.get("left_office"))}</td>' if former else ""
    return (f'<tr><td class="lead"><a href="{e(href)}">{e(m["name"])}</a></td><td data-label="Seat">{e(m.get("seat") or "")}</td>'
            f'<td class="party" data-label="Party">{e(party_text(m))}</td>{left}<td data-label="Surveyed votes">{cell}</td></tr>')


def members_table(ms: list[dict], slugs: dict, former: bool = False) -> str:
    return ('<div class="table-scroll"><table class="data-table stack"><thead><tr><th scope="col">Member</th>'
            '<th scope="col">Seat</th><th scope="col" class="party">Party</th>'
            + ('<th scope="col">Left office</th>' if former else "")
            + '<th scope="col">Surveyed votes that went the way a clear majority where they live wanted</th></tr></thead><tbody>'
            + "".join(member_row(m, slugs, former) for m in ms) + "</tbody></table></div>")


def state_page(st: dict, slugs: dict, today: date) -> tuple[dict, str]:
    code, name = st["state"], st.get("name") or STATE_NAMES.get(st["state"], st["state"])
    senators = [m for m in st["members"] if m["chamber"] == "senate"]
    house = [m for m in st["members"] if m["chamber"] != "senate"]
    meta = {"title": f"{name}: members of Congress vs. what residents said",
            "description": (f"{name}'s senators and representatives, how each one's votes compared with what the "
                            f"people they represent told independent surveys, and what {name} residents said."),
            "image_alt": f"{name}'s members of Congress compared with what residents told surveys"}
    p = ['<div class="page-head profile-head">',
         '<p class="crumbs"><a href="states/">All states</a></p>',
         f"<h1>{e(name)}</h1>",
         f'<p class="lede">{"About " + people(st["residents"]) + " residents. " if st.get("residents") else ""}'
         f"{len(senators)} senator{'s' if len(senators) != 1 else ''} and {len(house)} House member{'s' if len(house) != 1 else ''} serving now.</p>",
         f'<p class="profile-actions"><a class="button" href="state.html?s={e(code)}">Open the interactive state page</a></p>',
         "</div>"]
    if senators:
        p += ['<h2 id="senate">Senators</h2>', members_table(senators, slugs)]
    if house:
        p += ['<h2 id="house">House</h2>', members_table(house, slugs)]
    if st.get("former"):
        p += [f'<details class="more"><summary>Former members with votes on this site ({len(st["former"])})</summary>',
              members_table(st["former"], slugs, former=True), "</details>"]

    if st.get("opinion"):
        p.append(f'<h2 id="opinion">What {e(name)} residents told surveys</h2>')
        p.append('<p class="meta">Estimated support statewide, with the likely range. Each survey is shown on its '
                 'own. Ballot measures are certified votes cast, so they have no range.</p>')
        rows = []
        for o in st["opinion"]:
            lo, hi = o["range_pct"]
            support = f"{o['support_pct']:g}%" + ("" if o.get("kind") == "ballot" else f" (likely {lo:g}–{hi:g}%)")
            sen = "; ".join(
                f'<a href="{e("members/" + slugs[s["bioguide_id"]] + "/") if s["bioguide_id"] in slugs else "index.html#" + code + "/" + s["bioguide_id"]}">{e(s["name"])}</a>: '
                + (SIDE.get(s.get("sided_with") or "", "didn't vote") + (", related vote" if s.get("match") == "related" else ""))
                for s in o.get("senate_votes", [])) or '<span class="meta">No Senate vote by a senator from here</span>'
            src = o.get("source") or {}
            rows.append(f"<tr><td class=\"lead\">{e(o['question'])}<br><span class=\"meta\">{e(src.get('organization') or o['survey'])}"
                        f"{' · ' + e(str(src['fielded'])) if src.get('fielded') else ''}</span></td>"
                        f"<td data-label=\"Residents\">{MAJORITY[o['majority']]}: {support}</td>"
                        f"<td data-label=\"Senators\">{sen}</td></tr>")
        p.append('<div class="table-scroll"><table class="data-table stack"><thead><tr><th scope="col">Question</th>'
                 '<th scope="col">Residents</th><th scope="col">How senators voted</th></tr></thead><tbody>'
                 + "".join(rows) + "</tbody></table></div>")
    p.append(f'<p class="meta asof">Figures as of {fmt_date(today.isoformat())}. The '
             f'<a href="state.html?s={e(code)}">interactive state page</a> always shows the latest.</p>')
    return meta, "\n".join(p)


def members_index(states: list[dict], slugs: dict) -> tuple[dict, str]:
    meta = {"title": "All members of Congress",
            "description": "Every current member of the House and Senate, and former members with votes on this site, by state."}
    p = ['<div class="page-head"><h1>All members of Congress</h1>',
         '<p class="lede">Every senator and representative serving now, and former members whose votes are on this '
         'site, by state. Each page shows their votes and how they compared with what the people they represent '
         'told independent surveys.</p></div>']
    jump = " · ".join(f'<a href="members/#{st["state"].lower()}">{e(st["state"])}</a>' for st in states if st["members"] or st["former"])
    p.append(f'<p class="jump-list">{jump}</p>')
    for st in states:
        if not (st["members"] or st["former"]):
            continue
        def li(m, former=False):
            extra = f" · left office {fmt_date(m.get('left_office'))}" if former else ""
            return (f'<li><a href="members/{slugs[m["bioguide_id"]]}/">{e(m["name"])}</a> '
                    f'<span class="meta">{e(m.get("seat") or "")}<span class="party"> · {e(m.get("party") or "")}</span>{extra}</span></li>')
        p.append(f'<h2 id="{st["state"].lower()}"><a href="states/{state_slug(st["state"])}/">{e(STATE_NAMES.get(st["state"], st["state"]))}</a></h2>')
        p.append('<ul class="member-list">' + "".join(li(m) for m in st["members"]) + "</ul>")
        if st["former"]:
            p.append('<details class="more"><summary>Former members</summary><ul class="member-list">'
                     + "".join(li(m, True) for m in st["former"]) + "</ul></details>")
    return meta, "\n".join(p)


def states_index(states: list[dict]) -> tuple[dict, str]:
    meta = {"title": "All states", "description": "Each state's members of Congress and what its residents told independent surveys."}
    items = "".join(f'<li><a href="states/{state_slug(st["state"])}/">{e(STATE_NAMES.get(st["state"], st["state"]))}'
                    f'<small>{e(st["state"])}</small></a></li>' for st in states)
    return meta, ('<div class="page-head"><h1>All states</h1><p class="lede">Each state\'s members of Congress, how '
                  "their surveyed votes compared with the people they represent, and what the state's residents told "
                  f'independent surveys.</p></div><ul class="state-grid">{items}</ul>')


def sitemap(site_url: str, paths: list[str], today: date) -> str:
    urls = "".join(f"  <url><loc>{e(site_url.rstrip('/') + '/' + p)}</loc><lastmod>{today.isoformat()}</lastmod></url>\n"
                   for p in paths)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n'


PAGE_CSS = """<style>
  .crumbs { font-size: 0.85rem; color: var(--ink-soft); margin: 0 0 6px; }
  .profile-head h1 { font-size: 1.6rem; }
  .profile-actions { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; margin: 0 0 18px; }
  .button { display: inline-block; padding: 7px 16px; border-radius: 999px; background: var(--mark); color: var(--surface);
    font-weight: 600; text-decoration: none; }
  .button:hover, .button:focus-visible { color: var(--surface); filter: brightness(1.1); }
  .score-lines { padding-left: 1.2rem; }
  .table-scroll { overflow-x: auto; }
  .asof { margin-top: 28px; }
  .member-list { columns: 18rem; padding-left: 1.2rem; }
  .jump-list { line-height: 1.9; }
  .state-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr)); gap: 6px; margin: 0; padding: 0; list-style: none; }
  .state-grid a { display: block; padding: 8px 12px; background: var(--surface); border: 1px solid var(--rule); border-radius: 8px; text-decoration: none; }
  .state-grid a:hover, .state-grid a:focus-visible { border-color: var(--mark); color: var(--mark); }
  .state-grid small { color: var(--ink-soft); margin-left: 4px; }
  /* On phones, each table row becomes a small card with its labels. */
  @media (max-width: 640px) {
    .stack thead { display: none; }
    .stack tr { display: block; padding: 10px 0; border-bottom: 1px solid var(--rule); }
    .stack td { display: block; border: 0; padding: 2px 0; }
    .stack td.lead { font-weight: 600; }
    .stack td.lead .meta { font-weight: 400; }
    .stack td[data-label]::before { content: attr(data-label) ": "; color: var(--ink-soft); }
    .stack td.verdict::before { content: "Compared: "; color: var(--ink-soft); font-weight: 400; }
    html[data-party-blind] .stack td.party { display: none; }
  }
</style>"""


# ------------------------------------------------------------------------------------- images

def _font(weight: str, size: int):
    from PIL import ImageFont
    return ImageFont.truetype(str(FONTS / f"PublicSans-{weight}.ttf"), size)


def _wrap(draw, text: str, font, width: int, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=font) <= width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,;") + "…"
    return lines


def preview_image(path: Path, title: str, subtitle: str, lines: list[tuple[str, str]], footer: str) -> None:
    """A 1200x630 link-preview card. lines: (big figure, words) pairs, e.g. ("12 of 15", "...")."""
    from PIL import Image, ImageDraw
    W, H, pad = 1200, 630, 72
    ink, soft, mark, page = (29, 39, 51), (85, 97, 110), (47, 111, 102), (233, 238, 241)
    img = Image.new("RGB", (W, H), page)
    d = ImageDraw.Draw(img)
    card = (40, 40, W - 40, H - 96)
    d.rounded_rectangle(card, radius=28, fill=(255, 255, 255))
    d.rounded_rectangle((card[0], card[1], card[0] + 12, card[3]), radius=6, fill=mark)

    # Lay the text out first, then centre it in the card below the brand line.
    ops, y = [], 0
    tf = _font("Bold", 66 if len(title) <= 26 else 54)
    for ln in _wrap(d, title, tf, W - 2 * pad, 2):
        ops.append(("t", pad, y, ln, tf, ink)); y += int(tf.size * 1.18)
    sf = _font("Regular", 34)
    for ln in _wrap(d, subtitle, sf, W - 2 * pad, 2):
        ops.append(("t", pad, y, ln, sf, soft)); y += 44
    y += 26
    big, small = _font("Bold", 50), _font("Regular", 30)
    for fig, words in lines[:3]:
        fx = pad
        if fig:
            ops.append(("t", pad, y, fig, big, mark))
            fx = pad + int(d.textlength(fig, font=big)) + 20
        wl = _wrap(d, words, small, W - pad - fx, 2)
        top = y + (14 if len(wl) == 1 else 0)
        for k, ln in enumerate(wl):
            ops.append(("t", fx, top + 36 * k, ln, small, ink))
        y += 76 if len(wl) == 1 else 84
    brand_h = 70
    room = card[3] - card[1] - brand_h - 30
    y0 = card[1] + brand_h + max(0, (room - y) // 2)
    brand, vs = _font("Bold", 30), _font("SemiBold", 30)
    bx, by = pad, card[1] + 30
    d.text((bx, by), "US Congress ", font=brand, fill=ink)
    bx += d.textlength("US Congress ", font=brand)
    d.text((bx, by), "vs ", font=vs, fill=mark)
    bx += d.textlength("vs ", font=vs)
    d.text((bx, by), "Voters", font=brand, fill=ink)
    for _, x, yy, text, font, fill in ops:
        d.text((x, y0 + yy), text, font=font, fill=fill)
    d.text((pad - 24, H - 72), footer, font=_font("SemiBold", 27), fill=soft)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.quantize(colors=64).save(path, optimize=True)


def have_pillow() -> bool:
    try:
        import PIL  # noqa: F401
        return (FONTS / "PublicSans-Bold.ttf").exists()
    except ImportError:
        return False


FOOTER = "uscongressvsvoters.org · independent · no ads, no tracking"


def member_image(path: Path, m: dict, opinion: dict | None) -> None:
    role = seat_words(m) if m.get("serving", True) else "Former " + seat_words(m)[0].lower() + seat_words(m)[1:]
    lines = []
    for s in (opinion or {}).get("by_source") or []:
        if s.get("clear_majority"):
            lines.append((f"{s['with_majority']} of {s['clear_majority']}",
                          f"surveyed votes with a clear majority went the way most constituents wanted · {s['organization']}"))
    if not lines:
        lines = [("", "Voting record, attendance, and how votes compared with what constituents told surveys")]
    preview_image(path, m["name"], role, lines, FOOTER)


def state_image(path: Path, st: dict) -> None:
    name = st.get("name") or STATE_NAMES.get(st["state"], st["state"])
    n = len(st["members"])
    lines = [(str(n), f"members of Congress serving {name} now"),
             (str(len(st.get("opinion") or [])), "survey questions and ballot measures asked of residents")]
    preview_image(path, name, "Members of Congress vs. what residents told surveys", lines, FOOTER)


def site_image(path: Path) -> None:
    preview_image(path, "How did your members of Congress vote?",
                  "And how did that compare with what the people they represent told independent surveys?",
                  [("", "Every House and Senate member, from the official vote records and published survey data")], FOOTER)


# ------------------------------------------------------------------------------------- build

def build(out: Path, get, version: str, today: date | None = None, images: bool | None = None,
          workers: int = 8, log=print) -> dict:
    today = today or date.today()
    images = have_pillow() if images is None else images
    frame = (build_site.SITE / "frame.html").read_text(encoding="utf-8")
    settings = build_site.load_settings()
    site_url = str(settings.get("site_url", "")).rstrip("/")

    def write(url_path: str, meta: dict, body: str, image: str | None = None, nav: str = "") -> None:
        meta = {**meta, "head": PAGE_CSS}
        page = build_site.wrap(frame, settings, meta, body, nav, version, slug="profile",
                               url_path=url_path, image=image, base=True)
        target = out / url_path / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page, encoding="utf-8")

    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        states = [s for s in pool.map(lambda c: get(f"/v1/states/{c}"), STATE_NAMES) if s]
    everyone = [m for st in states for m in st["members"]] + [m for st in states for m in st["former"]]
    seen, unique = set(), []
    for m in everyone:
        if m["bioguide_id"] not in seen:
            seen.add(m["bioguide_id"])
            unique.append(m)
    slugs = assign_slugs(unique)
    log(f"{len(states)} states, {len(unique)} members")

    def one(m):
        mid = m["bioguide_id"]
        detail = get(f"/v1/members/{mid}")
        if not detail:
            return None
        opinion = get(f"/v1/members/{mid}/opinion")
        votes = (get(f"/v1/members/{mid}/votes?limit=15") or {}).get("votes", [])
        return detail, opinion, votes

    paths = []
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        for m, got in zip(unique, pool.map(one, unique)):
            if not got:
                continue
            detail, opinion, votes = got
            slug = slugs[m["bioguide_id"]]
            img = None
            if images:
                member_image(out / "members" / slug / "preview.png", detail, opinion)
                img = f"members/{slug}/preview.png"
            meta, body = member_page(detail, opinion, votes, slugs, today)
            write(f"members/{slug}/", meta, body, img)
            paths.append(f"members/{slug}/")
    for st in states:
        slug = state_slug(st["state"])
        img = None
        if images:
            state_image(out / "states" / slug / "preview.png", st)
            img = f"states/{slug}/preview.png"
        meta, body = state_page(st, slugs, today)
        write(f"states/{slug}/", meta, body, img)
        paths.append(f"states/{slug}/")
    write("members/", *members_index(states, slugs))
    write("states/", *states_index(states), nav="state.html")
    (out / "members" / "slugs.json").write_text(json.dumps(slugs, sort_keys=True), encoding="utf-8")

    top = sorted(p.name for p in out.glob("*.html") if p.name not in ("search.html",))
    top = ["" if n == "index.html" else n for n in top]
    (out / "sitemap.xml").write_text(sitemap(site_url, sorted(top) + ["members/", "states/"] + sorted(paths), today),
                                     encoding="utf-8")
    log(f"Wrote {len(paths)} member and state pages{' with preview images' if images else ''}, and sitemap.xml")
    return {"members": len(paths) - len(states), "states": len(states), "slugs": slugs}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "build" / "site"))
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--version", default="dev")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--site-image", metavar="PNG", help="only draw the site-wide preview image to this file")
    args = ap.parse_args()
    if args.site_image:
        site_image(Path(args.site_image))
        return
    build(Path(args.out), http_getter(args.api), args.version, images=False if args.no_images else None)


if __name__ == "__main__":
    main()
