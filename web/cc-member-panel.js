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
        const [member, votes] = await Promise.all([
          this.get(`/v1/members/${encodeURIComponent(id)}`),
          this.get(`/v1/members/${encodeURIComponent(id)}/votes?limit=${STRIP_SIZE}`),
        ]);
        if (ticket !== this.request) return; // a newer member was chosen meanwhile
        this.member = member;
        this.votes = votes.votes;
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

      if (votes.length) {
        // Strip: oldest on the left so it reads like a timeline.
        const ordered = [...votes].reverse();
        const counts = ordered.reduce((a, v) => (a[v.position] = (a[v.position] || 0) + 1, a), {});
        const summary = Object.entries(counts).map(([p, n]) => `${n} ${POSITION_TEXT[p] || p}`).join(", ");
        parts.push(
          h("div", { class: "strip-wrap" },
            h("p", { class: "caption", "aria-hidden": "true" }, "Recent votes, newest at the right"),
            h("p", { class: "sr" }, `Last ${ordered.length} votes, oldest first: ${summary}.`),
            h("div", { class: "strip", "aria-hidden": "true" }, ordered.map(v => {
              const svg = mark(v.position);
              const t = document.createElementNS("http://www.w3.org/2000/svg", "title");
              t.textContent = `${fmtDate(v.date)}: ${POSITION_TEXT[v.position] || v.position_detail}`;
              svg.prepend(t);
              return svg;
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

      if (votes.length) {
        parts.push(h("h3", {}, "Recent votes"));
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

    voteRow(v) {
      const title = v.description || v.question || "Recorded vote";
      const what = v.bill
        ? h("span", { class: "what" }, h("a", { href: v.bill.url, target: "_blank", rel: "noopener" }, v.bill.label), `: ${title}`)
        : h("span", { class: "what" }, title);
      const tally = (v.yea_total != null && v.nay_total != null) ? `, ${v.yea_total}–${v.nay_total}` : "";
      return h("li", {},
        mark(v.position),
        what,
        h("span", { class: "detail" },
          h("span", { class: "their" }, `Voted ${POSITION_TEXT[v.position] === "Did not vote" ? "— did not vote" : POSITION_TEXT[v.position] || v.position_detail}`),
          v.position_detail && !["Yea", "Nay", "Present", "Not Voting"].includes(v.position_detail) ? ` (${v.position_detail})` : "",
          `. ${v.question ? v.question + ", " : ""}${(v.result || "").toLowerCase()}${tally}. `,
          h("a", { href: v.official_url, target: "_blank", rel: "noopener" }, fmtDate(v.date))));
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
