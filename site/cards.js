// Shared pieces for pages that show survey questions (Search, Surveyed votes): small DOM helper,
// formatting, "recently viewed members", and the question card. Exposed as window.CC.
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

  // "Recently viewed members": the members most recently opened on this device (kept only in this
  // browser). Not the visitor's own representatives: the site doesn't know where anyone lives.
  function myMembers() { try { return JSON.parse(localStorage.getItem(STORE)) || []; } catch { return []; } }
  function forgetMembers() { try { localStorage.removeItem(STORE); } catch { /* nothing stored */ } }

  function yourMembersLine(list) {
    if (!list?.length) return null;
    return el("p", {}, "Recently viewed members: ", list.map((m, i) => [i ? " · " : "", el("strong", {}, m.name), ` ${POS[m.position] || m.position}`]));
  }

  // The line above a list explaining "Recently viewed members", with a button to forget them.
  // onForget redraws the page. Returns null when no members have been viewed.
  function recentNote(onForget) {
    const mine = myMembers();
    if (!mine.length) return null;
    const clear = el("button", { type: "button" }, "forget");
    const box = el("p", { class: "mine" }, "Showing how members you recently viewed voted: ",
      el("strong", {}, mine.map(m => m.name).join(", ")),
      ". These are the last members you opened on this device, kept only in this browser. ", clear);
    clear.addEventListener("click", () => { forgetMembers(); box.remove(); onForget?.(); });
    return box;
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

  const partiesHidden = () => document.documentElement.hasAttribute("data-party-blind");
  const ordinal = n => n + ((n % 100 >= 11 && n % 100 <= 13) ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"));
  // #TX/C001098_Ted_Cruz: the ID opens the member; the name is there for people reading the link.
  const nameTag = n => (n || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  const memberHref = m => `index.html#${m.state}/${m.bioguide_id}_${nameTag(m.name)}`;

  // "Yea–Nay by party: Democrats 210–2 · Republicans 3–215" (left out in the party-blind view).
  function partySplit(v) {
    const parties = Object.entries(v.by_party || {}).sort((a, b) => a[0].localeCompare(b[0]))
      .map(([p, c]) => `${p}s ${c.yea || 0}–${c.nay || 0}`).join(" · ");
    return parties ? el("p", { class: "meta party" }, `Yea–Nay by party: ${parties}`) : null;
  }

  // A folded list of every member's vote, fetched when opened: Yea, Nay, Present, didn't vote.
  function whoVoted(rollCallId) {
    const d = el("details", { class: "more who-voted" }, el("summary", {}, "How each member voted"));
    const box = el("div", {}, el("p", { class: "meta" }, "Loading…"));
    d.append(box);
    let loaded = false;
    d.addEventListener("toggle", async () => {
      if (!d.open || loaded) return;
      loaded = true;
      try {
        const res = await fetch(`/api/v1/votes/${encodeURIComponent(rollCallId)}`);
        if (!res.ok) throw new Error(res.status);
        const v = await res.json();
        const groups = ["yea", "nay", "present", "not_voting"].map(pos => [pos, v.members.filter(m => m.position === pos)])
          .filter(([, ms]) => ms.length);
        box.replaceChildren(...groups.map(([pos, ms]) => el("div", { class: "who-group" },
          el("h4", {}, `${pos === "not_voting" ? "Didn't vote" : POS[pos]} (${ms.length})`),
          el("ul", { class: "who-list" }, ms.map(m => el("li", {},
            el("a", { href: memberHref(m) }, m.name), " ",
            el("span", { class: "meta" }, m.seat || "", el("span", { class: "party" }, m.party ? ` · ${m.party}${m.caucus ? `, caucuses with ${m.caucus}s` : ""}` : ""))))))));
      } catch {
        loaded = false;
        box.replaceChildren(el("p", { class: "meta" }, "Couldn't load the members' votes just now. Close and reopen to try again."));
      }
    });
    return d;
  }

  const KIND = { passage: "Passage", amendment: "Amendment", nomination: "Nomination", procedural: "Procedural", other: "Other" };

  // One vote in a list (All votes page): title, what happened, party split, survey links, members.
  function voteCard(v) {
    return el("article", { class: "result vote-card" },
      el("h3", {}, v.bill ? `${v.bill.label}: ` : "", v.description || v.bill_title || v.question || "Vote",
        v.surveyed?.some(s => s.match === "same") ? el("span", { class: "tag surveyed" }, "Surveyed") : null),
      el("p", { class: "meta" }, `${chamberName(v.chamber)} · ${date(v.date)} · `, v.question || "",
        v.result ? ` — ${v.result}` : "", v.yea != null ? ` ${v.yea}–${v.nay}` : "", v.kind ? ` · ${KIND[v.kind] || v.kind}` : "",
        v.policy_area ? ` · Topic: ${v.policy_area}` : ""),
      partySplit(v),
      v.surveyed?.length ? el("p", {}, v.surveyed.map((s, i) => [i ? " " : "",
        el("a", { class: `tag ${s.match === "same" ? "surveyed" : ""}`, href: detailHref(s) },
          s.match === "same" ? `Surveyed: ${s.question}` : `Related to a survey question: ${s.question}`)])) : null,
      yourMembersLine(v.your_members),
      el("p", { class: "meta" }, el("a", { href: v.official_url }, "Official record"),
        v.bill ? [" · ", el("a", { href: v.bill.url }, `${v.bill.label} on Congress.gov`)] : ""),
      whoVoted(v.roll_call_id));
  }

  window.CC = { API: "/api", el, date, pct, plural, chamberName, POS, slug, myMembers, forgetMembers,
                yourMembersLine, recentNote, spreadLine, voteSummary, questionCard, detailHref,
                partiesHidden, ordinal, memberHref, partySplit, whoVoted, voteCard, KIND };
})();
