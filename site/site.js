// Small shared script for every page: the coverage line in the footer, and the list of
// surveys loaded on the Sources page. Pages work without it; these are additions.
(() => {
  const API = "/api";
  const $ = id => document.getElementById(id);
  const longDate = iso => new Date(iso + "T12:00:00").toLocaleDateString("en-US",
    { month: "long", day: "numeric", year: "numeric" });
  const ordinal = n => n + ((n % 100 >= 11 && n % 100 <= 13) ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"));
  const CADENCE = { house: "checked every 2 hours",
                    senate: "checked daily; see Sources for where each vote comes from" };

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
  const nameTag = n => (n || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  const memberHref = m => `index.html#${m.state}/${m.bioguide_id}_${nameTag(m.name)}`;
  const hidden = () => document.documentElement.hasAttribute("data-party-blind");
  const describe = m => (m.former ? "Former " : "") +
    (m.chamber === "senate" ? `${m.former ? "senator" : "Senator"}, ${m.state}` : `${m.former ? "representative" : "Representative"}, ${m.seat}`) +
    (hidden() ? "" : ` · ${m.party}`);
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
      // Members first, then always a last option: search votes and survey questions for the words.
      const option = (i, text, sub, href) => {
        const li = document.createElement("li");
        li.id = `site-q-opt-${i}`; li.setAttribute("role", "option"); li.setAttribute("aria-selected", "false");
        li.append(text);
        if (sub) { const small = document.createElement("small"); small.textContent = sub; li.append(small); }
        li.addEventListener("mousedown", e => { e.preventDefault(); location.href = href; });
        return li;
      };
      const everything = `search.html?q=${encodeURIComponent(query)}`;
      results = [...members.map(m => memberHref(m)), everything];
      list.replaceChildren(...members.map((m, i) => option(i, m.name, describe(m), memberHref(m))),
        option(members.length, `Search votes and survey questions for “${query}”`,
               members.length ? null : "No member’s name matches", everything));
      list.hidden = false; input.setAttribute("aria-expanded", "true"); active = -1;
    };
    input.addEventListener("input", () => {
      clearTimeout(timer);
      const query = input.value.trim();
      if (query.length < 2) { close(); return; }
      timer = setTimeout(() => {
        lastQuery = query;
        getJSON(`/v1/search?only=members&q=${encodeURIComponent(query)}`)
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
        // A highlighted option, or the only member found; otherwise the form opens the Search page.
        const pick = active >= 0 ? results[active] : (results.length === 2 ? results[0] : null);
        if (pick) { e.preventDefault(); location.href = pick; }
      }
    });
    input.addEventListener("blur", () => setTimeout(close, 100));
  }

  // Party-blind switch in the header. Pages and the member panel listen for "cc-party-blind" and
  // redraw; anything marked class="party" is hidden by the stylesheet straight away.
  const blind = $("party-blind");
  if (blind) {
    blind.checked = document.documentElement.hasAttribute("data-party-blind");
    blind.addEventListener("change", () => {
      document.documentElement.toggleAttribute("data-party-blind", blind.checked);
      try { localStorage.setItem("cc-party-blind", blind.checked ? "1" : "0"); } catch { /* not remembered */ }
      window.dispatchEvent(new CustomEvent("cc-party-blind", { detail: { hidden: blind.checked } }));
    });
  }

  // Email addresses: written in pages as "contact (at) example.org" so they aren't harvested from the
  // page source; turned into links here. data-email holds the part before the @.
  for (const span of document.querySelectorAll("[data-email]")) {
    const domain = span.textContent.split("(at)")[1]?.trim();
    if (!domain) continue;
    const address = `${span.getAttribute("data-email")}@${domain}`;
    const a = document.createElement("a");
    a.href = `mailto:${address}`; a.textContent = address;
    span.replaceWith(a);
  }

  // Contact page feedback form. contact.html?member=C001098&name=Ted%20Cruz&from=<page> pre-fills
  // what it's about (the member panel's "Report an error" link does this).
  const form = $("feedback-form");
  if (form) {
    form.hidden = false;
    const opened = Date.now();
    const p = new URLSearchParams(location.search);
    const context = { member: p.get("member") || "", member_name: p.get("name") || "",
                      page: p.get("from") || document.referrer || "" };
    if (context.member) {
      form.kind.value = "error";
      const about = $("feedback-about");
      about.textContent = `About: ${context.member_name || context.member}` +
        (context.page ? ` (sent with a link to the page you were on)` : "");
      about.hidden = false;
    }
    const status = form.querySelector(".form-status"), button = form.querySelector("button");
    form.addEventListener("submit", async e => {
      e.preventDefault();
      status.className = "form-status";
      if (form.message.value.trim().length < 5) { status.textContent = "Please write a little more."; status.classList.add("bad"); form.message.focus(); return; }
      button.disabled = true; status.textContent = "Sending…";
      try {
        const res = await fetch(`${API}/v1/feedback`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: form.kind.value, message: form.message.value, reply_to: form.reply_to.value.trim(),
            website: form.website.value, seconds_open: (Date.now() - opened) / 1000, ...context }) });
        const out = await res.json().catch(() => ({}));
        if (!res.ok || !out.ok) throw new Error(out.message || "Your message couldn't be sent just now. Please use email instead.");
        const replying = form.reply_to.value.trim();
        form.reset();
        status.textContent = "Thank you. Your message was sent to our inbox." +
          (out.copy_sent === true ? ` A copy is on its way to ${replying}; reply to it if you'd like to add anything. ` +
             "If it isn't in your inbox in a few minutes, check your spam or junk folder."
           : out.copy_sent === false ? " We couldn't send you a copy just now, but we have your message and will reply to the address you gave."
           : replying ? " We'll reply to the address you gave." : "");
      } catch (err) {
        status.textContent = err.message; status.classList.add("bad");
      } finally { button.disabled = false; }
    });
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
            <td>${s.kind === "ballot" ? "voters in each state (certified results)"
                  : s.respondents ? s.respondents.toLocaleString() : "see the survey"}</td>
            <td>${s.items}</td>
            <td>${[link(s.about_url, "About"), link(s.guide_url, "Questions asked"), link(s.dataset_url, "Data")]
                   .filter(Boolean).join(" · ")}</td></tr>`).join("")}</tbody></table>`;
      }
    }).catch(() => { for (const box of lists) box.textContent = "The survey list couldn't be loaded just now."; });
  }
})();
