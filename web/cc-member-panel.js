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
    h3[tabindex]:focus { outline: none; }
    h3[tabindex]:focus-visible { outline: 2px solid var(--mark); outline-offset: 4px; }
    h3 { scroll-margin-top: 12px; }
    .intro + .intro { margin-top: 0; }
    .intro { margin: -4px 0 10px; font-size: 0.85rem; color: var(--ink-soft); max-width: 70ch; }
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
                color: var(--ink-soft); margin: 10px 0 2px; }
    .op-scale span:nth-child(2) { text-align: center; }
    .op-scale span:last-child { text-align: right; }
    .op-list { list-style: none; margin: 0; padding: 0; }
    .op-list li { padding: 10px 0; border-top: 1px solid var(--rule); }
    .op-q { margin: 0 0 6px; font-weight: 600; }
    .op-bar { display: block; width: 100%; height: 12px; margin: 0 0 4px; }
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

  const fmtDate = (iso, opts = { month: "short", day: "numeric", year: "numeric" }) =>
    new Date(iso + "T12:00:00").toLocaleDateString("en-US", opts);

  function seatSentence(m) {
    const role = m.chamber === "senate" ? "Senator for" : (m.district === 0 ? "Representative for" : "Representative for");
    const where = m.chamber === "senate" ? m.state : m.seat;
    const party = m.caucus && m.caucus !== m.party ? `${m.party}, caucuses with the ${m.caucus}s` : m.party;
    const status = m.serving ? "" : " (no longer serving)";
    return `${role} ${where}, ${party}${status}`;
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
      } catch (err) {
        if (ticket !== this.request) return;
        this.body.replaceChildren(h("p", { class: "error", role: "alert" },
          `Couldn't load this voting record: ${err.message}. Reload the page to try again.`));
      }
    }

    render() {
      const m = this.member, s = m.stats, votes = this.votes;
      const parts = [
        h("h2", {}, m.name),
        h("p", { class: "seat" }, seatSentence(m)),
      ];
      const jumps = [];
      if (this.opinion?.items?.length) jumps.push(["compared", "Compared with constituents"]);
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
      if (s.votes_total) {
        facts.push(h("li", {}, "Missed ", h("strong", {}, `${s.missed_pct}%`),
          ` of ${s.votes_total.toLocaleString()} votes in the ${ordinal(s.congress)} Congress.`));
      }
      if (s.party_votes) {
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
      const { where, verdict } = this.area();
      const tail = item.agreement === "too_close" ? ", too close to call"
        : verdict[item.agreement] ? `, ${verdict[item.agreement]}` : "";
      const tag = h("button", { type: "button", class: "op-tag" },
        `Surveyed: ${where} ${Math.round(item.constituents.support_pct)}% support${tail}`);
      tag.addEventListener("click", () => this.flash(this.root.querySelector(`li[data-op="${CSS.escape(v.roll_call_id)}"]`)));
      return tag;
    }

    area() {
      const m = this.member;
      // "TX" or "TX-6", with a non-breaking hyphen so it never splits across lines
      const where = (m.chamber === "senate" ? m.state : (this.opinion?.area || m.seat)).replace("-", "\u2011");
      const whose = m.chamber === "senate" ? "state's" : "district's";
      const verdict = {
        with: `with the ${whose} majority`,
        against: `against the ${whose} majority`,
        too_close: `${where} too close to call`,
        did_not_vote: "",
      };
      return { where, whose, verdict };
    }

    opinionSection() {
      const o = this.opinion;
      if (!o || !o.items || !o.items.length) return null;
      const m = this.member;
      const { where, verdict } = this.area();
      const s = o.summary;
      const lead = s.clear_majority
        ? h("p", { class: "op-lead" }, "Voted with ", h("strong", {}, `${s.with_majority} of ${s.clear_majority}`),
            ` surveyed votes where ${where}'s estimated majority was clear.`)
        : h("p", { class: "op-lead" }, `On these votes, ${where}'s estimated opinion was too close to call.`);

      const survey = (o.surveys || [])[0];
      const guide = survey?.guide_url;
      const rows = o.items.map(i => {
        const c = i.constituents;
        const [lo, hi] = c.range_pct;
        const voted = i.position === "yea" || i.position === "nay" ? `Voted ${POSITION_TEXT[i.position]}` : "Did not vote";
        const tail = verdict[i.agreement] ? `, ${verdict[i.agreement]}` : "";
        return h("li", { "data-op": i.vote.roll_call_id },
          h("p", { class: "op-q" }, i.question),
          this.rangeBar(c.support_pct, lo, hi, `${where}: about ${Math.round(c.support_pct)}% support, likely between ${Math.round(lo)}% and ${Math.round(hi)}%`),
          h("p", { class: "op-est" },
            `${where}: ${Math.round(c.support_pct)}% support (likely ${Math.round(lo)}–${Math.round(hi)}%), `,
            `from ${c.respondents.toLocaleString()} ${c.respondents === 1 ? "person" : "people"} surveyed in ${where}`,
            c.respondents < 20 && m.chamber === "house" ? ", so this leans mostly on statewide answers" : "",
            "."),
          h("p", { class: "op-vote" }, mark(i.position, 11),
            h("span", {}, h("strong", {}, voted), tail, ". "),
            h("a", { href: i.vote.official_url, target: "_blank", rel: "noopener" }, fmtDate(i.vote.date))),
          i.note ? h("p", { class: "op-note" }, i.note) : null,
          guide ? h("p", { class: "op-note" },
            h("a", { href: guide, target: "_blank", rel: "noopener",
                     title: `The exact wording is in the survey guide under ${i.item}` },
              `Survey question ${i.item}`), " (exact wording in the survey guide)") : null);
      });

      const link = (href, text) => href ? h("a", { href, target: "_blank", rel: "noopener" }, text) : null;
      const sourceLine = survey ? h("p", { class: "op-source" },
        h("strong", {}, "Source: "),
        `${survey.title}`,
        survey.fielded || survey.respondents
          ? ` (${[survey.fielded && `interviewed ${survey.fielded}`,
                 survey.respondents && `${survey.respondents.toLocaleString()} adults nationwide`].filter(Boolean).join(", ")})`
          : "",
        ", a large academic survey of U.S. adults. ",
        [link(survey.about_url, "About the survey"), link(survey.guide_url, "Questions asked (PDF)"),
         link(survey.dataset_url, "Survey data")].filter(Boolean).flatMap((a, k) => k ? [" | ", a] : [a])) : null;
      return h("section", { class: "opinion" },
        h("h3", { id: "compared", tabindex: "-1" }, "Compared with constituents"),
        h("p", { class: "intro" },
          `Did this member vote the way most people in ${where} wanted? A national survey asked people `,
          "about a few major bills; this section compares the member's vote on each with what people where they ",
          "live said. Only bills the survey asked about can be compared."),
        h("p", { class: "intro" },
          "How to read the bars: the dark mark is the estimated share who support the bill, and the shaded band is ",
          "where support likely falls. The tick in the middle is an even split; if the band crosses it, the area is ",
          "too close to call. ",
          m.chamber === "senate"
            ? "Senators are compared with their whole state."
            : "House districts have few respondents each, so estimates lean on statewide answers and many are too close to call."),
        lead,
        h("div", { class: "op-scale", "aria-hidden": "true" },
          h("span", {}, "All oppose"), h("span", {}, "Even split"), h("span", {}, "All support")),
        h("ol", { class: "op-list" }, rows),
        sourceLine);
    }

    rangeBar(est, lo, hi, label) {
      const ns = "http://www.w3.org/2000/svg";
      const svg = document.createElementNS(ns, "svg");
      svg.setAttribute("class", "op-bar");
      svg.setAttribute("viewBox", "0 0 100 10");
      svg.setAttribute("preserveAspectRatio", "none");
      svg.setAttribute("role", "img");
      svg.setAttribute("aria-label", label);
      const add = (tag, attrs) => {
        const el = document.createElementNS(ns, tag);
        for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
        svg.appendChild(el);
      };
      add("rect", { x: 0, y: 4, width: 100, height: 2, fill: "var(--rule)" });                       // 0..100% track
      add("rect", { x: lo, y: 1.5, width: Math.max(0.8, hi - lo), height: 7, rx: 1, fill: "var(--mark-soft)" });
      add("rect", { x: 49.8, y: 0, width: 0.4, height: 10, fill: "var(--ink-soft)" });               // 50% line
      add("rect", { x: Math.min(99, Math.max(0, est - 0.6)), y: 1, width: 1.2, height: 8, fill: "var(--mark)" });
      return svg;
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

  function ordinal(n) {
    const s = (n % 100 >= 11 && n % 100 <= 13) ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th");
    return `${n}${s}`;
  }

  if (!customElements.get("cc-member-panel")) customElements.define("cc-member-panel", MemberPanel);
})();
