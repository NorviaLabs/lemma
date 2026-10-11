/* Lemma app shell, Exhibit Floor edition:
   bring a paper → review the exhibits → watch them build → walk the hall → keep and share. */
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const main = $("#main");
  let status = { provider: {}, providers: [] };
  let player = null;
  let pollTimer = null;
  let cleanups = [];
  const session = { paper: null, audience: "", outline: null, removed: [], buildJob: null, lesson: null, search: null, mode: "search" };

  /* ------------------------------------------------------------ helpers */
  function h(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return n;
  }

  async function api(path, body, method) {
    const res = await fetch(path, {
      method: method || (body === undefined ? "GET" : "POST"),
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = null;
    try { data = await res.json(); } catch (e) { /* not JSON */ }
    if (!res.ok) {
      const err = new Error((data && data.error) || `Request failed (${res.status})`);
      err.problems = data && data.problems;
      throw err;
    }
    return data;
  }

  function view(...kids) {
    cleanups.forEach((fn) => fn());
    cleanups = [];
    stopPolling();
    if (player) { player.destroy(); player = null; }
    main.replaceChildren(...kids.filter(Boolean));
    const head = main.querySelector("h1, h2");
    if (head) { head.setAttribute("tabindex", "-1"); head.focus({ preventScroll: true }); }
    window.scrollTo(0, 0);
  }

  const setHash = (hash) => history.replaceState(null, "", hash || location.pathname + location.search);
  function stopPolling() { clearTimeout(pollTimer); pollTimer = null; }

  function errorBox(msg, problems) {
    return h("div", { class: "error", role: "alert" }, h("p", {}, msg),
      problems && problems.length ? h("details", {}, h("summary", {}, `${problems.length} problem${problems.length > 1 ? "s" : ""}`), h("ul", {}, problems.slice(0, 40).map((p) => h("li", {}, p)))) : null);
  }

  const ICONS = {
    check: '<path d="M3.5 8.5l3 3 6-6.5"/>',
    cross: '<path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/>',
    copy: '<rect x="5.5" y="5.5" width="8" height="8"/><path d="M10.5 5.5V2.5h-8v8h3"/>',
    refresh: '<path d="M13 8a5 5 0 1 1-1.5-3.6M13 2.5v3h-3"/>',
    play: '<path d="M5 3.5v9l7-4.5z" fill="currentColor" stroke="none"/>',
    up: '<path d="M8 13V3M4 7l4-4 4 4"/>',
    down: '<path d="M8 3v10M4 9l4 4 4-4"/>',
    dash: '<path d="M4 8h8"/>',
    search: '<circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5l3.5 3.5"/>',
    out: '<path d="M9.5 2.5h4v4M13.5 2.5L7.5 8.5M11.5 9.5v4h-9v-9h4"/>',
    shuffle: '<path d="M2.5 4.5h3l5 7h3M2.5 11.5h3l5-7h3M12 3l1.5 1.5L12 6M12 10l1.5 1.5L12 13"/>',
  };
  function icon(name) {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 16 16");
    s.setAttribute("class", "icon");
    s.setAttribute("aria-hidden", "true");
    s.innerHTML = ICONS[name];
    return s;
  }

  const STATE_MARK = { waiting: "", active: "", done: "check", failed: "cross", skipped: "dash" };
  function stepList(steps) {
    return h("ol", { class: "build-steps", "aria-live": "polite" }, steps.map((s, i) =>
      h("li", { class: "build-step " + s.state },
        h("span", { class: "bs-icon", "aria-hidden": "true" }, STATE_MARK[s.state] ? icon(STATE_MARK[s.state]) : String(i + 1)),
        h("span", { class: "bs-label" }, s.label),
        s.detail ? h("span", { class: "bs-detail" }, s.detail) : null,
        h("span", { class: "sr-only" }, ` (${s.state})`))));
  }

  function download(filename, text) {
    const url = URL.createObjectURL(new Blob([text], { type: "text/html" }));
    const a = h("a", { href: url, download: filename });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }
  const slug = (s) => (s || "lesson").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "lesson";

  /* ------------------------------------------------------------ AI tool setup */
  function commandBlock(cmd) {
    const code = h("code", {}, cmd);
    const btn = h("button", { type: "button", class: "copy-btn", "aria-label": `Copy ${cmd}` }, icon("copy"), "Copy");
    btn.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(cmd); }
      catch (e) { const r = document.createRange(); r.selectNodeContents(code); getSelection().removeAllRanges(); getSelection().addRange(r); return; }
      btn.replaceChildren(icon("check"), "Copied");
      btn.classList.add("done");
      setTimeout(() => { btn.replaceChildren(icon("copy"), "Copy"); btn.classList.remove("done"); }, 1600);
    });
    return h("div", { class: "command" }, h("span", { class: "prompt", "aria-hidden": "true" }, "$"), code, btn);
  }

  // What a stranger needs to get each tool working. Commands are each tool's documented ones.
  const SETUP = {
    "opencode-go": {
      tagline: "Many models through an OpenCode Go plan. Fits long papers (about 1M tokens).",
      install: "curl -fsSL https://opencode.ai/install | bash",
      installMore: ["Other ways to install", "https://opencode.ai/docs"],
      signIn: "opencode providers login",
      signInNote: "Choose OpenCode Go when asked. It needs an OpenCode Go plan.",
    },
    codex: {
      tagline: "OpenAI's Codex, signed in with your ChatGPT account. Fits papers up to about 270k tokens.",
      install: "npm install -g @openai/codex",
      installMore: ["Other ways to install", "https://github.com/openai/codex"],
      signIn: "codex login",
      signInNote: "This opens your browser to sign in with ChatGPT.",
    },
  };
  const providerState = (p) => (p.ok ? "Ready" : p.installed ? "Installed, not signed in" : "Not installed");

  function providerSteps(p) {
    const info = SETUP[p.id];
    const step = (n, done, title, body, active) => h("li", { class: "setup-step" + (done ? " done" : active ? " active" : " later") },
      h("span", { class: "plate", "aria-hidden": "true" }, done ? icon("check") : String(n)),
      h("div", { class: "step-body" }, h("p", { class: "step-title" }, title, h("span", { class: "sr-only" }, done ? " (done)" : " (to do)")), ...body));
    return h("ol", { class: "setup-steps" },
      step(1, p.installed, `Install ${p.id === "codex" ? "Codex" : "OpenCode"}`,
        p.installed ? [h("p", { class: "step-detail" }, "Found at ", h("code", {}, p.path), ".")]
          : [h("p", { class: "step-detail" }, "Run this in a terminal:"), commandBlock(info.install),
            h("p", { class: "step-detail" }, h("a", { href: info.installMore[1], target: "_blank", rel: "noopener noreferrer" }, info.installMore[0]))], !p.installed),
      step(2, p.ok, "Sign in",
        p.ok ? [h("p", { class: "step-detail" }, "Signed in.")] : [commandBlock(info.signIn), h("p", { class: "step-detail" }, info.signInNote)], p.installed && !p.ok),
      step(3, p.ok, "Ready to build lessons", p.ok ? [h("p", { class: "step-detail" }, `Lessons will use ${p.model}. You can change the model in Settings.`)] : [], false));
  }

  async function refreshStatus() { status = await api("/api/status/refresh", {}); return status; }

  /* Pick a tool, follow its steps; Lemma notices when it's ready. */
  function setupPanel(onReady) {
    const providers = () => status.providers || [];
    let selected = (providers().find((p) => p.ok) || providers().find((p) => p.installed) || providers()[0] || {}).id;
    const body = h("div");
    const live = h("p", { class: "setup-live muted small", "aria-live": "polite" });
    let checking = false;
    async function check(manual) {
      if (checking) return;
      checking = true;
      if (manual) live.textContent = "Checking…";
      try {
        const before = JSON.stringify(providers().map((p) => [p.installed, p.ok]));
        await refreshStatus();
        const after = JSON.stringify(providers().map((p) => [p.installed, p.ok]));
        if (manual || before !== after) draw();
        live.textContent = manual ? (before === after ? "No change yet. Finish the step above, then check again." : "") : "";
      } catch (e) { live.textContent = "Couldn't check: " + e.message; }
      checking = false;
    }
    function draw() {
      if (!providers().length) {
        body.replaceChildren(errorBox("Lemma couldn't check which AI tools are installed."), h("div", { class: "actions" }, h("button", { class: "ghost", onclick: () => check(true) }, icon("refresh"), "Try again")), live);
        return;
      }
      if (!providers().some((x) => x.id === selected)) selected = providers()[0].id;
      const p = providers().find((x) => x.id === selected);
      const choice = h("div", { class: "provider-choice", role: "radiogroup", "aria-label": "AI tool" }, providers().map((x) =>
        h("label", { class: "provider-option" },
          h("input", { type: "radio", name: "setup-provider", value: x.id, checked: x.id === selected, onchange: () => { selected = x.id; draw(); } }),
          h("span", { class: "po-body" },
            h("span", { class: "po-name" }, x.name),
            h("span", { class: "po-tagline" }, SETUP[x.id].tagline),
            h("span", { class: "po-status " + (x.ok ? "ok" : "") }, x.ok ? icon("check") : null, providerState(x))))));
      const actions = p.ok
        ? h("div", { class: "actions" }, h("button", { class: "primary", onclick: async () => {
            await api("/api/settings", { provider: p.id }).then((st) => (status = Object.assign(status, st)));
            onReady();
          } }, `Use ${p.name}`))
        : h("div", { class: "actions" }, h("button", { class: "ghost", onclick: () => check(true) }, icon("refresh"), "Check again"),
            h("span", { class: "muted small" }, "Lemma also checks when you come back to this window."));
      body.replaceChildren(choice, providerSteps(p), actions, live);
    }
    const onFocus = () => check(false);
    const onVisible = () => { if (document.visibilityState === "visible") check(false); };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisible);
    cleanups.push(() => { window.removeEventListener("focus", onFocus); document.removeEventListener("visibilitychange", onVisible); });
    draw();
    return body;
  }

  /* ------------------------------------------------------------ home */
  // Starting points for "Search a topic"; Surprise me picks one at random.
  const TOPICS = ["Regression to the mean", "The prisoner's dilemma", "Herd immunity", "Simpson's paradox", "Small-world networks",
    "Schelling segregation model", "Statistical power", "Confounding variables", "Bayes' theorem", "Natural selection",
    "Diminishing returns", "Network contagion", "Random walks", "Signal detection theory", "The wisdom of crowds",
    "Opinion dynamics", "Sampling bias", "Loss aversion", "Supply and demand", "Exponential growth"];

  const AUDIENCES = ["A curious learner with no special background", "An undergraduate student", "An educator preparing a class", "A researcher from a neighbouring field"];

  function tryPanel(primary) {
    return h("aside", { class: "try-panel", "aria-labelledby": "try-title" },
      h("h2", { id: "try-title" }, "Walk through an example"),
      h("ol", { class: "steps3" },
        h("li", {}, h("b", {}, "The paper in brief"), "What Galton asked in 1886, what he measured and what he found."),
        h("li", {}, h("b", {}, "How it works"), "Watch each idea play out on a live model, then read it in Galton's words."),
        h("li", {}, h("b", {}, "Try it yourself"), "Make it happen on the model, then use it on a new case.")),
      h("p", { class: "meta" }, "About 10 minutes. Works right away, with no setup."),
      h("button", { class: primary ? "primary" : "ghost", onclick: openExample }, icon("play"), "Try the example lesson"));
  }

  function showHome(msg) {
    setHash("");
    const p = status.provider || {};
    const hero = (primaryTry) => h("section", { class: "home-hero" },
      h("div", {},
        h("h1", {}, "Learn a paper by playing with it"),
        h("p", { class: "lead" }, "Search any topic or bring a paper, and Lemma turns it into a hall of hands-on exhibits. You don't need to have read anything: it tells you the paper's story, walks you through a live model of each idea, then lets you try it yourself.")),
      tryPanel(primaryTry));
    if (!p.ok) {
      view(hero(true), msg ? errorBox(msg) : null,
        h("section", { class: "panel setup", "aria-labelledby": "setup-title" },
          h("h2", { id: "setup-title" }, "Make lessons from your own papers"),
          h("p", {}, "Lemma doesn't come with an AI model. It uses one you install and sign in to yourself, so your papers go only where you choose. Pick one; you can switch later in Settings."),
          setupPanel(() => showHome())));
      return;
    }
    let mode = session.mode || "search";
    const qIn = h("input", { type: "search", id: "topic-q", placeholder: "For example: herd immunity, Simpson's paradox, loss aversion", autocomplete: "off", maxlength: 200 });
    const results = h("section", { class: "results", "aria-live": "polite", "aria-labelledby": "results-title" });
    const runSearch = async (q) => {
      q = (q ?? qIn.value).trim();
      if (!q) return qIn.focus();
      qIn.value = q;
      errSlot.replaceChildren();
      submit.disabled = true;
      submit.textContent = "Searching…";
      results.replaceChildren(h("p", { class: "muted" }, `Searching for “${q}”…`));
      try { session.search = await api("/api/search", { query: q }); drawResults(); }
      catch (err) { results.replaceChildren(); errSlot.append(errorBox(err.message)); }
      submit.disabled = false;
      submit.textContent = "Search";
    };
    const chips = h("div", { class: "chips", role: "group", "aria-label": "Try a topic" },
      TOPICS.slice(0, 4).map((t) => h("button", { type: "button", class: "chip", onclick: () => runSearch(t) }, t)),
      h("button", { type: "button", class: "chip surprise", onclick: () => runSearch(TOPICS[Math.floor(Math.random() * TOPICS.length)]) }, icon("shuffle"), "Surprise me"));
    function drawResults() {
      const r = session.search;
      if (!r) return results.replaceChildren();
      const cards = r.results.map((x) => {
        const err = h("div");
        const learn = h("button", { class: "primary small", onclick: async () => {
          err.replaceChildren();
          session.audience = audSel.value === "other" ? audOther.value.trim() || AUDIENCES[0] : audSel.value;
          results.querySelectorAll(".result button").forEach((b) => (b.disabled = true));
          learn.textContent = "Reading…";
          try { session.paper = await api("/api/papers", { urls: x.urls || [x.url] }); startOutline(); }
          catch (e) {
            err.append(errorBox(e.message));
            results.querySelectorAll(".result button").forEach((b) => (b.disabled = false));
            learn.textContent = "Learn from this";
          }
        } }, "Learn from this");
        const badge = x.kind === "overview" ? "Overview" : x.source === "arXiv" ? "Preprint" : "Paper";
        const meta = [x.authors, x.year, x.venue].filter(Boolean).join(" · ");
        return h("li", { class: "result" },
          h("div", { class: "r-tags" }, h("span", { class: "tag" + (x.kind === "overview" ? " yellow" : "") }, badge),
            x.cited_by ? h("span", { class: "r-cites" }, `Cited ${x.cited_by.toLocaleString()} times`) : null,
            h("span", { class: "r-src" }, "via " + x.source)),
          h("h3", { class: "r-title" }, x.title),
          meta ? h("p", { class: "r-meta" }, meta) : null,
          x.summary ? h("p", { class: "r-sum" }, x.summary) : null,
          h("div", { class: "r-actions" }, learn,
            h("a", { href: x.url, target: "_blank", rel: "noopener noreferrer", class: "r-open" }, "Open it", icon("out"), h("span", { class: "sr-only" }, " (opens in a new tab)"))),
          err);
      });
      results.replaceChildren(...[
        h("h2", { id: "results-title" }, r.results.length ? `Top resources for “${r.query}”` : `Nothing readable found for “${r.query}”`),
        r.results.length ? h("p", { class: "muted" }, "Pick one to learn from. An overview is the gentlest start; widely cited papers go deeper. Lemma reads the one you pick and builds the lesson from it.")
          : h("p", { class: "muted" }, "Try other words, or paste a link to a paper you already have."),
        r.unavailable.length ? h("p", { class: "muted small" }, `${r.unavailable.join(" and ")} didn't answer, so ${r.unavailable.length > 1 ? "their" : "its"} results are missing. Search again in a moment to include them.`) : null,
        h("ol", { class: "result-list" }, cards)].filter(Boolean));
    }
    const urlIn = h("input", { type: "url", id: "paper-url", placeholder: "https://arxiv.org/abs/… or any link to a paper", autocomplete: "off" });
    const fileIn = h("input", { type: "file", id: "paper-file", accept: ".pdf,.html,.htm,.txt,application/pdf,text/html,text/plain" });
    const audSel = h("select", { id: "aud-select" }, AUDIENCES.map((a) => h("option", { value: a }, a)), h("option", { value: "other" }, "Someone else…"));
    const audOther = h("input", { type: "text", id: "aud-other", placeholder: "For example, a nurse curious about trial design", hidden: true, "aria-label": "Describe who the lesson is for" });
    if (session.audience) {
      if (AUDIENCES.includes(session.audience)) audSel.value = session.audience;
      else { audSel.value = "other"; audOther.hidden = false; audOther.value = session.audience; }
    }
    audSel.addEventListener("change", () => { audOther.hidden = audSel.value !== "other"; if (!audOther.hidden) audOther.focus(); });
    const searchPane = h("div", {}, h("label", { for: "topic-q" }, "What do you want to learn about?"), qIn, chips);
    const linkPane = h("div", {}, h("label", { for: "paper-url" }, "Link to the paper"), urlIn);
    const filePane = h("div", {}, h("label", { for: "paper-file" }, "A PDF, saved web page or text file"), fileIn);
    const panes = { search: searchPane, link: linkPane, file: filePane };
    const tabs = { search: "Search a topic", link: "Paste a link", file: "Upload a file" };
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
      submit.textContent = m === "search" ? "Search" : "Read the paper";
      privacy.replaceChildren(...(m === "search"
        ? ["Your search words go to OpenAlex, arXiv and Wikipedia to find resources. When you pick one, Lemma downloads it and sends its text to ", h("strong", {}, p.label || "your AI tool"), " to build the lesson. Nothing else leaves your computer, and Lemma keeps no usage logs. "]
        : ["When you continue, Lemma sends the paper's text to ", h("strong", {}, p.label || "your AI tool"), " to build the lesson. Nothing else leaves your computer, and Lemma keeps no usage logs. "]),
        h("a", { href: "#/settings" }, "Change the AI tool or model"));
    }
    const form = h("form", { class: "panel bring", "aria-labelledby": "bring-title", onsubmit: async (e) => {
      e.preventDefault();
      errSlot.replaceChildren();
      session.audience = audSel.value === "other" ? audOther.value.trim() || AUDIENCES[0] : audSel.value;
      if (mode === "search") return runSearch();
      let body;
      if (mode === "link") {
        if (!urlIn.value.trim()) return urlIn.focus();
        body = { url: urlIn.value.trim() };
      } else {
        const f = fileIn.files[0];
        if (!f) return fileIn.focus();
        if (f.size > 40 * 1024 * 1024) { errSlot.append(errorBox("That file is larger than 40 MB.")); return; }
        body = { filename: f.name, content_type: f.type, data: await fileToBase64(f) };
      }
      submit.disabled = true;
      submit.textContent = "Reading…";
      try {
        session.paper = await api("/api/papers", body);
        startOutline();
      } catch (err) {
        errSlot.append(errorBox(err.message));
        submit.disabled = false;
        submit.textContent = "Read the paper";
      }
    } },
      h("h2", { id: "bring-title" }, "Find something to learn"),
      h("div", { class: "segmented", role: "tablist", "aria-label": "How to find it" }, Object.values(tabBtns)),
      searchPane, linkPane, filePane,
      h("label", { for: "aud-select" }, "Who is it for?"), audSel, audOther,
      privacy,
      errSlot,
      h("div", { class: "actions" }, submit, h("span", { class: "muted small" }, "Building usually takes 1–3 minutes. You can start the first exhibit sooner.")));
    const recent = h("section", { class: "recent", hidden: true, "aria-labelledby": "recent-title" });
    setMode(mode);
    if (session.search) { qIn.value = session.search.query; drawResults(); }
    view(hero(false), msg ? errorBox(msg) : null, form, results, recent);
    if (status.library_count) {
      api("/api/lessons").then((items) => {
        if (!items.length) return;
        recent.hidden = false;
        recent.replaceChildren(h("h2", { id: "recent-title" }, "Your recent lessons"),
          h("ul", { class: "recent-list" }, items.slice(0, 3).map((it) => h("li", {},
            h("button", { class: "recent-item", onclick: async () => openLesson(await api(`/api/lessons/${it.id}`), { saved: true }) },
              h("span", { class: "ri-title" }, it.title), h("span", { class: "ri-meta" }, `${it.concepts} exhibit${it.concepts === 1 ? "" : "s"} · ${it.source}`))))),
          items.length > 3 ? h("a", { href: "#/library" }, `All ${items.length} lessons`) : null);
      }).catch(() => {});
    }
  }

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result).split(",")[1] || "");
      r.onerror = () => reject(new Error("Couldn't read that file."));
      r.readAsDataURL(file);
    });
  }

  /* ------------------------------------------------------------ outline */
  async function startOutline() {
    const p = session.paper;
    const box = h("div");
    const cancel = h("button", { class: "ghost" }, "Cancel");
    view(h("section", { class: "panel" },
      h("h1", {}, "Reading the paper"),
      h("p", {}, h("strong", {}, p.title), h("span", { class: "muted" }, ` · ${p.pages ? p.pages + " pages · " : ""}${Math.round(p.chars / 1000)}k characters`)),
      h("p", { class: "muted" }, `Sending the text to ${status.provider.label}. This usually takes under a minute.`),
      box, h("div", { class: "actions" }, cancel)));
    let job;
    try { job = await api("/api/outline", { paper_id: p.paper_id, audience: session.audience }); } catch (err) { return showHome(err.message); }
    cancel.onclick = () => { api(`/api/jobs/${job.id}/cancel`, {}); showHome(); };
    const poll = async () => {
      let s;
      try { s = await api(`/api/jobs/${job.id}`); } catch (err) { box.replaceChildren(errorBox(err.message)); return; }
      box.replaceChildren(stepList(s.steps));
      if (s.status === "running") { pollTimer = setTimeout(poll, 1000); return; }
      if (s.status === "done") {
        session.outline = s.result;
        session.outline.concepts.forEach((c) => (c.known = false));
        session.removed = [];
        showOutline();
      } else if (s.status === "error") { box.append(errorBox(s.error)); cancel.textContent = "Back"; }
    };
    poll();
  }

  function showOutline() {
    setHash("#/outline");
    const o = session.outline;
    const list = h("ol", { class: "outline-list" });
    const removedBox = h("div");
    const buildBtn = h("button", { class: "primary", onclick: startBuild });
    function draw(focusSel) {
      const cs = o.concepts;
      list.replaceChildren(...cs.map((c, i) => h("li", { class: "outline-item" + (c.known ? " known" : "") },
        h("div", {},
          h("div", { class: "oi-title" }, h("strong", {}, c.title), h("span", { class: "tag" }, c.role || "core"), h("span", { class: "tag" }, c.visual),
            c.hard ? h("span", { class: "tag" }, "hard: has a check") : null,
            (() => { const b = cs.findIndex((x) => x.id === c.builds_on); return b >= 0 && b < i ? h("span", { class: "tag" }, `reuses ${b + 1}'s model`) : null; })()),
          h("p", { class: "oi-idea" }, c.idea),
          c.known ? h("p", { class: "muted small" }, "You know this one: it will be skipped.") : null),
        h("div", { class: "oi-btns" },
          h("button", { class: "small", "data-k": `up-${i}`, "aria-label": `Move “${c.title}” up`, disabled: i === 0, onclick: () => { [cs[i - 1], cs[i]] = [cs[i], cs[i - 1]]; draw(`[data-k="up-${i - 1}"]`); } }, icon("up")),
          h("button", { class: "small", "data-k": `down-${i}`, "aria-label": `Move “${c.title}” down`, disabled: i === cs.length - 1, onclick: () => { [cs[i + 1], cs[i]] = [cs[i], cs[i + 1]]; draw(`[data-k="down-${i + 1}"]`); } }, icon("down")),
          h("button", { class: "small", "aria-pressed": c.known ? "true" : "false", onclick: () => { c.known = !c.known; draw(); } }, c.known ? icon("check") : null, "I know this"),
          h("button", { class: "small danger", "aria-label": `Remove “${c.title}”`, onclick: () => { session.removed.push(cs.splice(i, 1)[0]); draw(); } }, "Remove")))));
      removedBox.replaceChildren(session.removed.length ? h("div", { class: "removed" }, h("h3", {}, "Removed"), h("ul", {}, session.removed.map((c, i) => h("li", {}, c.title, " ", h("button", { class: "small", onclick: () => { o.concepts.push(session.removed.splice(i, 1)[0]); draw(); } }, "Restore"))))) : "");
      const n = cs.filter((c) => !c.known).length;
      buildBtn.textContent = `Build ${n} exhibit${n === 1 ? "" : "s"}`;
      buildBtn.disabled = n === 0;
      if (focusSel) { const b = list.querySelector(focusSel); if (b && !b.disabled) b.focus(); }
    }
    draw();
    view(h("section", {},
      h("h1", {}, o.title),
      h("p", { class: "muted" }, [o.source?.title, o.source?.authors, o.source?.year ? `(${o.source.year})` : ""].filter(Boolean).join(" · ")),
      h("p", { style: "font-size:19px;max-width:66ch" }, o.summary),
      (o.primer || []).length ? h("details", { class: "advanced" },
        h("summary", {}, `The paper in brief: ${o.primer.length} pages read before the first exhibit`),
        ...o.primer.map((pg) => h("div", {}, h("h3", {}, pg.heading), h("p", { style: "max-width:66ch;white-space:pre-line" }, pg.body)))) : null,
      h("p", { class: "note" }, "Here's the proposed hall of exhibits, from background to the paper's main result. Reorder them, remove any, or mark the ones you already know."),
      list, removedBox,
      h("div", { class: "actions" }, buildBtn, h("button", { class: "ghost", onclick: () => showHome() }, "Start over"))));
  }

  /* ------------------------------------------------------------ build */
  async function startBuild() {
    let job;
    try { job = await api("/api/build", { paper_id: session.paper.paper_id, audience: session.audience, outline: session.outline }); } catch (err) { return showHome(err.message); }
    session.buildJob = job.id;
    showBuilding(job.id);
  }

  function showBuilding(jobId) {
    setHash("#/building");
    const stepsBox = h("div"), errSlot = h("div");
    const startBtn = h("button", { class: "primary", disabled: true, onclick: () => openBuilding(jobId) }, "Start the first exhibit");
    const cancel = h("button", { class: "ghost", onclick: async () => { await api(`/api/jobs/${jobId}/cancel`, {}).catch(() => {}); showHome(); } }, "Cancel");
    view(h("section", { class: "panel" },
      h("h1", {}, "Building your exhibits"),
      h("p", { style: "max-width:66ch" }, "Each exhibit is drafted, then checked: its quote must appear in the paper, its model must work, and every goal must be reachable. Exhibits that fail are fixed or left out, never shown broken."),
      stepsBox, errSlot,
      h("p", { class: "muted small" }, "You can start the first exhibit as soon as it's ready. The rest keep building in the background."),
      h("div", { class: "actions" }, startBtn, cancel)));
    const poll = async () => {
      let s;
      try { s = await api(`/api/jobs/${jobId}`); } catch (err) { errSlot.replaceChildren(errorBox(err.message)); return; }
      stepsBox.replaceChildren(stepList(s.steps));
      startBtn.disabled = !(s.lesson && s.lesson.concepts.length);
      if (s.status === "running") { pollTimer = setTimeout(poll, 1200); return; }
      if (s.status === "done") { session.lesson = s.result; startBtn.disabled = false; startBtn.textContent = "Open the lesson"; startBtn.onclick = () => openLesson(s.result); cancel.textContent = "Back"; }
      else if (s.status === "error") { errSlot.replaceChildren(errorBox(s.error)); cancel.textContent = "Back"; }
    };
    poll();
  }

  async function openBuilding(jobId) {
    const s = await api(`/api/jobs/${jobId}`);
    if (s.status === "done") return openLesson(s.result);
    openLesson(s.lesson, { live: jobId });
  }

  /* ------------------------------------------------------------ learn */
  function openLesson(lesson, opts = {}) {
    view();
    setHash(lesson.example ? "#/example" : opts.saved ? `#/lesson/${lesson.id}` : "#/learn");
    const host = h("div", { class: "player-host" });
    main.replaceChildren(host);
    player = LemmaPlayer.mount(host, lesson, {
      onExit: () => showHome(),
      onSave: lesson.example ? null : saveLesson,
      onDownload: downloadLesson,
      onEdit: lesson.example ? null : (l) => showEditor(l),
      onOwnPaper: lesson.example ? () => showHome() : null,
    });
    if (opts.live) {
      const jobId = opts.live;
      const poll = async () => {
        let s;
        try { s = await api(`/api/jobs/${jobId}`); } catch (e) { return; }
        if (!player) return;
        if (s.status === "running") { player.update(s.lesson); pollTimer = setTimeout(poll, 1500); }
        else if (s.status === "done") { session.lesson = s.result; player.update(s.result); }
        else if (s.status === "error" && s.lesson) { const l = Object.assign({}, s.lesson); delete l.plan; player.update(l); }
      };
      pollTimer = setTimeout(poll, 1500);
    }
  }

  async function saveLesson(lesson, btn) {
    try {
      await api("/api/lessons", { lesson });
      if (btn) { btn.replaceChildren(icon("check"), "Saved to your library"); btn.disabled = true; }
    } catch (err) {
      if (btn) btn.textContent = "Couldn't save";
      alertInline(err.message, err.problems);
    }
  }

  function alertInline(msg, problems) {
    const box = errorBox(msg, problems);
    box.classList.add("floating");
    box.append(h("button", { class: "small", onclick: () => box.remove() }, "Dismiss"));
    document.body.append(box);
  }

  async function downloadLesson(lesson) {
    try {
      const res = await fetch("/api/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lesson }) });
      if (!res.ok) throw new Error((await res.json()).error || "Export failed");
      download(`${slug(lesson.title)}.html`, await res.text());
    } catch (err) { alertInline(err.message); }
  }

  async function openExample() { try { openLesson(await api("/api/example")); } catch (err) { showHome(err.message); } }

  /* ------------------------------------------------------------ library */
  async function showLibrary() {
    let items = [];
    try { items = await api("/api/lessons"); } catch (err) { return showHome(err.message); }
    const list = h("ul", { class: "library" }, items.map((it) => {
      const del = h("button", { class: "small danger", onclick: async () => {
        if (del.dataset.armed !== "1") { del.dataset.armed = "1"; del.textContent = "Confirm delete"; return; }
        await api(`/api/lessons/${it.id}`, undefined, "DELETE");
        showLibrary();
      } }, "Delete");
      return h("li", { class: "lib-item" },
        h("div", {}, h("h3", {}, it.title), h("p", { class: "muted small", style: "margin:0" }, `${it.source} · ${it.concepts} exhibit${it.concepts === 1 ? "" : "s"} · saved ${new Date(it.saved * 1000).toLocaleDateString()}`)),
        h("div", { class: "actions" },
          h("button", { class: "small primary", onclick: async () => openLesson(await api(`/api/lessons/${it.id}`), { saved: true }) }, "Open"),
          h("button", { class: "small", onclick: async () => downloadLesson(await api(`/api/lessons/${it.id}`)) }, "Download"),
          h("button", { class: "small", onclick: async () => showEditor(await api(`/api/lessons/${it.id}`)) }, "Edit"),
          del));
    }));
    view(h("section", {},
      h("h1", {}, "My library"),
      h("p", { class: "muted", style: "max-width:66ch" }, "Lessons saved on this computer. Download one to get a single file that works offline and sends nothing anywhere."),
      items.length ? list : h("div", { class: "panel empty" },
        h("h2", {}, "No saved lessons yet"),
        h("p", {}, "Lessons you save live here, on this computer. They open without an internet connection, and any of them downloads as a single file you can share."),
        h("p", { class: "muted small" }, "Finish a lesson you've built and choose “Save to my library” at the end."),
        h("div", { class: "actions" },
          h("a", { class: "btn primary", href: "#/" }, "Make a lesson"),
          h("button", { class: "ghost", onclick: openExample }, icon("play"), "Try the example lesson")))));
  }

  /* ------------------------------------------------------------ editor */
  const EDIT_FIELDS = [
    ["title", "Title"], ["idea", "Idea"],
    ["understand.explanation", "In plain words"], ["understand.quote", "Quote (must match the paper word for word)"], ["understand.quote_where", "Where the quote appears"],
    ["explore.prompt", "Try-it prompt"], ["predict.question", "Use-it question"],
    ["understand.feedback.correct", "Feedback on a right answer"], ["understand.feedback.incorrect", "Feedback on a wrong answer"],
    ["model.note", "Teaching-model note"], ["check.hint", "Check hint (hard concepts only)"], ["check.misconception", "Common mix-up (hard concepts only)"], ["connect.caption", "Equation caption"], ["recap", "In one line"],
  ];
  const getPath = (o, p) => p.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
  const setPath = (o, p, v) => { const ks = p.split("."); const last = ks.pop(); const t = ks.reduce((a, k) => (a[k] ||= {}), o); t[last] = v; };

  function showEditor(lessonIn) {
    setHash("#/edit");
    const lesson = JSON.parse(JSON.stringify(lessonIn));
    const errSlot = h("div");
    const fields = [];
    const field = (label, obj, path, long) => {
      const id = "f" + fields.length;
      const input = long ? h("textarea", { id, rows: 3 }) : h("input", { id, type: "text" });
      input.value = getPath(obj, path) ?? "";
      fields.push(() => setPath(obj, path, input.value));
      return h("div", {}, h("label", { for: id }, label), input);
    };
    const json = h("textarea", { id: "json-edit", rows: 18, class: "mono", spellcheck: "false", "aria-label": "Lesson JSON" });
    const advanced = h("details", { class: "advanced", ontoggle: () => { if (advanced.open) { fields.forEach((f) => f()); json.value = JSON.stringify(lesson, null, 2); } } },
      h("summary", {}, "Advanced: edit the whole lesson as JSON"), json,
      h("p", { class: "muted small" }, "While this panel is open, saving uses the JSON above."));
    const save = h("button", { class: "primary", onclick: async () => {
      errSlot.replaceChildren();
      let edited = lesson;
      if (advanced.open) { try { edited = JSON.parse(json.value); } catch (e) { errSlot.append(errorBox("The JSON isn't valid: " + e.message)); return; } }
      else fields.forEach((f) => f());
      save.disabled = true;
      try { await api("/api/lessons", { lesson: edited }); errSlot.append(h("p", { class: "ok", role: "status" }, icon("check"), " Checked and saved to your library.")); }
      catch (err) { errSlot.append(errorBox(err.message + " The lesson was not saved, because a lesson that fails its checks is never shown to learners.", err.problems)); }
      save.disabled = false;
    } }, "Check and save");
    view(h("section", {},
      h("h1", {}, "Edit lesson"),
      h("p", { class: "muted", style: "max-width:66ch" }, "Correct anything before sharing. Saving re-runs every quality check against the paper: quotes must still match word for word, and every goal must still be reachable."),
      h("fieldset", {}, h("legend", {}, "Lesson"), field("Lesson title", lesson, "title"), field("Summary", lesson, "intro.summary", true)),
      Array.isArray(lesson.primer) ? h("fieldset", {}, h("legend", {}, "The paper in brief"),
        ...lesson.primer.flatMap((pg, i) => [field(`Page ${i + 1} heading`, pg, "heading"), field(`Page ${i + 1} text`, pg, "body", true),
          field(`Page ${i + 1} quote (optional; must match the paper word for word)`, pg, "quote", true)])) : null,
      ...lesson.concepts.map((c, i) => h("fieldset", {}, h("legend", {}, `Exhibit ${i + 1}: ${c.title}`),
        EDIT_FIELDS.filter(([p]) => !p.startsWith("check.") || c.check).map(([p, label]) => field(label, c, p, /explanation|feedback|quote$|caption|misconception|note|idea|question|prompt/.test(p))))),
      advanced, errSlot,
      h("div", { class: "actions sticky-actions" }, save,
        h("button", { class: "ghost", onclick: () => openLesson(lesson, { saved: true }) }, "Preview"),
        h("a", { class: "btn ghost", href: "#/library" }, "Back to library"))));
  }

  /* ------------------------------------------------------------ settings */
  function showSettings() {
    let providers = status.providers || [];
    let selected = (status.provider || {}).id || (providers[0] || {}).id;
    const msg = h("div", { role: "status" });
    const detail = h("div");
    let model, path;
    const choice = () => h("div", { class: "provider-choice", role: "radiogroup", "aria-label": "AI tool" }, providers.map((p) =>
      h("label", { class: "provider-option" },
        h("input", { type: "radio", name: "provider", value: p.id, checked: p.id === selected, onchange: () => { selected = p.id; drawDetail(); } }),
        h("span", { class: "po-body" },
          h("span", { class: "po-name" }, p.name),
          h("span", { class: "po-status " + (p.ok ? "ok" : "") }, p.ok ? icon("check") : null, p.ok ? `Ready · ${p.model}` : providerState(p))))));
    function drawDetail() {
      const p = providers.find((x) => x.id === selected) || {};
      model = h("select", { id: "model", disabled: true }, h("option", { value: p.model }, p.ok ? `${p.model} (loading the list…)` : `Connect ${p.name} to choose a model`));
      const note = h("p", { class: "muted small" }, `Models come from ${p.name} through your local installation.`);
      path = h("input", { id: "tool-path", type: "text", autocomplete: "off", placeholder: p.path || (p.id === "codex" ? "~/.local/bin/codex" : "/opt/homebrew/bin/opencode") });
      path.value = p.configured_path || "";
      const how = p.id === "codex"
        ? "Lemma runs each request as a one-off `codex exec` that saves nothing to disk, ignores your Codex config and rules, and runs in a read-only sandbox in an empty folder. Approvals are set to never, and the shell, code execution, web search, browser, computer use, apps, plugins, MCP servers, memories and image tools are turned off, so the model can only read what Lemma sends and reply with text."
        : "Lemma runs its own private copy of `opencode serve`, reachable only from this computer and protected by a one-time password. Its agent has no tools, so the model can only read what Lemma sends and reply with text. Lemma deletes each OpenCode session when it finishes, so papers don't stay in your OpenCode history.";
      detail.replaceChildren(...[
        p.ok ? null : h("div", { class: "settings-setup" }, providerSteps(p),
          h("div", { class: "actions" }, h("button", { class: "ghost", onclick: async () => { await refreshStatus(); providers = status.providers || []; showSettings(); } }, icon("refresh"), "Check again"))),
        h("label", { for: "model" }, `${p.name} model`), model, note,
        h("label", { for: "tool-path" }, `${p.name} program`), path,
        h("p", { class: "muted small" }, p.path ? `Found at ${p.path}. Leave this blank to keep finding it automatically.` : `Not found automatically. Enter the full path to the ${p.id === "codex" ? "codex" : "opencode"} program.`),
        h("p", { class: "muted small", style: "max-width:70ch" }, how)].filter(Boolean));
      if (p.ok) {
        const want = selected;
        api(`/api/models/${p.id}`).then((r) => {
          if (want !== selected) return;
          model.replaceChildren(...r.models.map((m) => h("option", { value: m.id, selected: m.id === r.current }, `${m.name}${m.context ? ` · ${Math.round(m.context / 1000)}k context` : ""}`)));
          if (!r.models.some((m) => m.id === r.current)) model.prepend(h("option", { value: r.current, selected: true }, `${r.current} (not offered right now)`));
          model.disabled = false;
          note.textContent = `${r.models.length} models offered by ${p.name}${r.version ? ` · ${r.version}` : ""}.`;
        }).catch((err) => note.replaceChildren(errorBox(err.message)));
      }
    }
    view(h("section", { class: "panel", style: "max-width:900px" },
      h("h1", {}, "Settings"),
      h("p", { style: "max-width:66ch" }, "Lemma builds lessons with an AI tool already installed and signed in on this computer. It sends a paper's text only when you build a lesson, and only to the tool and model chosen here."),
      h("h3", {}, "AI tool"), choice(), detail, msg,
      h("div", { class: "actions" },
        h("button", { class: "primary", onclick: async () => {
          const body = { provider: selected, path: path.value.trim() };
          if (!model.disabled && model.value) body.model = model.value;
          try {
            status = await api("/api/settings", body);
            msg.replaceChildren(h("p", { class: "ok" }, icon("check"), status.provider.ok ? ` Saved. Lessons will be built with ${status.provider.label}.` : " Saved. " + status.provider.message));
          } catch (err) { msg.replaceChildren(errorBox(err.message)); }
        } }, "Save"),
        h("a", { class: "btn ghost", href: "#/" }, "Back"))));
    drawDetail();
  }

  /* ------------------------------------------------------------ routing */
  async function route() {
    const hash = location.hash;
    if (hash === "#/library") return showLibrary();
    if (hash === "#/settings") return showSettings();
    if (hash === "#/example") return player ? null : openExample();
    if (hash.startsWith("#/lesson/")) {
      if (player) return;
      try { return openLesson(await api(`/api/lessons/${hash.slice(9)}`), { saved: true }); } catch (e) { return showHome(e.message); }
    }
    if (hash === "#/outline" && session.outline) return;
    if (hash === "#/building" && session.buildJob) return;
    if (hash === "#/learn" || hash === "#/edit") return;
    return showHome();
  }

  window.addEventListener("hashchange", () => {
    if (["#/library", "#/settings", "#/", ""].includes(location.hash) && player) { player.destroy(); player = null; }
    route();
  });

  (async function init() {
    try { status = await api("/api/status"); } catch (e) { /* the server will report */ }
    $("#settings-link").hidden = false;
    route();
  })();
})();
