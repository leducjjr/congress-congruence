// Shared pieces for pages that show survey questions (Search, Surveyed votes): small DOM helper,
// formatting, "your members", and the question card. Exposed as window.CC.
(() => {
  const el = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) if (v != null && v !== false) n.setAttribute(k, v);
    for (const k of kids.flat(Infinity)) if (k != null && k !== false) n.append(k instanceof Node ? k : String(k));
    return n;
  };
  const date = iso => new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  const pct = x => `${Math.round(x)}%`;
  const plural = (n, one, many) => `${n.toLocaleString()} ${n === 1 ? one : many}`;
  const chamberName = c => c === "senate" ? "Senate" : "House";
  const POS = { yea: "Yea", nay: "Nay", present: "Present", not_voting: "didn't vote" };
  const slug = t => t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const STORE = "cc-my-members";

  // "Your members": the members most recently opened on this device (kept only in this browser).
  function myMembers() { try { return JSON.parse(localStorage.getItem(STORE)) || []; } catch { return []; } }
  function forgetMembers() { try { localStorage.removeItem(STORE); } catch { /* nothing stored */ } }

  function yourMembersLine(list) {
    if (!list?.length) return null;
    return el("p", {}, "Your members: ", list.map((m, i) => [i ? " · " : "", el("strong", {}, m.name), ` ${POS[m.position] || m.position}`]));
  }

  function spreadLine(label, s) {
    if (!s) return null;
    const range = s.lowest_pct === s.highest_pct ? pct(s.lowest_pct) : `${pct(s.lowest_pct)} to ${pct(s.highest_pct)}`;
    return el("p", {}, `Support in the ${plural(s.areas, label.one, label.many)} surveyed: ${range}. `,
      `Clear majority in favor in ${s.support}, opposed in ${s.oppose}, too close to call in ${s.too_close}.`);
  }

  // A ballot measure: the share voting yes in each state that voted on it, and where it passed.
  function ballotLine(s) {
    if (!s) return null;
    const range = s.lowest_pct === s.highest_pct ? pct(s.lowest_pct) : `${pct(s.lowest_pct)} to ${pct(s.highest_pct)}`;
    return el("p", {}, `Yes vote in the ${plural(s.areas, "state", "states")} that voted on it: ${range}. `,
      s.oppose ? `Passed in ${s.support}, failed in ${s.oppose}.` : s.areas === 1 ? "It passed." : `Passed in all ${s.support}.`);
  }

  const detailHref = q => `surveyed.html?${new URLSearchParams({ survey: q.survey, item: q.item })}`;

  // One vote's line in a question card: what happened, and how members lined up with their areas.
  function voteSummary(v) {
    const m = v.members;
    const compared = m.with_majority + m.against_majority + m.too_close;
    return el("div", { class: "card-vote" },
      el("p", {}, el("strong", {}, `${chamberName(v.chamber)} vote`), `, ${date(v.date)}: ${v.question || ""} — ${v.result || ""} ${v.yea}–${v.nay}. `,
        v.support_side === "nay" ? "Voting Nay supported the proposal. " : "",
        el("a", { href: v.official_url }, "Official record")),
      v.match === "related"
        ? el("p", { class: "meta" }, "Related vote: close to, but not the same as, what was asked, so members aren't scored on it.")
        : compared
          ? el("p", { class: "tally" }, `Members compared with their own ${v.chamber === "senate" ? "state" : "district"}: `,
              el("strong", {}, m.with_majority.toLocaleString()), " voted with a clear majority, ",
              el("strong", {}, m.against_majority.toLocaleString()), " against one, and ",
              el("strong", {}, m.too_close.toLocaleString()), m.too_close === 1 ? " was" : " were", " in areas too close to call",
              m.not_surveyed ? `; ${plural(m.not_surveyed, "member's area wasn't", "members' areas weren't")} surveyed` : "",
              m.did_not_vote ? `; ${plural(m.did_not_vote, "member", "members")} didn't vote` : "", ".")
          : el("p", { class: "meta" }, "None of the members who voted represent an area this survey covered."),
      yourMembersLine(v.your_members));
  }

  // A survey question: wording, source, spread of support, each chamber's vote. opts.link adds
  // "See how every member voted" (the Surveyed votes detail view); opts.heading sets h2/h3.
  function questionCard(q, opts = {}) {
    return el("article", { class: "result question-card", id: `q-${q.survey}-${q.item}`.replace(/\s+/g, "-") },
      el(opts.heading || "h3", {}, opts.link ? el("a", { href: detailHref(q) }, q.question) : q.question),
      q.source.kind === "ballot"
        ? el("p", { class: "meta" }, `${q.source.title}`, q.source.fielded ? ` · voted ${q.source.fielded}` : "", " · ",
            el("a", { href: `sources.html#${slug(q.source.organization)}` }, "About ballot measures"))
        : el("p", { class: "meta" }, `${q.source.organization} · ${q.source.title}`, q.source.fielded ? ` · asked ${q.source.fielded}` : "", " · ",
            el("a", { href: q.source.guide_url || `sources.html#${slug(q.source.organization)}` },
               q.source.guide_url ? "Survey questions" : "About this survey")),
      q.note ? el("p", { class: "meta" }, q.note) : null,
      q.source.kind === "ballot" ? ballotLine(q.spread.states) : [
        spreadLine({ one: "state", many: "states" }, q.spread.states),
        spreadLine({ one: "district", many: "districts" }, q.spread.districts)],
      q.votes.map(voteSummary),
      opts.link ? el("p", {}, el("a", { class: "more-link", href: detailHref(q) }, "See how every member voted →")) : null);
  }

  window.CC = { API: "/api", el, date, pct, plural, chamberName, POS, slug, myMembers, forgetMembers,
                yourMembersLine, spreadLine, voteSummary, questionCard, detailHref };
})();
