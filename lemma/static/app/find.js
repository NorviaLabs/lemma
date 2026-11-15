/* Finding sources: a search's progress, results and field and level, or a link or file brought by the learner. */
import { api, busy, errorBox, ext, h, holdIntent, icon, session, status } from "./shell.js";
import { showMake, TOPICS } from "./home.js";
import { showConnect, showRequest } from "./build.js";
import { openLesson } from "./learn.js";

// What a search is doing while it runs: each library answering, then each source being checked.
const SERVICE_NAMES = { "Stanford Encyclopedia of Philosophy": "Stanford Encyclopedia" };
function searchProgress(q) {
  const list = h("ul", { class: "search-services" });
  const bar = h("progress", { class: "search-bar", "aria-hidden": "true" });  // no value: still asking the libraries
  const line = h("p", { class: "muted small" }, "Working out what to look up…");
  const said = h("p", { class: "sr-only", role: "status" }, `Searching for “${q}”.`);
  // Muted for screen readers, which would otherwise hear every tick; `said` announces each new phase instead.
  const el = h("div", { class: "search-progress", "aria-live": "off" },
    h("p", { class: "sp-head" }, h("span", { class: "spinner sp-spin", "aria-hidden": "true" }), `Searching for “${q}”`), list, bar, line, said);
  let phase = "asking";
  function update(p) {
    if (!p || p.planning === "active") return;
    if (phase === "asking") line.textContent = "Asking the libraries…";
    list.replaceChildren(...Object.entries(p.services).map(([name, st]) => h("li", { class: `sp-${st}` },
      st === "searching" ? h("span", { class: "sp-dot", "aria-hidden": "true" }) : icon(st === "done" ? "check" : "cross"),
      h("span", {}, SERVICE_NAMES[name] || name),
      h("span", { class: "muted" }, st === "searching" ? "searching…" : st === "failed" ? "didn't answer" : `${p.found[name]} found`))));
    if (Object.values(p.services).includes("searching") || !p.to_check) return;
    bar.max = p.to_check;
    bar.value = p.checked;
    line.textContent = `Checking which ones OpenLemma can read: ${p.checked} of ${p.to_check} checked, ${p.readable} readable so far`;
    if (phase === "asking") {  // announce the change of phase once, not every tick
      phase = "checking";
      said.textContent = `Found ${p.to_check} sources. Checking which ones OpenLemma can read.`;
    }
  }
  return { el, update };
}

