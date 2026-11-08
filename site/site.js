// Small shared script for every page: the coverage line in the footer, and the list of
// surveys loaded on the Sources page. Pages work without it; these are additions.
(() => {
  const API = "/api";
  const $ = id => document.getElementById(id);
  const longDate = iso => new Date(iso + "T12:00:00").toLocaleDateString("en-US",
    { month: "long", day: "numeric", year: "numeric" });
  const ordinal = n => n + ((n % 100 >= 11 && n % 100 <= 13) ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"));
  const CADENCE = { house: "checked every 2 hours",
                    senate: "updated daily from Voteview, which can trail the official record by days to weeks" };

  async function getJSON(path) {
    const res = await fetch(API + path);
    if (!res.ok) throw new Error(String(res.status));
    return res.json();
  }

  // "Voting records cover the 119th Congress, starting January 3, 2025. House votes through ..."
  function coverageText(data) {
    if (!data.length) return "";
    const first = data.reduce((a, d) => d.first_vote < a.first_vote ? d : a);
    const lo = Math.min(...data.map(d => d.first_congress)), hi = Math.max(...data.map(d => d.latest_congress));
    const congresses = lo === hi ? `the ${ordinal(lo)} Congress` : `the ${ordinal(lo)} through ${ordinal(hi)} Congresses`;
    const through = ["house", "senate"].map(ch => {
      const rows = data.filter(d => d.chamber === ch);
      if (!rows.length) return null;
      const latest = rows.map(d => d.latest_vote).sort().at(-1);
      return `${ch === "house" ? "House" : "Senate"} votes through ${longDate(latest)} (${CADENCE[ch]})`;
    }).filter(Boolean);
    return `Voting records cover ${congresses}, starting ${longDate(first.first_vote)}. ${through.join("; ")}.`;
  }

  getJSON("/v1/health").then(({ data }) => {
    const text = coverageText(data);
    for (const el of document.querySelectorAll("#site-coverage, [data-coverage]")) el.textContent = text;
  }).catch(() => {});

  // Header search: suggestions as you type; Enter or a click opens the member's page.
  // Keyboard: Up/Down move through suggestions, Enter opens, Escape closes.
  const input = $("site-q"), list = $("site-q-list");
  const memberHref = m => `index.html#${m.state}/${m.bioguide_id}`;
  const describe = m => m.chamber === "senate" ? `Senator, ${m.state} · ${m.party}`
                                               : `Representative, ${m.seat} · ${m.party}`;
  if (input && list) {
    let results = [], active = -1, timer = null, lastQuery = "";
    const close = () => { list.hidden = true; input.setAttribute("aria-expanded", "false");
                          input.removeAttribute("aria-activedescendant"); active = -1; };
    const highlight = i => {
      active = i;
      [...list.children].forEach((li, k) => li.setAttribute("aria-selected", String(k === i)));
      if (i >= 0 && list.children[i]) {
        input.setAttribute("aria-activedescendant", list.children[i].id);
        list.children[i].scrollIntoView({ block: "nearest" });
      }
    };
    const show = (members, query) => {
      results = members;
      list.replaceChildren(...(members.length ? members.map((m, i) => {
        const li = document.createElement("li");
        li.id = `site-q-opt-${i}`; li.setAttribute("role", "option"); li.setAttribute("aria-selected", "false");
        li.append(m.name); const small = document.createElement("small"); small.textContent = describe(m); li.append(small);
        li.addEventListener("mousedown", e => { e.preventDefault(); location.href = memberHref(m); });
        return li;
      }) : [Object.assign(document.createElement("li"), { className: "empty",
              textContent: `No member of Congress matches “${query}”. Try a last name, a state, or a seat like TX-7.` })]));
      list.hidden = false; input.setAttribute("aria-expanded", "true"); active = -1;
    };
    input.addEventListener("input", () => {
      clearTimeout(timer);
      const query = input.value.trim();
      if (query.length < 2) { close(); return; }
      timer = setTimeout(() => {
        lastQuery = query;
        getJSON(`/v1/search?q=${encodeURIComponent(query)}`)
          .then(({ members }) => { if (query === lastQuery && input.value.trim() === query) show(members, query); })
          .catch(close);
      }, 180);
    });
    input.addEventListener("keydown", e => {
      if (list.hidden) return;
      if (e.key === "ArrowDown") { e.preventDefault(); highlight(Math.min(active + 1, results.length - 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); highlight(Math.max(active - 1, 0)); }
      else if (e.key === "Escape") { close(); }
      else if (e.key === "Enter") {
        const pick = active >= 0 ? results[active] : (results.length === 1 ? results[0] : null);
        if (pick) { e.preventDefault(); location.href = memberHref(pick); }   // else the form goes to the results list
      }
    });
    input.addEventListener("blur", () => setTimeout(close, 100));
  }

  // Sources page: one row per survey loaded, under its organization's section.
  const lists = document.querySelectorAll("[data-surveys]");
  if (lists.length) {
    getJSON("/v1/surveys").then(({ surveys }) => {
      for (const box of lists) {
        const org = box.getAttribute("data-surveys");
        const mine = surveys.filter(s => s.organization === org);
        if (!mine.length) { box.textContent = "None loaded yet."; continue; }
        const link = (href, text) => href ? `<a href="${href}">${text}</a>` : "";
        const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
        box.innerHTML = `<table class="survey-table"><thead><tr><th>Survey</th><th>Interviewed</th>
          <th>People surveyed</th><th>Questions compared</th><th>Links</th></tr></thead><tbody>${
          mine.map(s => `<tr><td>${esc(s.title)}</td><td>${esc(s.fielded || "")}</td>
            <td>${s.respondents ? s.respondents.toLocaleString() : "see the survey"}</td>
            <td>${s.items}</td>
            <td>${[link(s.about_url, "About"), link(s.guide_url, "Questions asked"), link(s.dataset_url, "Data")]
                   .filter(Boolean).join(" · ")}</td></tr>`).join("")}</tbody></table>`;
      }
    }).catch(() => { for (const box of lists) box.textContent = "The survey list couldn't be loaded just now."; });
  }
})();
