/*
 * <cc-member-panel member="B001277" api-base="/api"></cc-member-panel>
 *
 * Shows one member of Congress: who they are, how often they miss votes, how
 * often they vote with their party's majority, and their recent votes.
 * Self-contained: drop the script on any page and add the tag.
 *
 * Attributes
 *   member     Bioguide ID (required), e.g. B001277
 *   api-base   where the API lives; default "/api" (same site)
 *   votes      how many recent votes to list; default 10 (max 100)
 *   site-base  where the site's reference pages are (Sources, Methods, Glossary); default: the folder
 *              this script was loaded from, so an embed elsewhere still links to them
 *
 * Events
 *   cc-member-loaded  fired once a member's record has loaded; event.detail is the member summary
 *
 * Design notes
 *   - No party colours. Votes are told apart by shape (filled / ring / dash),
 *     so the panel reads the same to everyone and to colour-blind readers.
 *   - Typeface: Public Sans, the U.S. Web Design System's open typeface,
 *     falling back to the system UI font if it can't load.
 */
(() => {
  const FONT_HREF = "https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700&display=swap";
  if (!document.querySelector(`link[href="${FONT_HREF}"]`)) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = FONT_HREF;
    document.head.appendChild(link);
  }

  // Where the reference pages live, unless the page says otherwise (site-base attribute).
  const SCRIPT_BASE = (() => { try { return new URL(".", document.currentScript.src).href; } catch { return ""; } })();

  const STRIP_SIZE = 100; // votes fetched for the strip; narrow screens show the newest that fit

  const css = `
    :host {
      --ink: #1d2733;
      --ink-soft: #55616e;
      --rule: #d7dde3;
      --surface: #ffffff;
      --surface-sunk: #f2f5f7;
      --mark: #2f6f66;          /* verdigris, the panel's one accent */
      --mark-soft: #cfe3de;
      --against: #b45309;      /* amber: vote went against a clear majority */
      --against-soft: #f6dfc6;
      --unclear-soft: #e3e8ec; /* grey: too close to call */
      display: block;          /* fills the width the host page gives it */
      font-family: "Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
      font-size: 15px;
      line-height: 1.5;
      color: var(--ink);
    }
    @media (prefers-color-scheme: dark) {
      :host {
        --ink: #e6ebef;
        --ink-soft: #a3afba;
        --rule: #34404b;
        --surface: #182028;
        --surface-sunk: #1f2932;
        --mark: #7cc2b5;
        --mark-soft: #2c4d48;
        --against: #e8a35c;
        --against-soft: #4d3622;
        --unclear-soft: #2c363f;
      }
    }
    * { box-sizing: border-box; }
    .panel {
      background: var(--surface);
      border: 1px solid var(--rule);
      border-radius: 10px;
      padding: 20px 20px 16px;
    }
    h2 {
      font-size: 1.6rem;
      line-height: 1.15;
      font-weight: 700;
      letter-spacing: -0.01em;
      margin: 0 0 4px;
    }
    .seat { color: var(--ink-soft); margin: 0 0 18px; }

    /* The vote strip: the panel's signature. Oldest at left, newest at right. */
    .strip-wrap { margin: 0 0 6px; }
    /* Right-aligned: when space runs out the oldest marks (left) are the ones hidden. */
    .strip { display: flex; gap: 3px; flex-wrap: nowrap; overflow: hidden; height: 18px;
             align-items: center; justify-content: flex-end; }
    .strip svg { flex: 0 0 auto; }
    .dot { all: unset; flex: 0 0 auto; display: inline-flex; cursor: pointer; padding: 2px 0; border-radius: 3px; }
    .dot:hover svg { transform: scale(1.35); }
    @media (prefers-reduced-motion: no-preference) { .dot svg { transition: transform 0.1s; } }
    ol.votes li.found, .op-list li.found { background: var(--mark-soft); border-radius: 6px; }
    .jumps { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: -8px 0 18px;
             font-size: 0.85rem; color: var(--ink-soft); }
    .jumps button {
      font: inherit; color: var(--ink); background: var(--surface-sunk); cursor: pointer;
      border: 1px solid var(--rule); border-radius: 999px; padding: 2px 12px;
    }
    .jumps button:hover { border-color: var(--mark); }
    h3[tabindex]:focus, .op-sources:focus { outline: none; }
    .op-sources:focus-visible { outline: 2px solid var(--mark); outline-offset: 4px; border-radius: 3px; }
    .op-sources { scroll-margin-top: 12px; }
    h3[tabindex]:focus-visible { outline: 2px solid var(--mark); outline-offset: 4px; }
    h3 { scroll-margin-top: 12px; }
    .intro + .intro { margin-top: 0; }
    .intro { margin: -4px 0 10px; font-size: 0.85rem; color: var(--ink-soft); }
    /* Longer explanations fold away (closed by default), like a "details" block on a wiki page. */
    details.more { margin: -6px 0 10px; font-size: 0.85rem; color: var(--ink-soft); }
    details.more > summary { cursor: pointer; width: fit-content; color: var(--ink); list-style: none;
                             text-decoration: underline; text-decoration-color: var(--mark);
                             text-underline-offset: 2px; padding: 2px 0; }
    details.more > summary::-webkit-details-marker { display: none; }
    details.more > summary::before { content: "\\25B8"; display: inline-block; width: 1.1em; color: var(--mark);
                                     text-decoration: none; transition: transform 0.15s; }
    details.more[open] > summary::before { transform: rotate(90deg); }
    details.more > p { margin: 6px 0 0; }
    @media (prefers-reduced-motion: reduce) { details.more > summary::before { transition: none; } }
    .op-tag {
      grid-column: 2; justify-self: start; margin-top: 4px; font: inherit; font-size: 0.8rem; color: var(--ink);
      background: var(--surface-sunk); border: 1px solid var(--rule); border-radius: 999px; padding: 1px 10px; cursor: pointer;
    }
    .op-tag:hover { border-color: var(--mark); }
    @media (prefers-reduced-motion: no-preference) {
      ol.votes li.found, .op-list li.found { animation: found 2.4s ease-out forwards; }
      @keyframes found { 0%, 60% { background: var(--mark-soft); } 100% { background: transparent; } }
    }
    .legend {
      display: flex; gap: 14px; flex-wrap: wrap;
      font-size: 0.8rem; color: var(--ink-soft); margin: 6px 0 18px;
    }
    .legend span { display: inline-flex; align-items: center; gap: 5px; }

    .facts { margin: 0 0 18px; padding: 0; list-style: none; }
    .facts li { padding: 8px 0; border-top: 1px solid var(--rule); }
    .facts li:last-child { border-bottom: 1px solid var(--rule); }
    .facts li.folded { padding: 6px 0; }
    .facts li.folded .facts { margin: 6px 0 0; }
    .facts li.folded .facts li:last-child { border-bottom: 0; }
    .facts strong { font-variant-numeric: tabular-nums; font-weight: 700; }

    h3 { font-size: 0.95rem; font-weight: 600; margin: 0 0 8px; }
    ol.votes { list-style: none; margin: 0; padding: 0; }
    ol.votes li {
      display: grid;
      grid-template-columns: 18px 1fr;
      gap: 2px 10px;
      padding: 10px 0;
      border-top: 1px solid var(--rule);
    }
    ol.votes li svg { grid-row: 1 / span 2; margin-top: 3px; }
    .what { font-weight: 600; }
    .what a { color: inherit; text-decoration-color: var(--mark); text-underline-offset: 2px; }
    .detail { grid-column: 2; color: var(--ink-soft); font-size: 0.85rem; }
    .detail a { color: var(--ink-soft); white-space: nowrap; }
    .caption { font-size: 0.8rem; color: var(--ink-soft); margin: 0 0 4px; }
    .their { color: var(--ink); font-weight: 600; }

    button.more {
      margin-top: 10px; font: inherit; font-size: 0.9rem;
      background: var(--surface-sunk); color: var(--ink);
      border: 1px solid var(--rule); border-radius: 6px; padding: 6px 12px; cursor: pointer;
    }
    button.more:hover { border-color: var(--mark); }
    a:focus-visible, button:focus-visible { outline: 2px solid var(--mark); outline-offset: 2px; border-radius: 3px; }

    .source { margin: 16px 0 0; font-size: 0.8rem; color: var(--ink-soft); }

    .opinion { margin: 0 0 22px; }
    .op-lead { margin: 0 0 6px; }
    .op-lead strong { font-variant-numeric: tabular-nums; }
    .op-scale { display: grid; grid-template-columns: 1fr auto 1fr; font-size: 0.75rem;
                color: var(--ink-soft); margin: 10px 0 2px; padding: 0 2px; }
    .op-scale span:nth-child(2) { text-align: center; }
    .op-scale span:last-child { text-align: right; }
    .op-list { list-style: none; margin: 0; padding: 0; }
    .op-congress { font-size: 0.95rem; margin: 14px 0 4px; }
    .op-congress span, .op-tally { font-weight: 400; color: var(--ink-soft); font-size: 0.88rem; }
    .op-tally { display: inline-block; text-decoration: none; }
    .op-groups > details { border-top: 1px solid var(--rule); padding: 8px 0; }
    .op-groups > details > summary { font-weight: 600; font-size: 0.95rem; }
    .op-sample p { margin: 0 0 4px; }
    .op-sample-list { margin: 4px 0 0; padding-left: 1.2em; }
    .op-list li { padding: 10px 0; border-top: 1px solid var(--rule); }
    .op-q { margin: 0 0 6px; font-weight: 600; }
    .people { margin: -14px 0 18px; color: var(--ink-soft); font-size: 0.9rem; }
    .people-src { font-size: 0.8rem; }
    .history { margin: -14px 0 18px; color: var(--ink-soft); font-size: 0.9rem; }
    .history .spell { white-space: nowrap; }
    .op-sample { margin: 2px 0 0; font-size: 0.85rem; color: var(--ink-soft); }
    .op-sample strong { color: var(--ink); font-variant-numeric: tabular-nums; }
    .op-key { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 0.8rem; color: var(--ink-soft); margin: 8px 0 0; }
    .op-key span { display: inline-flex; align-items: center; gap: 6px; }
    .op-key .sw { display: inline-block; width: 18px; height: 8px; border-radius: 2px; }
    .op-key .sw.with { background: var(--mark-soft); box-shadow: inset 0 0 0 1px var(--mark); }
    .op-key .sw.against { background: var(--against-soft); box-shadow: inset 0 0 0 1px var(--against); }
    .op-key .sw.unclear { background: var(--unclear-soft); box-shadow: inset 0 0 0 1px var(--ink-soft); }
    .op-barwrap { position: relative; margin: 0 9px 4px; }   /* side room so end markers aren't clipped */
    .op-bar { display: block; width: 100%; height: 12px; }
    .op-pin { position: absolute; top: 50%; display: inline-flex; padding: 1px; border-radius: 50%;
              background: var(--surface); transform: translate(-50%, -50%); }
    .op-pin.support { left: 100%; }   /* at the end of the scale the vote supported */
    .op-pin.oppose { left: 0; }
    .op-related { display: inline-block; margin-left: 6px; padding: 0 6px; border: 1px solid var(--rule);
                  border-radius: 999px; font-size: 0.75rem; color: var(--ink-soft); white-space: nowrap; }
    .op-leads { margin: 0 0 6px; }
    .op-leads .op-lead { margin: 0 0 2px; }
    .op-est { margin: 0; font-size: 0.85rem; color: var(--ink-soft); font-variant-numeric: tabular-nums; }
    .op-vote { margin: 2px 0 0; font-size: 0.9rem; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
    .op-vote svg { align-self: center; }
    .op-vote a { color: var(--ink-soft); white-space: nowrap; font-size: 0.85rem; }
    .op-note { margin: 4px 0 0; font-size: 0.8rem; color: var(--ink-soft); }
    .op-source { margin: 12px 0 0; font-size: 0.8rem; color: var(--ink-soft); }
    .op-source strong { color: var(--ink); font-weight: 600; }
    .op-source a, .op-note a { color: var(--ink-soft); }
    .note { color: var(--ink-soft); }
    .error { color: var(--ink); background: var(--surface-sunk); border-radius: 6px; padding: 10px 12px; }
    .loading { color: var(--ink-soft); }
    .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  `;

  const POSITION_TEXT = { yea: "Yea", nay: "Nay", present: "Present", not_voting: "Did not vote", other: "Other" };

  // Shape per position: filled dot, ring, square for present, dash for not voting.
  function mark(position, size = 12) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("width", size);
    svg.setAttribute("height", size);
    svg.setAttribute("viewBox", "0 0 12 12");
    svg.setAttribute("aria-hidden", "true");
    let el;
    if (position === "yea") {
      el = document.createElementNS(ns, "circle");
      el.setAttribute("cx", 6); el.setAttribute("cy", 6); el.setAttribute("r", 5);
      el.setAttribute("fill", "var(--mark)");
    } else if (position === "nay") {
      el = document.createElementNS(ns, "circle");
      el.setAttribute("cx", 6); el.setAttribute("cy", 6); el.setAttribute("r", 4.25);
      el.setAttribute("fill", "none"); el.setAttribute("stroke", "var(--mark)"); el.setAttribute("stroke-width", 1.5);
    } else if (position === "present") {
      el = document.createElementNS(ns, "rect");
      el.setAttribute("x", 2); el.setAttribute("y", 2); el.setAttribute("width", 8); el.setAttribute("height", 8);
      el.setAttribute("fill", "var(--mark-soft)"); el.setAttribute("stroke", "var(--mark)");
    } else {
      el = document.createElementNS(ns, "rect");
      el.setAttribute("x", 2); el.setAttribute("y", 5); el.setAttribute("width", 8); el.setAttribute("height", 2);
      el.setAttribute("fill", "var(--ink-soft)");
    }
    svg.appendChild(el);
    return svg;
  }

  // Small DOM helper: h("p", {class: "x"}, "text", childNode, ...)
  function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      el.append(c instanceof Node ? c : String(c));
    }
    return el;
  }

  // "Sep 15, 2026 · H.Con.Res. 93: Directing the President… · Voted Nay"
  function voteSummary(v) {
    const title = v.description || v.question || "Recorded vote";
    const short = title.length > 90 ? title.slice(0, 88).trimEnd() + "…" : title;
    const what = v.bill ? `${v.bill.label}: ${short}` : short;
    const how = v.position === "not_voting" ? "Did not vote" : `Voted ${POSITION_TEXT[v.position] || v.position_detail}`;
    return `${fmtDate(v.date)} · ${what} · ${how}`;
  }

  const STATE_NAMES = { AL:"Alabama",AK:"Alaska",AZ:"Arizona",AR:"Arkansas",CA:"California",CO:"Colorado",
    CT:"Connecticut",DE:"Delaware",FL:"Florida",GA:"Georgia",HI:"Hawaii",ID:"Idaho",IL:"Illinois",IN:"Indiana",
    IA:"Iowa",KS:"Kansas",KY:"Kentucky",LA:"Louisiana",ME:"Maine",MD:"Maryland",MA:"Massachusetts",MI:"Michigan",
    MN:"Minnesota",MS:"Mississippi",MO:"Missouri",MT:"Montana",NE:"Nebraska",NV:"Nevada",NH:"New Hampshire",
    NJ:"New Jersey",NM:"New Mexico",NY:"New York",NC:"North Carolina",ND:"North Dakota",OH:"Ohio",OK:"Oklahoma",
    OR:"Oregon",PA:"Pennsylvania",RI:"Rhode Island",SC:"South Carolina",SD:"South Dakota",TN:"Tennessee",TX:"Texas",
    UT:"Utah",VT:"Vermont",VA:"Virginia",WA:"Washington",WV:"West Virginia",WI:"Wisconsin",WY:"Wyoming",
    DC:"the District of Columbia",PR:"Puerto Rico" };
  const stateName = code => STATE_NAMES[code] || code;

  function people(n) {
    if (n == null) return "";
    if (n >= 1e6) return `${(n / 1e6).toFixed(1).replace(/\.0$/, "")} million`;
    return (Math.round(n / 1000) * 1000).toLocaleString();
  }

  const fmtDate = (iso, opts = { month: "short", day: "numeric", year: "numeric" }) =>
    new Date(iso + "T12:00:00").toLocaleDateString("en-US", opts);

  function seatSentence(m) {
    const role = m.chamber === "senate" ? "Senator for" : "Representative for";
    const where = m.chamber === "senate" ? m.state : m.seat;
    const party = m.caucus && m.caucus !== m.party ? `${m.party}, caucuses with the ${m.caucus}s` : m.party;
    // Former members: say so plainly, with when they left. No reason is given (retired, defeated,
    // resigned...) because the member data doesn't reliably include one.
    if (!m.serving) {
      const until = m.left_office ? `; served until ${fmtDate(m.left_office)}` : "";
      return `Former ${role.toLowerCase()} ${where}, ${party}${until}`;
    }
    return `${role} ${where}, ${party}`;
  }

  const SOURCE_TEXT = {
    house_clerk: "the Clerk of the House",
    senate_lis: "the Senate",
    voteview: "Voteview (UCLA), which republishes Senate votes after a delay",
  };

  class MemberPanel extends HTMLElement {
    static get observedAttributes() { return ["member", "api-base", "votes"]; }

    constructor() {
      super();
      this.root = this.attachShadow({ mode: "open" });
      this.root.append(h("style", {}, css));
      this.body = h("div", { class: "panel", part: "panel" });
      this.root.append(this.body);
      this.showing = 0;
      this.request = 0;
    }

    connectedCallback() { this.load(); }
    attributeChangedCallback(_name, oldV, newV) { if (this.isConnected && oldV !== newV) this.load(); }

    get apiBase() { return (this.getAttribute("api-base") || "/api").replace(/\/$/, ""); }
    get listSize() { return Math.min(100, Math.max(1, parseInt(this.getAttribute("votes") || "10", 10) || 10)); }

    async get(path) {
      const res = await fetch(this.apiBase + path, { headers: { Accept: "application/json" } });
      if (!res.ok) {
        let detail = "";
        try { detail = (await res.json()).detail || ""; } catch { /* not JSON */ }
        throw new Error(detail || `The server answered ${res.status}`);
      }
      return res.json();
    }

    async load() {
      const id = (this.getAttribute("member") || "").trim().toUpperCase();
      const ticket = ++this.request;
      this.body.replaceChildren(h("p", { class: "loading", role: "status" }, "Loading voting record…"));
      if (!id) {
        this.body.replaceChildren(h("p", { class: "error" }, "Choose a member of Congress to see their voting record."));
        return;
      }
      try {
        const [member, votes, opinion] = await Promise.all([
          this.get(`/v1/members/${encodeURIComponent(id)}`),
          this.get(`/v1/members/${encodeURIComponent(id)}/votes?limit=${STRIP_SIZE}`),
          // Optional: if this part fails, show the rest of the panel without it.
          this.get(`/v1/members/${encodeURIComponent(id)}/opinion`).catch(() => null),
        ]);
        if (ticket !== this.request) return; // a newer member was chosen meanwhile
        this.member = member;
        this.votes = votes.votes;
        this.opinion = opinion;
        this.showing = Math.min(this.listSize, this.votes.length);
        this.render();
        // Lets the host page react (e.g. remember recently viewed members); detail = the member summary.
        this.dispatchEvent(new CustomEvent("cc-member-loaded", { detail: member, bubbles: true }));
      } catch (err) {
        if (ticket !== this.request) return;
        this.body.replaceChildren(h("p", { class: "error", role: "alert" },
          `Couldn't load this voting record: ${err.message}. Reload the page to try again.`));
      }
    }

    // A folded explanation. Its open/closed state survives re-renders (e.g. "Show more votes").
    // "Seats held: Senator for OH, 2025–now · Representative for OH-3, 2023–2025 · ...", from the
    // member list (whole career), with a note when the votes loaded here start later than that.
    historyLine(m) {
      const seats = m.seats || [];
      if (seats.length < 2 && !(seats.length === 1 && seats[0].first_congress < seats[0].last_congress)) return null;
      const year = d => d.slice(0, 4);
      const parties = new Set(seats.map(x => x.party));
      const spells = seats.map((x, i) => h("span", { class: "spell" },
        `${x.chamber === "senate" ? "Senator for" : "Representative for"} ${x.seat.replace("-", "\u2011")}`,
        parties.size > 1 ? ` (${x.party})` : "",
        `, ${year(x.start)}\u2013${x.end ? year(x.end) : "now"}`, i < seats.length - 1 ? " · " : ""));
      const loaded = (m.service || []).map(p => p.congress);
      const earliest = Math.min(...seats.map(x => x.first_congress));
      const note = loaded.length && earliest < Math.min(...loaded)
        ? ` Votes on this site start with the ${ordinal(Math.min(...loaded))} Congress.` : "";
      return h("p", { class: "history" }, h("strong", {}, "Seats held: "), spells, ".", note);
    }

    foldable(key, summary, ...body) {
      return this.foldableOpen(key, false, summary, ...body);
    }

    // Like foldable, but starts open unless the reader has closed it.
    foldableOpen(key, startOpen, summary, ...body) {
      this.folds = this.folds || {};
      const open = key in this.folds ? this.folds[key] : startOpen;
      const d = h("details", { class: "more", open }, h("summary", {}, summary), ...body);
      d.addEventListener("toggle", () => { this.folds[key] = d.open; });
      return d;
    }

    render() {
      const m = this.member, s = m.stats, votes = this.votes;
      const parts = [
        h("h2", {}, m.name),
        h("p", { class: "seat" }, seatSentence(m)),
      ];
      const history = this.historyLine(m);
      if (history) parts.push(history);
      const pop = m.population;
      if (pop) {
        const where = pop.area.replace("-", "\u2011");
        const year = (pop.source.match(/\d{4}/) || [""])[0];
        parts.push(h("p", { class: "people" },
          // Former members: the state's figure is today's; a district's is for the lines of their last term.
          m.chamber === "senate"
            ? `${stateName(pop.area)} has about ${people(pop.residents)} residents${m.serving ? "" : " today"}, represented by two senators.`
            : m.serving ? `${where} has about ${people(pop.residents)} residents.`
                        : `${where}, as drawn for their last term, had about ${people(pop.residents)} residents.`,
          m.chamber === "senate" && pop.smallest_state && pop.largest_state
            ? ` States range from about ${people(pop.smallest_state.residents)} (${stateName(pop.smallest_state.state)}) to ${people(pop.largest_state.residents)} (${stateName(pop.largest_state.state)}) residents, each with two senators.`
            : pop.average_district ? ` The average House district has about ${people(pop.average_district)}.` : "",
          h("span", { class: "people-src" }, ` Census Bureau estimate${year ? `, ${year}` : ""}.`)));
      }
      const jumps = [];
      if (this.opinion?.items?.length) {
        jumps.push(["compared", "Compared with constituents"]);
        if (this.opinion.surveys?.length) jumps.push(["sources", this.opinion.surveys.length > 1 ? "Survey sources" : "Survey source"]);
      }
      if (votes.length) jumps.push(["recent", "Recent votes"]);
      if (jumps.length) {
        // Buttons, not #links: the host page may use the address's # part (the dev page stores the member there).
        parts.push(h("nav", { class: "jumps", "aria-label": "Sections" }, h("span", {}, "Go to:"),
          jumps.map(([id, label]) => {
            const b = h("button", { type: "button" }, label);
            b.addEventListener("click", () => this.goToSection(id));
            return b;
          })));
      }

      if (votes.length) {
        // Strip: oldest on the left so it reads like a timeline.
        const ordered = [...votes].reverse();
        const counts = ordered.reduce((a, v) => (a[v.position] = (a[v.position] || 0) + 1, a), {});
        const summary = Object.entries(counts).map(([p, n]) => `${n} ${POSITION_TEXT[p] || p}`).join(", ");
        parts.push(
          h("div", { class: "strip-wrap" },
            h("p", { class: "caption", "aria-hidden": "true" }, "Recent votes, newest at the right"),
            h("p", { class: "sr" }, `Last ${ordered.length} votes, oldest first: ${summary}.`),
            // Mouse and touch shortcut into the list below; the list itself is the accessible version.
            h("div", { class: "strip", "aria-hidden": "true" }, ordered.map(v => {
              const btn = h("button", { type: "button", class: "dot", tabindex: "-1", title: voteSummary(v) }, mark(v.position));
              btn.addEventListener("click", () => this.jumpTo(v.roll_call_id));
              return btn;
            }))),
          h("div", { class: "legend", "aria-hidden": "true" },
            ["yea", "nay", "present", "not_voting"].map(p => h("span", {}, mark(p, 10), POSITION_TEXT[p]))),
        );
      }

      const facts = [];
      const periods = (m.service || []).filter(p => p.votes_total);
      if (periods.length > 1) {
        // Served in more than one Congress or chamber: one line for each, newest first. A long
        // career keeps the latest two in view and folds the rest.
        const line = p => h("li", {},
            h("strong", {}, `${p.chamber === "senate" ? "Senate" : "House"}${p.seat ? ` (${p.seat})` : ""}, ${ordinal(p.congress)} Congress`),
            `: missed ${p.missed_pct}% of ${p.votes_total.toLocaleString()} ${p.votes_total === 1 ? "vote" : "votes"}`,
            p.party_votes ? `; voted with their party's majority on ${p.with_party_pct}% of ${p.party_votes.toLocaleString()}` : "",
            p.first_vote && p.last_vote ? ` (${fmtDate(p.first_vote)} to ${fmtDate(p.last_vote)})` : "", ".");
        const shown = periods.length > 3 ? periods.slice(0, 2) : periods;
        facts.push(...shown.map(line));
        if (shown.length < periods.length) {
          const rest = periods.slice(shown.length);
          facts.push(h("li", { class: "folded" }, this.foldable("earlier-congresses",
            `Earlier Congresses (${rest.length}, back to the ${ordinal(rest.at(-1).congress)})`,
            h("ul", { class: "facts" }, rest.map(line)))));
        }
      } else if (s.votes_total) {
        facts.push(h("li", {}, "Missed ", h("strong", {}, `${s.missed_pct}%`),
          ` of ${s.votes_total.toLocaleString()} votes in the ${ordinal(s.congress)} Congress`,
          s.first_vote && s.last_vote
            ? ` (${fmtDate(s.first_vote)} to ${fmtDate(s.last_vote)})` : "",
          "."));
      }
      if (periods.length <= 1 && s.party_votes) {
        facts.push(h("li", {}, "Voted with the majority of their party on ",
          h("strong", {}, `${s.with_party_pct}%`), ` of ${s.party_votes.toLocaleString()} votes.`));
      }
      if (facts.length) parts.push(h("ul", { class: "facts" }, facts));
      else parts.push(h("p", { class: "note" }, `No recorded votes yet in the ${ordinal(s.congress)} Congress.`));

      const opinionSection = this.opinionSection();
      if (opinionSection) parts.push(opinionSection);

      if (votes.length) {
        parts.push(h("h3", { id: "recent", tabindex: "-1" }, "Recent votes"));
        parts.push(h("p", { class: "intro" },
          "Every recorded floor vote, newest first: what the member did, and the result. ",
          this.opinion?.items?.length
            ? "Votes marked \u201cSurveyed\u201d also appear in the comparison above; on the rest, constituents weren\u2019t asked."
            : "Constituents\u2019 views aren\u2019t available for these votes."));
        parts.push(h("ol", { class: "votes" }, votes.slice(0, this.showing).map(v => this.voteRow(v))));
        if (this.showing < votes.length) {
          const btn = h("button", { class: "more", type: "button" }, "Show more votes");
          btn.addEventListener("click", () => {
            this.showing = Math.min(votes.length, this.showing + this.listSize);
            this.render();
            this.root.querySelector("button.more, ol.votes li:last-child a")?.focus();
          });
          parts.push(btn);
        }
      }

      parts.push(this.sourceNote());
      this.body.replaceChildren(...parts);
    }

    goToSection(id) {
      const heading = this.root.getElementById(id);
      if (!heading) return;
      const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
      heading.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
      heading.focus({ preventScroll: true });
    }

    jumpTo(rollCallId) {
      const index = this.votes.findIndex(v => v.roll_call_id === rollCallId);
      if (index < 0) return;
      if (index >= this.showing) {               // open the list far enough to include it
        this.showing = Math.min(this.votes.length, Math.ceil((index + 1) / this.listSize) * this.listSize);
        this.render();
      }
      this.flash(this.root.querySelector(`li[data-roll="${CSS.escape(rollCallId)}"]`));
    }

    // Scroll a row into view and highlight it briefly.
    flash(row) {
      if (!row) return;
      // A comparison from an earlier Congress sits in a folded group: open it first.
      for (let d = row.closest("details"); d; d = d.parentElement && d.parentElement.closest("details")) d.open = true;
      const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
      row.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "center" });
      row.classList.remove("found");
      void row.offsetWidth;                      // restart the highlight if clicked twice
      row.classList.add("found");
      clearTimeout(this.foundTimer);
      this.foundTimer = setTimeout(() => row.classList.remove("found"), 2400);   // also ends it without animation
      row.querySelector("a")?.focus({ preventScroll: true });
    }

    voteRow(v) {
      const title = v.description || v.question || "Recorded vote";
      const what = v.bill
        ? h("span", { class: "what" }, h("a", { href: v.bill.url, target: "_blank", rel: "noopener" }, v.bill.label), `: ${title}`)
        : h("span", { class: "what" }, title);
      const tally = (v.yea_total != null && v.nay_total != null) ? `, ${v.yea_total}–${v.nay_total}` : "";
      return h("li", { "data-roll": v.roll_call_id },
        mark(v.position),
        what,
        h("span", { class: "detail" },
          h("span", { class: "their" }, `Voted ${POSITION_TEXT[v.position] === "Did not vote" ? "— did not vote" : POSITION_TEXT[v.position] || v.position_detail}`),
          v.position_detail && !["Yea", "Nay", "Present", "Not Voting"].includes(v.position_detail) ? ` (${v.position_detail})` : "",
          `. ${v.question ? v.question + ", " : ""}${(v.result || "").toLowerCase()}${tally}. `,
          h("a", { href: v.official_url, target: "_blank", rel: "noopener" }, fmtDate(v.date))),
        this.surveyedTag(v));
    }

    // "Surveyed: TX-6 62% support, with the district's majority" - jumps to the comparison.
    surveyedTag(v) {
      const item = (this.opinion?.items || []).find(i => i.vote.roll_call_id === v.roll_call_id);
      if (!item) return null;
      const where = item.constituents.area_label.replace("-", "\u2011");
      const whose = item.constituents.area === "state" ? "state's" : "district's";
      const related = item.match === "related";
      const tail = related ? ", related question (not counted)"
        : { with: `, with the ${whose} majority`, against: `, against the ${whose} majority`,
            too_close: ", too close to call" }[item.agreement] || "";
      const tag = h("button", { type: "button", class: "op-tag" }, item.kind === "ballot"
        ? `Ballot measure: ${where} voters ${Math.round(item.constituents.support_pct)}% yes${tail}`
        : `Surveyed: ${where} ${Math.round(item.constituents.support_pct)}% support${tail}`);
      tag.addEventListener("click", () => this.flash(this.root.querySelector(`li[data-op="${CSS.escape(v.roll_call_id)}"]`)));
      return tag;
    }

    opinionSection() {
      const o = this.opinion;
      if (!o || !o.items || !o.items.length) return null;
      const m = this.member;
      const nb = text => text.replace("-", "‑");           // keep "TX-6" on one line
      // Each comparison uses the seat the member held when the vote happened, so a
      // redrawn district or a move between chambers shows correctly.
      const areaOf = i => nb(i.constituents.area_label);
      const areas = [...new Set(o.items.map(areaOf))];
      const where = areas.length === 1 ? areas[0] : null;
      const whose = i => i.constituents.area === "state" ? "state's" : "district's";
      const verdictFor = i => i.match === "related" ? "related bill, not counted" : ({
        with: `with the ${whose(i)} majority`,
        against: `against the ${whose(i)} majority`,
        too_close: `${areaOf(i)} too close to call`,
        did_not_vote: "",
      })[i.agreement];

      const theirs = where ? `${where}'s` : "their constituents'";
      // One line per survey organization: sources are shown side by side, never combined into one score.
      const leadFor = (s, org) => {
        const by = org ? [h("strong", {}, org), ": "] : [];
        if (s.clear_majority)
          return h("p", { class: "op-lead" }, ...by, org ? "voted with " : "Voted with ",
            h("strong", {}, `${s.with_majority} of ${s.clear_majority}`),
            ` surveyed votes where ${theirs} estimated majority was clear.`);
        if (s.surveyed_votes)
          return h("p", { class: "op-lead" }, ...by, `${org ? "on" : "On"} these votes, ${theirs} estimated opinion was too close to call.`);
        return h("p", { class: "op-lead" }, ...by, `${org ? "only" : "Only"} related votes, which aren't counted.`);
      };
      const bySource = o.by_source || [];
      const lead = bySource.length > 1
        ? h("div", { class: "op-leads" }, bySource.map(b => leadFor(b, b.organization)))
        : leadFor(o.summary, null);

      const surveys = new Map((o.surveys || []).map(sv => [sv.name, sv]));
      const several = surveys.size > 1;
      const rows = [...o.items].reverse().map(i => {
        const c = i.constituents;
        const [lo, hi] = c.range_pct;
        const here = areaOf(i);
        const sv = surveys.get(i.survey);
        const voted = i.position === "yea" || i.position === "nay" ? `Voted ${POSITION_TEXT[i.position]}` : "Did not vote";
        const verdict = verdictFor(i);
        const related = i.match === "related";
        const ballot = i.kind === "ballot";
        // A ballot measure is a count of votes cast, so it has no likely range.
        const barText = ballot
          ? `${here}: ${Math.round(c.support_pct)}% of voters voted yes on ${c.area_note || "a state ballot measure"}. ${voted}${verdict ? ", " + verdict : ""}.`
          : `${here}: about ${Math.round(c.support_pct)}% support, likely between ${Math.round(lo)}% and ${Math.round(hi)}%. ${voted}${verdict ? ", " + verdict : ""}.`;
        const estimate = ballot
          ? h("p", { class: "op-est" },
              `${here} voters: ${Math.round(c.support_pct)}% yes on ${c.area_note || "a state ballot measure"}, `,
              `${c.respondents.toLocaleString()} votes cast (certified result).`)
          : h("p", { class: "op-est" },
            `${here}: ${Math.round(c.support_pct)}% support (likely ${Math.round(lo)}–${Math.round(hi)}%), `,
            `from ${c.respondents.toLocaleString()} ${c.respondents === 1 ? "person" : "people"} surveyed in ${here}`,
            c.respondents < 20 && c.area === "district" ? ", so this leans mostly on statewide answers" : "",
            several && sv ? ` (${sv.title})` : "",
            ".");
        const wording = !i.wording_url ? null : ballot
          ? h("p", { class: "op-note" }, h("a", { href: i.wording_url, target: "_blank", rel: "noopener" },
              "See the measure and its result"))
          : h("p", { class: "op-note" },
            h("a", { href: i.wording_url, target: "_blank", rel: "noopener",
                     title: i.wording_hint ? `Opens the ${sv?.title || "survey"} guide; search it for ${i.wording_hint}`
                                           : `Opens the questionnaire with ${here}'s results` },
              "See the exact question"),
            i.wording_hint ? ` (in the survey guide, search for ${i.wording_hint})` : ` (questionnaire with ${here}'s results, PDF)`);
        return h("li", { "data-op": i.vote.roll_call_id, "data-congress": i.vote.congress || 0, "data-agreement": related ? "related" : i.agreement },
          h("p", { class: "op-q" }, i.question,
            related ? h("span", { class: "op-related", title: "The vote was on a related bill, not exactly this proposal" },
              "Related vote") : null),
          this.rangeBar(c.support_pct, lo, hi, barText,
            i.sided_with, related ? "related" : i.agreement, i.position),
          estimate,
          h("p", { class: "op-vote" }, mark(i.position, 11),
            h("span", {}, h("strong", {}, voted), verdict ? `, ${verdict}` : "", ". "),
            h("a", { href: i.vote.official_url, target: "_blank", rel: "noopener" }, fmtDate(i.vote.date))),
          i.note ? h("p", { class: "op-note" }, i.note) : null,
          wording);
      });

      // One line: each survey organization (with the years used), linked to its section of the
      // site's Sources page, which has how each survey was done and links to questions and data.
      const base = this.getAttribute("site-base") || SCRIPT_BASE;
      const page = (file, anchor) => `${base}${file}${anchor ? `#${anchor}` : ""}`;
      const slug = t => t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
      const byOrg = new Map();
      for (const sv of surveys.values()) {
        const org = sv.organization || sv.title;
        const year = ((sv.name || "").match(/(\d{4})$/) || [])[1];
        byOrg.set(org, [...(byOrg.get(org) || []), year].filter(Boolean));
      }
      const orgLinks = [...byOrg].map(([org, years]) =>
        [h("a", { href: page("sources.html", slug(org)) }, org), years.length ? ` (${years.sort().join(", ")})` : ""]);
      const sourceLines = orgLinks.length ? [h("p", { class: "op-source" },
        h("strong", {}, orgLinks.length > 1 ? "Sources: " : "Source: "),
        orgLinks.flatMap((x, j) => j ? ["; ", ...x] : x), ". ",
        h("a", { href: page("sources.html", "surveys") }, "How each survey was done"), " · ",
        h("a", { href: page("methods.html") }, "How the comparison works"), " · ",
        h("a", { href: `${base}contact.html?${new URLSearchParams({ member: m.bioguide_id, name: m.name,
          from: location.href })}#feedback` }, "Report an error"), ".")] : [];

      return h("section", { class: "opinion" },
        h("h3", { id: "compared", tabindex: "-1" }, "Compared with constituents"),
        h("p", { class: "intro" },
          `Did this member vote the way most people ${where ? `in ${where}` : "they represented"} wanted?`),
        this.foldable("how-compared", "How this works and how to read the bars",
          h("p", {},
            `${several ? "Surveys" : "A survey"} asked people about a few major bills; this section `,
            "compares the member's vote on each with what people where they live said. ",
            "Only bills a survey asked about can be compared."),
          o.items.some(i => i.kind === "ballot") ? h("p", {},
            "State ballot measures are not surveys: they are the certified votes of the state's own voters on a ",
            "similar question, so they have no range. They are compared only with members who represent the whole ",
            "state (senators, and the representative of a one-district state), and only as related votes, never counted.") : null,
          h("p", {},
          "The dark mark is the estimated share who support the bill, and the shaded band is ",
          "where support likely falls. The tick in the middle is an even split; if the band crosses it, the area is ",
          "too close to call. The member's vote sits at the end of the scale it supported (usually Yea at the support end), ",
          "so when vote and band are on the same side, they agree. ",
          m.chamber === "senate"
            ? "Senators are compared with their whole state."
            // Only true of small district samples (the CES has a few dozen people per district;
            // district surveys such as PPC's have hundreds), so say it only when it applies.
            : o.items.some(i => i.constituents.area === "district" && i.constituents.respondents < 100)
              ? "Where a survey reached only a few dozen people in the district, its estimate leans on statewide answers, so many of those are too close to call."
              : "")),
        lead,
        this.samplesLine(o, surveys, nb),
        h("div", { class: "op-key", "aria-hidden": "true" },
          h("span", {}, mark("yea", 12), "Voted Yea"),
          h("span", {}, mark("nay", 12), "Voted Nay"),
          h("span", {}, "(at the end their vote supported)"),
          h("span", {}, h("i", { class: "sw with" }), "With the majority"),
          h("span", {}, h("i", { class: "sw against" }), "Against the majority"),
          h("span", {}, h("i", { class: "sw unclear" }), "Too close to call")),
        h("div", { class: "op-scale", "aria-hidden": "true" },
          h("span", {}, "All oppose"), h("span", {}, "Even split"), h("span", {}, "All support")),
        this.groupByCongress(rows),
        sourceLines.length ? h("div", { id: "sources", class: "op-sources", tabindex: "-1" }, sourceLines) : null);
    }

    // Comparisons newest first, one fold per Congress of the vote, each summarizing how the
    // member lined up; the latest starts open.
    groupByCongress(rows) {
      const groups = new Map();
      for (const li of rows) {
        const c = Number(li.getAttribute("data-congress"));
        groups.set(c, [...(groups.get(c) || []), li]);
      }
      const years = c => c ? ` (${2 * c + 1787}–${2 * c + 1788})` : "";
      const tally = lis => {
        const n = a => lis.filter(li => li.getAttribute("data-agreement") === a).length;
        const clear = n("with") + n("against");
        return `${plural(lis.length, "vote", "votes")} compared` +
          (clear ? `; with the majority on ${n("with")} of ${clear} where it was clear` : "");
      };
      // Every Congress is its own fold, the same for every member; the latest starts open.
      return h("div", { class: "op-groups" },
        [...groups].sort((a, b) => b[0] - a[0]).map(([c, lis], k) => this.foldableOpen(`op-congress-${c}`, k === 0,
          [c ? `${ordinal(c)} Congress${years(c)}` : "Votes compared", " ", h("span", { class: "op-tally" }, `· ${tally(lis)}`)],
          h("ol", { class: "op-list" }, lis))));
    }

    // "People surveyed": one line per source. A source with many surveys (the CES, every year)
    // gets a one-line summary, with the year-by-year counts folded underneath.
    samplesLine(o, surveys, nb) {
      const samples = o.samples || [];
      if (!samples.length) return null;
      const orgOf = x => (surveys.get(x.survey) || {}).organization || x.survey;
      const byOrg = new Map();
      for (const x of samples) byOrg.set(orgOf(x), [...(byOrg.get(orgOf(x)) || []), x]);
      const detail = x => [h("strong", {}, x.surveyed.toLocaleString()), ` in ${nb(x.area_label)} (${x.survey})`,
        x.residents ? `, out of about ${people(x.residents)} residents` : ""];
      const lines = [...byOrg].map(([org, xs]) => {
        if (xs.length <= 2) return h("p", { class: "op-sample" }, "People surveyed: ",
          xs.map((x, k) => [k ? "; " : "", ...detail(x)]).flat(), ".");
        const counts = xs.map(x => x.surveyed), areas = [...new Set(xs.map(x => nb(x.area_label)))];
        const yrs = xs.map(x => (x.survey.match(/(\d{4})$/) || [])[1]).filter(Boolean).sort();
        const span = yrs.length ? ` (${yrs[0]}–${yrs.at(-1)})` : "";
        return h("div", { class: "op-sample" },
          h("p", {}, "People surveyed",
            areas.length === 1 ? ` in ${areas[0]}` : " where they represented",
            ": ", h("strong", {}, Math.min(...counts).toLocaleString()), " to ",
            h("strong", {}, Math.max(...counts).toLocaleString()),
            ` per survey, in ${xs.length} ${org} surveys${span}.`),
          this.foldable(`samples-${org}`, "Each survey",
            h("ul", { class: "op-sample-list" }, xs.map(x => h("li", {}, ...detail(x))))));
      });
      return lines.length === 1 ? lines[0] : h("div", {}, lines);
    }

    rangeBar(est, lo, hi, label, side, agreement, position) {
      const ns = "http://www.w3.org/2000/svg";
      const svg = document.createElementNS(ns, "svg");
      svg.setAttribute("class", "op-bar");
      svg.setAttribute("viewBox", "0 0 100 10");
      svg.setAttribute("preserveAspectRatio", "none");
      svg.setAttribute("aria-hidden", "true");
      const add = (tag, attrs) => {
        const el = document.createElementNS(ns, tag);
        for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
        svg.appendChild(el);
      };
      const tone = { with: ["var(--mark-soft)", "var(--mark)"], against: ["var(--against-soft)", "var(--against)"] }[agreement]
        || ["var(--unclear-soft)", "var(--ink-soft)"];
      add("rect", { x: 0, y: 4, width: 100, height: 2, fill: "var(--rule)" });                       // 0..100% track
      add("rect", { x: lo, y: 1.5, width: Math.max(0.8, hi - lo), height: 7, rx: 1, fill: tone[0] });
      add("rect", { x: 49.8, y: 0, width: 0.4, height: 10, fill: "var(--ink-soft)" });               // 50% line
      add("rect", { x: Math.min(99, Math.max(0, est - 0.6)), y: 1, width: 1.2, height: 8, fill: tone[1] });

      // The member's vote sits at the end of the scale it supported: usually Yea at "All support",
      // but on a vote to block the proposal (support_side nay) a Nay sits there instead.
      // Drawn as HTML so the marker keeps its shape however wide the bar is stretched.
      const wrap = h("div", { class: "op-barwrap", role: "img", "aria-label": label }, svg);
      if (side && (position === "yea" || position === "nay")) {
        const pin = h("span", { class: `op-pin ${side}` }, mark(position, 14));
        wrap.appendChild(pin);
      }
      return wrap;
    }

    sourceNote() {
      const sources = [...new Set(this.votes.map(v => v.source))];
      const latest = this.votes.length ? fmtDate(this.votes[0].date) : null;
      const from = sources.map(s => SOURCE_TEXT[s] || s).join(" and ");
      const text = sources.length
        ? `Votes from ${from}. Latest vote shown: ${latest}.`
        : "No votes on record for this member yet.";
      return h("p", { class: "source" }, text);
    }
  }

  function plural(n, one, many) { return `${n.toLocaleString()} ${n === 1 ? one : many}`; }

  function ordinal(n) {
    const s = (n % 100 >= 11 && n % 100 <= 13) ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th");
    return `${n}${s}`;
  }

  if (!customElements.get("cc-member-panel")) customElements.define("cc-member-panel", MemberPanel);
})();