/* The build panel for the #/make page: search a topic, paste a link or upload a paper, then start. */
export function findPanel() {
  const p = status.provider || {};
  const signedOut = !status.user;  // the example and gallery work signed out, but building needs an account
  const toSignIn = (intent) => { holdIntent(intent || { mode }); location.hash = "#/signin?next=build"; };
  let mode = session.mode === "search" || !session.mode ? "search" : "bring";
  const qIn = h("input", { type: "search", id: "topic-q", placeholder: "For example: herd immunity, Simpson's paradox, loss aversion", autocomplete: "off", maxlength: 200 });
  const results = h("section", { class: "results", "aria-live": "polite", "aria-labelledby": "results-title" });
  let searchSeq = 0;  // a newer search (or leaving the page) quietly retires an older one
  // `field` is one the learner chose instead of Jev's pick. A level is sent only once the learner has set one
  // this visit; otherwise the account's level for the question's field applies.
  const runSearch = async (q, field) => {
    q = (q ?? qIn.value).trim();
    if (!q) return qIn.focus();
    if (signedOut) return toSignIn({ mode: "search", ask: q });
    // The learner's AI provider works out what to look up, so a search needs one, as a build does.
    if (!(status.provider || {}).ok) return showConnect(() => { session.ask = q; session.mode = "search"; showMake(); });
    qIn.value = q;
    errSlot.replaceChildren();
    const seq = ++searchSeq, current = () => seq === searchSeq && results.isConnected;
    busy(submit, true);
    submit.textContent = "Searching…";
    const progress = searchProgress(q);
    results.replaceChildren(progress.el);
    try {
      let s = await api("/api/search", { query: q, ...(session.levelTouched ? { level: session.level } : {}), ...(field ? { field } : {}) });
      while (!s.done) {
        if (!current()) return;
        progress.update(s.progress);
        await new Promise((r) => setTimeout(r, 400));
        s = await api(`/api/search/${s.id}`);
      }
      if (!current()) return;
      if (s.error) throw new Error(s.error);
      session.search = s.result;
      if (s.result.plan?.level) setLevel(s.result.plan.level);  // the level it was searched at, which the lesson uses
      if (s.result.field?.chosen_by === "jev") session.likely = { query: s.result.query, field: s.result.field };
      drawResults();
    } catch (err) {
      if (current()) { results.replaceChildren(); errSlot.append(errorBox(err.message)); }
    } finally {
      if (seq === searchSeq) { busy(submit, false); submit.textContent = "Find sources"; }
    }
  };
  const chips = h("div", { class: "chips", role: "group", "aria-label": "Try a concept" },
    TOPICS.slice(0, 4).map((t) => h("button", { type: "button", class: "chip", onclick: () => runSearch(t) }, t)),
    h("button", { type: "button", class: "chip surprise", onclick: () => runSearch(TOPICS[Math.floor(Math.random() * TOPICS.length)]) }, icon("shuffle"), "Surprise me"));
  // "Searching as Psychology · Beginner · Change": the field Jev read the question in, which the learner can switch.
  const fieldName = (ids) => ids.map((id) => (status.fields || []).find((x) => x.id === id)?.name || id).join(" + ");
  function fieldLine(r) {
    const f = r.field, levelName = (status.levels || []).find((l) => l.id === r.plan?.level)?.name;
    const jevs = session.likely?.query === r.query ? session.likely.field : f.chosen_by === "jev" ? f : null;
    const options = jevs ? [jevs.ids, ...jevs.alternatives.map((a) => [a.id])] : [f.ids];
    let choice = f.ids, level = r.plan?.level;
    const same = (a, b) => a.join("+") === b.join("+");
    const chips = options.map((ids) => h("button", { type: "button", role: "radio", class: "chip", onclick: () => pick(ids) }, fieldName(ids)));
    const other = h("select", { id: "field-other", onchange: () => other.value && pick([other.value]) },
      h("option", { value: "" }, "Another field…"), (status.fields || []).map((x) => h("option", { value: x.id }, x.name)));
    function pick(ids) {
      choice = ids;
      chips.forEach((c, i) => c.setAttribute("aria-checked", String(same(options[i], ids))));
      if (options.some((o) => same(o, ids))) other.value = "";
      again.disabled = same(choice, f.ids) && level === r.plan?.level;
    }
    const levelBtns = (status.levels || []).map((l) => h("button", { type: "button", role: "radio", class: "seg", onclick: () => setPanelLevel(l.id) }, l.name));
    function setPanelLevel(v) {
      level = v;
      (status.levels || []).forEach((l, i) => { levelBtns[i].classList.toggle("active", l.id === v); levelBtns[i].setAttribute("aria-checked", String(l.id === v)); });
      pick(choice);
    }
    const again = h("button", { type: "button", class: "primary small", onclick: () => {
      if (level !== r.plan?.level) setLevel(level, true);
      runSearch(r.query, jevs && same(choice, jevs.ids) ? null : choice);  // back to Jev's own pick needs no field
    } }, "Search again");
    const panel = h("div", { class: "field-change", id: "field-change", hidden: true },
      h("p", { class: "fc-label", id: "fc-field" }, "Field"),
      h("div", { class: "chips", role: "radiogroup", "aria-labelledby": "fc-field" }, chips),
      h("label", { for: "field-other", class: "sr-only" }, "Another field"), other,
      h("p", { class: "fc-label", id: "fc-level" }, "Your level"),
      h("div", { class: "segmented", role: "radiogroup", "aria-labelledby": "fc-level" }, levelBtns),
      h("div", { class: "actions" }, again, h("span", { class: "muted small" }, "A new search counts toward today's searches.")));
    setPanelLevel(level);
    const toggle = h("button", { type: "button", class: "ghost small", "aria-expanded": "false", "aria-controls": "field-change", onclick: () => {
      panel.hidden = !panel.hidden;
      toggle.setAttribute("aria-expanded", String(!panel.hidden));
      if (!panel.hidden) (chips.find((c) => c.getAttribute("aria-checked") === "true") || other).focus();
    } }, "Change");
    return [h("p", { class: "field-line" }, h("span", {}, "Searching as ", h("strong", {}, fieldName(f.ids)), levelName ? ` · ${levelName}` : ""), toggle), panel];
  }
  function drawResults() {
    const r = session.search;
    if (!r) return results.replaceChildren();
    const selected = new Set(r.results.filter((x) => x.recommended));
    const make = h("button", { class: "primary", disabled: !selected.size, onclick: async () => {
      const begin = async () => {
        busy(make, true);
        // The search goes with the sources, so the outline answers the question and knows what it builds on.
        const search = { query: r.query, field: r.field?.ids || null, subjects: r.graph?.subjects || [], not_covered: r.graph?.not_covered || [] };
        try { const job = await api("/api/requests", { sources: [...selected], topic: r.query, level: session.level, search }); showRequest(job.id); }
        catch (e) { errSlot.replaceChildren(errorBox(e.message)); busy(make, false); }
      };
      if (!(status.provider || {}).ok) return showConnect(begin);
      await begin();
    } });
    const label = () => { make.textContent = `Create lesson from ${selected.size} source${selected.size === 1 ? "" : "s"}`; };
    label();
    const cards = r.results.map((x, i) => {
      const check = h("input", { type: "checkbox", id: `source-${i}`, checked: selected.has(x), onchange: () => {
        if (check.checked) selected.add(x); else selected.delete(x);
        make.disabled = !selected.size;
        label();
      } });
      const learn = h("label", { class: "source-choice", for: `source-${i}` }, check, "Include this source",
        x.recommended ? h("span", { class: "tag" }, `Recommended · ${x.recommendation}`) : null);
      const badge = x.kind === "overview" ? "Overview" : x.kind === "explainer" ? (x.source === "LibreTexts" ? "Textbook" : "Encyclopedia") : x.source === "arXiv" ? "Preprint" : "Paper";
      const meta = [x.authors, x.year, x.venue].filter(Boolean).join(" · ");
      return h("li", { class: "result" },
        h("div", { class: "r-tags" }, h("span", { class: "tag" + (x.kind === "paper" ? "" : " yellow") }, badge),
          x.cited_by ? h("span", { class: "r-cites" }, `Cited ${x.cited_by.toLocaleString()} times`) : null,
          h("span", { class: "r-src" }, "via " + x.source)),
        h("h3", { class: "r-title" }, x.title),
        meta ? h("p", { class: "r-meta" }, meta) : null,
        x.summary ? h("p", { class: "r-sum" }, x.summary) : null,
        h("p", { class: "muted small" }, x.available ? "Full text checked. Availability can change." : `Couldn't confirm OpenLemma can read the full text: ${x.availability_error || "Try another source."}`),
        h("div", { class: "r-actions" }, learn,
          ext(x.link || x.url, "Open source", h("span", { class: "sr-only" }, `: ${x.title}`))),
        null);
    });
    results.replaceChildren(...[
      h("h2", { id: "results-title" }, r.results.length ? `Sources for “${r.query}”` : `Nothing readable found for “${r.query}”`),
      ...(r.field ? fieldLine(r) : []),
      r.results.length ? h("p", { class: "muted" }, r.kind === "paper"
        ? "OpenLemma suggests the papers that best match your search, with an overview and what they build on for context. They're a starting point, not full coverage. Change any selection before you start."
        : "OpenLemma suggests an overview, articles on what the idea builds on, and an in-depth explanation and a paper where it finds them. They're a starting point, not full coverage. Change any selection before you start.")
        : h("p", { class: "muted" }, "Try other words, or paste a link to a source you already have."),
      // A subject the learner needs that no readable source was found for: the lesson takes it as known.
      r.graph?.not_covered?.length ? h("p", { class: "muted small" }, `Not covered by these sources: ${new Intl.ListFormat("en").format(r.graph.not_covered)}. The lesson will assume you know ${r.graph.not_covered.length > 1 ? "them" : "it"}.`) : null,
      r.unavailable.length ? h("p", { class: "muted small" }, `${r.unavailable.join(" and ")} didn't answer, so ${r.unavailable.length > 1 ? "their" : "its"} results are missing. Search again in a moment to include them.`) : null,
      h("ol", { class: "result-list" }, cards), r.results.length ? make : null].filter(Boolean));
  }
  // Bring sources: any mix of links and files, in the learner's order, for one lesson.
  const MAX_SOURCES = 10, MAX_FILES = 5;  // the server's limits; it keeps only a person's five newest uploads in memory
  const picks = [];  // { kind: "link", input } or { kind: "file", file, paperId }, each with its row
  const bringList = h("ol", { class: "bring-list", "aria-label": "Your sources" });
  const bringNote = h("p", { class: "bring-note", "aria-live": "polite" });
  const fileIn = h("input", { type: "file", id: "paper-file", multiple: true, class: "sr-only", tabindex: "-1", accept: ".pdf,.html,.htm,.txt,application/pdf,text/html,text/plain",
    onchange: () => { addFiles([...fileIn.files]); fileIn.value = ""; } });
  const addLinkBtn = h("button", { type: "button", class: "small", onclick: () => addLink(true) }, icon("plus"), "Add a link");
  const addFileBtn = h("button", { type: "button", class: "small", onclick: () => fileIn.click() }, icon("plus"), "Add files");
  const sizeLabel = (n) => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
  const kindLabel = (f) => (/\.pdf$/i.test(f.name) || f.type === "application/pdf" ? "PDF" : /\.html?$/i.test(f.name) ? "Web page" : "Text");
  function removePick(pick) {
    const at = picks.indexOf(pick);
    picks.splice(at, 1);
    pick.row.remove();
    if (!picks.length) addLink(false);
    refreshBring();
    const next = picks[Math.min(at, picks.length - 1)];
    (next.input || next.row.querySelector("button")).focus();
  }
  function addRow(pick, ...content) {
    pick.row = h("li", { class: `bring-item ${pick.kind}` }, ...content,
      h("button", { type: "button", class: "icon-btn danger bring-remove", "aria-label": pick.kind === "file" ? `Remove ${pick.file.name}` : "Remove this link", onclick: () => removePick(pick) }, icon("cross")));
    picks.push(pick);
    bringList.append(pick.row);
  }
  function addLink(focus) {
    if (picks.length >= MAX_SOURCES) return;
    const input = h("input", { type: "url", placeholder: "https://arxiv.org/abs/… or any article link", autocomplete: "off", "aria-label": "Link to a paper, article or chapter", oninput: () => refreshBring() });
    if (!picks.length) input.id = "paper-url";
    addRow({ kind: "link", input }, h("span", { class: "bring-mark", "aria-hidden": "true" }, icon("link")), input);
    refreshBring();
    if (focus) input.focus();
  }
  function addFiles(files) {
    const refused = [];
    // A blank link row makes way for the files.
    picks.filter((x) => x.kind === "link" && !x.input.value.trim()).forEach((x) => { picks.splice(picks.indexOf(x), 1); x.row.remove(); });
    for (const f of files) {
      if (f.size > 40 * 1024 * 1024) refused.push(`${f.name} is larger than 40 MB.`);
      else if (picks.length >= MAX_SOURCES || picks.filter((x) => x.kind === "file").length >= MAX_FILES) refused.push(`${f.name} wasn't added: one lesson takes up to ${MAX_SOURCES} sources, and up to ${MAX_FILES} of them can be files.`);
      else addRow({ kind: "file", file: f }, h("span", { class: "bring-mark", "aria-hidden": "true" }, icon("doc")),
        h("span", { class: "bring-file" }, h("span", { class: "bring-name" }, f.name), h("span", { class: "bring-meta" }, `${kindLabel(f)} · ${sizeLabel(f.size)}`)));
    }
    if (!picks.length) addLink(false);
    refreshBring(refused);
  }
  function refreshBring(refused = []) {
    const files = picks.filter((x) => x.kind === "file").length;
    const ready = picks.filter((x) => x.kind === "file" || x.input.value.trim()).length;  // blank link rows don't count
    picks.forEach((x) => { x.row.querySelector(".bring-remove").hidden = picks.length === 1 && x.kind === "link"; });
    addLinkBtn.disabled = picks.length >= MAX_SOURCES;
    addFileBtn.disabled = picks.length >= MAX_SOURCES || files >= MAX_FILES;
    bringNote.className = "bring-note" + (refused.length ? " warn" : "");
    bringNote.replaceChildren(refused.length ? refused.join(" ")
      : ready > 1 ? `${ready} sources, woven into one lesson. Up to ${MAX_SOURCES}.` : `Add more links or files to combine them into one lesson, up to ${MAX_SOURCES}.`);
    if (mode === "bring" && !submit.disabled) submit.textContent = ready > 1 ? `Read ${ready} sources` : "Read the source";
  }
  // How much the learner already knows, set before searching so it can shape what is found. The account remembers it.
  session.level = session.level || status.level || "beginner";
  const levelBtns = (status.levels || []).map((l) => h("button", { type: "button", role: "radio", class: "seg", onclick: () => setLevel(l.id, true) }, l.name));
  function setLevel(v, touched) {
    session.level = v;
    if (touched) session.levelTouched = true;
    (status.levels || []).forEach((l, i) => { levelBtns[i].classList.toggle("active", l.id === v); levelBtns[i].setAttribute("aria-checked", String(l.id === v)); });
  }
  setLevel(session.level);
  const searchPane = h("div", {}, h("label", { for: "topic-q" }, "A concept or question"), qIn, chips);
  const bringPane = h("div", { class: "bring-pane",
      ondragover: (e) => { if ([...e.dataTransfer.types].includes("Files")) { e.preventDefault(); bringPane.classList.add("dropping"); } },
      ondragleave: (e) => { if (!bringPane.contains(e.relatedTarget)) bringPane.classList.remove("dropping"); },
      ondrop: (e) => { e.preventDefault(); bringPane.classList.remove("dropping"); addFiles([...e.dataTransfer.files]); } },
    h("label", { for: "paper-url" }, "Links and files"),
    h("p", { class: "muted small bring-hint" }, "Papers, articles or chapters: paste links, or add PDFs, saved web pages and text files. You can also drop files here."),
    bringList,
    h("div", { class: "bring-add" }, addLinkBtn, addFileBtn, fileIn),
    bringNote);
  const panes = { search: searchPane, bring: bringPane };
  const tabs = { search: "Ask about a concept", bring: "Bring sources" };
  const tabBtns = Object.fromEntries(Object.entries(tabs).map(([k, label]) => [k, h("button", { type: "button", role: "tab", class: "seg", onclick: () => setMode(k) }, label)]));
  const errSlot = h("div");
  const submit = h("button", { type: "submit", class: "primary" });
  const privacy = h("p", { class: "note", style: "margin-top:20px" });
  function setMode(m) {
    mode = session.mode = m;
    for (const k in panes) {
      panes[k].hidden = k !== m;
      tabBtns[k].classList.toggle("active", k === m);
      tabBtns[k].setAttribute("aria-selected", String(k === m));
    }
    results.hidden = m !== "search";
    submit.textContent = "Find sources";
    if (m === "bring") refreshBring();
    const to = () => p.ok ? h("strong", {}, p.label) : signedOut ? "the AI provider you connect after signing in" : "the AI provider you connect next";
    const checks = status.typesafe ? (m === "search" ? "to rank results and check concepts for errors" : "to sort the lesson into a subject and check concepts for errors") : "";
    privacy.replaceChildren(...[
      m === "search" ? ["Your question goes to ", to(), " to work out what to look up, then to Wikipedia, arXiv and four other libraries. The sources you pick go to "] : "The sources you add go to ", to(),
      checks ? [" to build the lesson, and parts go to TypeSafe, a checking service OpenLemma pays for, ", checks, ". "] : " to build the lesson. ",
      // A sign-in provider (a ChatGPT or Claude subscription) has no key to speak of.
      (status.providers || []).find((x) => x.id === p.id)?.sign_in
        ? "Your sources and progress are saved so you can come back. "
        : "Your sources and progress are saved so you can come back; your key isn't. ",
      h("a", { href: "faq#who-sees" }, "What's shared"),
      p.ok ? [" · ", h("a", { href: "#/settings" }, "Change AI provider or model")] : null].flat().filter(Boolean));
  }
  const form = h("form", { class: "panel bring", "aria-label": "New lesson", onsubmit: async (e) => {
    e.preventDefault();
    if (signedOut) return mode === "search" ? runSearch() : toSignIn({ mode });
    errSlot.replaceChildren();
    if (mode === "search") return runSearch();
    const chosen = picks.filter((x) => x.kind === "file" || x.input.value.trim());
    if (!chosen.length) return picks[0].input?.focus();
    if (submit.disabled) return;
    busy(submit, true);
    const label = submit.textContent;
    const sources = [];
    try {
      for (const x of chosen) {
        if (x.kind === "link") { sources.push({ url: x.input.value.trim(), title: x.input.value.trim() }); continue; }
        if (!x.paperId) {  // read once; a retry after another source fails doesn't upload it again
          submit.textContent = `Reading ${x.file.name}…`;
          try { x.paperId = (await api("/api/papers", { filename: x.file.name, content_type: x.file.type, data: await fileToBase64(x.file) })).paper_id; }
          catch (err) { throw new Error(`${x.file.name}: ${err.message}`); }
        }
        sources.push({ paper_id: x.paperId });
      }
    } catch (err) {
      errSlot.append(errorBox(err.message));
      busy(submit, false);
      submit.textContent = label;
      return;
    }
    submit.textContent = label;
    const begin = async () => {
      try { const job = await api("/api/requests", { sources, level: session.level }); showRequest(job.id); }
      catch (e) { errSlot.replaceChildren(errorBox(e.message)); busy(submit, false); }
    };
    if (!(status.provider || {}).ok) return showConnect(begin);
    return begin();
  } },
    h("div", { class: "segmented", role: "tablist", "aria-label": "How to find it" }, Object.values(tabBtns)),
    searchPane, bringPane,
    h("label", { id: "level-label" }, "Your level"),
    h("div", { class: "segmented", role: "radiogroup", "aria-labelledby": "level-label" }, levelBtns),
    privacy,
    errSlot,
    signedOut
      ? h("div", { class: "actions" },
          h("button", { class: "primary", type: "button", onclick: () => (mode === "search" && qIn.value.trim() ? runSearch() : toSignIn({ mode })) }, "Sign in to build"),
          h("span", { class: "muted small" }, "OpenLemma is free. Building uses your own AI key, which your provider may charge for. Your lessons are saved in your library."))
      : h("div", { class: "actions" }, submit, h("span", { class: "muted small" }, "Next you'll review a proposed outline. Building then takes a few minutes, and you can start the first concept before it finishes.")));
  const recent = h("section", { class: "recent", hidden: true, "aria-labelledby": "recent-title" });
  addLink(false);
  setMode(mode);
  if (session.ask) { const q = session.ask; session.ask = null; runSearch(q); }  // asked on the home page
  else if (session.search) { qIn.value = session.search.query; drawResults(); }
  return { form, results, recent };
}

export function loadRecent(recent) {
  if (!status.library_count) return;
  api("/api/lessons").then((items) => {
    if (!items.length) return;
    recent.hidden = false;
    recent.replaceChildren(h("h2", { id: "recent-title" }, "Your recent lessons"),
      h("ul", { class: "recent-list" }, items.slice(0, 3).map((it) => h("li", {},
        h("button", { class: "recent-item", onclick: async () => openLesson(await api(`/api/lessons/${it.id}`), { saved: true }) },
          h("span", { class: "ri-title" }, it.title), h("span", { class: "ri-meta" }, `${it.concepts} concept${it.concepts === 1 ? "" : "s"} · ${it.source}`))))),
      ...(items.length > 3 ? [h("a", { href: "#/library" }, `All ${items.length} lessons`)] : []));
  }).catch(() => {});
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",")[1] || "");
    r.onerror = () => reject(new Error("Couldn't read that file."));
    r.readAsDataURL(file);
  });
}
