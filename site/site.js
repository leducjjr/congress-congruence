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
