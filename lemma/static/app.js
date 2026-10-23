/* Lemma app shell, Field Guide edition:
   bring a paper → review the outline → watch it build → learn each concept → keep and share. */
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const main = $("#main");
  let status = { provider: {}, providers: [] };
  let player = null;
  let pollTimer = null;
  let cleanups = [];
  const session = { level: "", outline: null, removed: [], lesson: null, search: null, mode: "search" };

  /* ------------------------------------------------------------ helpers */
  function h(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if ((k === "href" || k === "src") && /^\s*(javascript|vbscript|data):/i.test(v)) continue;  // a lesson's links are data, never script
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return n;
  }

  // The learner's provider, models and keys stay in this browser and go to the server with each request.
  const CRED_KEY = "lemma.ai";
  function loadCred() {
    try { return Object.assign({ provider: "", models: {}, keys: {} }, JSON.parse(localStorage.getItem(CRED_KEY) || "{}")); }
    catch (e) { return { provider: "", models: {}, keys: {} }; }
  }
  let cred = loadCred();
  // What a signed-out visitor was about to do, kept through the sign-in round trip (same tab) so they carry on from it.
  const HELD_KEY = "lemma.held";
  function holdIntent(intent) { try { sessionStorage.setItem(HELD_KEY, JSON.stringify({ ...intent, at: Date.now() })); } catch (e) { /* they start again */ } }
  function heldIntent(take) {
    try {
      const v = JSON.parse(sessionStorage.getItem(HELD_KEY) || "null");
      if (take) sessionStorage.removeItem(HELD_KEY);
      return v && Date.now() - v.at < 3600e3 ? v : null;
    } catch (e) { return null; }
  }
  function saveCred(next) {
    cred = next;
    try { localStorage.setItem(CRED_KEY, JSON.stringify(next)); } catch (e) { /* kept for this visit only */ }
  }
  function credHeaders(c = cred) {
    const out = {};
    if (c.provider) out["X-Lemma-Provider"] = c.provider;
    if (c.provider && c.keys[c.provider]) out["X-Lemma-Key"] = c.keys[c.provider];
    if (c.provider && c.models[c.provider]) out["X-Lemma-Model"] = c.models[c.provider];
    return out;
  }

  async function api(path, body, method, headers) {
    const res = await fetch(path.replace(/^\//, ""), { // relative, so Lemma also works under a path such as /lemma/
      method: method || (body === undefined ? "GET" : "POST"),
      headers: Object.assign(body === undefined ? {} : { "Content-Type": "application/json" }, headers || credHeaders()),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = null;
    try { data = await res.json(); } catch (e) { /* not JSON */ }
    if (res.status === 401 && !location.hash.startsWith("#/signin")) {  // signed out, or the session ended
      if (!heldIntent(false)) holdIntent({ route: location.hash });
      location.hash = "#/signin";
    }
    if (!res.ok) {
      const err = new Error((data && data.error) || `Request failed (${res.status})`);
      err.problems = data && data.problems;
      err.status = res.status;
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
  // Each screen names itself in the tab and history; the home page is just "OpenLemma".
  const setTitle = (t) => { document.title = t ? `${t} · OpenLemma` : "OpenLemma"; };
  function stopPolling() { clearTimeout(pollTimer); pollTimer = null; }

  // The id an unexpected error carries, as logs.report writes it: "… (error 1a2b3c4d)." from a build, or "… with error
  // id 1a2b3c4d." from the server's own 500 answer. Ordinary refusals have none.
  const ERROR_ID = /\berror (?:id )?([0-9a-f]{8})\b/;
  /* An error, said in place. One that carries an error id, or a build that stopped (`report`), can be reported
     from where it is shown, by a signed-in account. */
  function errorBox(msg, problems, report, page) {
    const id = (String(msg).match(ERROR_ID) || [])[1];
    let ctx = report || (id ? { kind: "error", error_id: id } : null);
    if (ctx && page) ctx = { ...ctx, page };  // where it happened, when the page has already moved on (home)
    return h("div", { class: "error", role: "alert" }, h("p", {}, msg),
      problems && problems.length ? h("details", {}, h("summary", {}, `${problems.length} problem${problems.length > 1 ? "s" : ""}`), h("ul", {}, problems.slice(0, 40).map((p) => h("li", {}, p)))) : null,
      ctx && status.user ? reportThis(ctx) : null);
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
    plus: '<path d="M8 3.5v9M3.5 8h9"/>',
    link: '<path d="M7 9l2-2M6.2 5.3l1.1-1.1a2.6 2.6 0 0 1 3.7 3.7l-1.1 1.1M9.8 10.7l-1.1 1.1a2.6 2.6 0 0 1-3.7-3.7l1.1-1.1"/>',
    search: '<circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5l3.5 3.5"/>',
    out: '<path d="M9.5 2.5h4v4M13.5 2.5L7.5 8.5M11.5 9.5v4h-9v-9h4"/>',
    shuffle: '<path d="M2.5 4.5h3l5 7h3M2.5 11.5h3l5-7h3M12 3l1.5 1.5L12 6M12 10l1.5 1.5L12 13"/>',
    next: '<path d="M3 8h10M9 4l4 4-4 4"/>',
    doc: '<path d="M9.5 2.5h-6v11h9v-8z"/><path d="M9.5 2.5v3h3M5.5 8.5h5M5.5 11h3.5"/>',
    chevron: '<path d="M6 3.5L10.5 8 6 12.5"/>',
    leave: '<path d="M6.5 2.5h-4v11h4M10 5l3 3-3 3M13 8H6"/>',
    up_thumb: '<path d="M5 7.2v6.3H2.5V7.2zM5 7.2l2.6-4.7c1 0 1.7.9 1.5 1.9l-.4 2.1h3.5c.9 0 1.5.8 1.3 1.7l-.9 4.1c-.2.7-.8 1.2-1.5 1.2H5"/>',
    down_thumb: '<g transform="rotate(180 8 8)"><path d="M5 7.2v6.3H2.5V7.2zM5 7.2l2.6-4.7c1 0 1.7.9 1.5 1.9l-.4 2.1h3.5c.9 0 1.5.8 1.3 1.7l-.9 4.1c-.2.7-.8 1.2-1.5 1.2H5"/></g>',
    flag: '<path d="M3.5 14V2.5M3.5 3h8.5l-2.2 3.2L12 9.5H3.5"/>',
    mail: '<rect x="2" y="3.5" width="12" height="9" rx="1.5"/><path d="M2.5 4.5L8 9l5.5-4.5"/>',
  };
  function icon(name) {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 16 16");
    s.setAttribute("class", "icon");
    s.setAttribute("aria-hidden", "true");
    s.innerHTML = ICONS[name];
    return s;
  }
  // A button that is waiting on the server: disabled and announced busy, but drawn in its own colours (see
  // [aria-busy] in styles.css) so it reads as working, not as unavailable.
  function busy(btn, on) {
    btn.disabled = on;
    if (on) btn.setAttribute("aria-busy", "true"); else btn.removeAttribute("aria-busy");
  }
  // A link that opens in a new tab says so, to the eye (the out arrow) and to a screen reader.
  const ext = (href, ...kids) => h("a", { href, target: "_blank", rel: "noopener noreferrer", class: "ext" }, ...kids, icon("out"), h("span", { class: "sr-only" }, " (opens in a new tab)"));

  /* ------------------------------------------------------------ feedback */
  /* Feedback goes to the people who run OpenLemma, from signed-in accounts only, said where it was asked for:
     the #/feedback page, the end of a lesson, or under an error or a stopped build. The same form everywhere:
     an optional rating, an optional message (one of them is needed, as the server checks), the address a
     reply would go to, then Send. Once sent it gives way to a thank-you line. */
  const FB_MAX = 2000, FB_COUNT_FROM = 1700;  // the server's limit, and where the count starts to show
  const pageOf = (hash) => (hash || "").split("?")[0].slice(0, 300);  // where they were, without any search words
  let fbSeq = 0;
  function feedbackForm(ctx, { variant = "page", onCancel = null, onSent = null } = {}) {
    const n = ++fbSeq, report = variant === "report", lessonEnd = variant === "lesson";
    let rating = null;
    const email = status.user?.email || "";
    const form = h("form", { class: `fb is-${variant}`, novalidate: true });
    const msg = h("textarea", { id: `fb-msg-${n}`, rows: report || lessonEnd ? 3 : 6, maxlength: FB_MAX, "aria-describedby": `fb-count-${n}` });
    const count = h("span", { class: "fb-count", id: `fb-count-${n}`, "aria-hidden": "true" });
    const errSlot = h("div");
    const send = h("button", { type: "submit", class: variant === "page" ? "primary" : "small" }, report ? "Send report" : "Send");
    const seg = (value, label, ic) => h("button", { type: "button", class: "seg", "aria-pressed": "false", "data-value": value, onclick: () => choose(rating === value ? null : value) }, icon(ic), label);
    const rate = h("div", { class: "segmented fb-rate", role: "group", "aria-labelledby": `fb-q-${n}` },
      seg("helpful", "Helpful", "up_thumb"), seg("not_helpful", "Not helpful", "down_thumb"));
    const question = report ? null
      : h(lessonEnd ? "h2" : "p", { class: "fb-q", id: `fb-q-${n}` }, lessonEnd ? "How was this lesson?" : "Is OpenLemma helpful so far?");
    // At the end of a lesson only the rating shows at first; the message and Send open once one is chosen.
    const more = h("div", { class: "fb-more", hidden: lessonEnd },
      h("label", { for: msg.id }, report ? "What happened?" : lessonEnd ? "Anything to add?" : "Message",
        report ? null : h("span", { class: "fb-opt" }, " (optional)")),
      report ? h("p", { class: "fb-help", id: `fb-help-${n}` }, ctx.kind === "build" ? "The build's id is sent with your message." : "The error's id is sent with your message.") : null,
      msg,
      h("div", { class: "fb-foot" }, email ? h("p", { class: "fb-reply" }, "We'll reply from contact@openlemma.org to ", h("strong", {}, email), " if you ask something.") : null, count),
      errSlot,
      h("div", { class: "fb-acts" }, send, onCancel ? h("button", { type: "button", class: "ghost small", onclick: onCancel }, "Cancel") : null));
    if (report) msg.setAttribute("aria-describedby", `fb-help-${n} fb-count-${n}`);
    function choose(value) {
      rating = value;
      rate.querySelectorAll(".seg").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.value === value)));
      if (lessonEnd && value && more.hidden) { more.hidden = false; }
      errSlot.replaceChildren();
    }
    const showCount = () => {
      const len = msg.value.length;
      count.textContent = len >= FB_COUNT_FROM ? `${len.toLocaleString()} / ${FB_MAX.toLocaleString()}` : "";
      count.classList.toggle("is-full", len >= FB_MAX);
    };
    msg.addEventListener("input", () => { showCount(); if (msg.value.trim()) errSlot.replaceChildren(); });
    form.addEventListener("keydown", (e) => { if (e.key === "Escape" && onCancel) { e.preventDefault(); onCancel(); } });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const message = msg.value.trim();
      if (!rating && !message) {
        errSlot.replaceChildren(errorBox(report ? "Write what happened before sending." : "Choose a rating or write a message before sending."));
        return (report || !lessonEnd ? msg : rate.querySelector(".seg")).focus();
      }
      busy(send, true);
      send.textContent = "Sending…";
      errSlot.replaceChildren();
      try {
        const body = { kind: ctx.kind || "general", message };
        if (rating) body.rating = rating;
        for (const k of ["page", "lesson_id", "lesson_title", "error_id", "request_id"]) if (ctx[k]) body[k] = ctx[k];
        const r = await api("/api/feedback", body);
        const thanks = h("p", { class: "fb-thanks", role: "status", tabindex: "-1" }, h("span", { class: "fb-tick", "aria-hidden": "true" }, icon("check")),
          h("span", {}, "Thanks. Sent to the people who run OpenLemma.", r.reply_to ? [" If you asked something, we'll reply from contact@openlemma.org to ", h("strong", {}, r.reply_to), "."] : null));
        form.replaceWith(thanks);
        thanks.focus({ preventScroll: true });
        if (onSent) onSent(thanks);
      } catch (err) {
        busy(send, false);
        send.textContent = report ? "Send report" : "Send";
        errSlot.replaceChildren(h("div", { class: "error", role: "alert" }, h("p", {}, err.message)));
      }
    });
    form.append(...(report ? [] : lessonEnd ? [h("div", { class: "fb-ask" }, question, rate)] : [question, rate]), more);
    return form;
  }

  /* "Report this" under an error or a stopped build: a quiet action that opens the form in place. */
  function reportThis(ctx) {
    const wrap = h("div", { class: "fb-report" });
    const open = h("button", { type: "button", class: "ghost small fb-report-btn", onclick: () => {
      const form = feedbackForm({ page: pageOf(location.hash), ...ctx }, { variant: "report", onCancel: () => { wrap.replaceChildren(open); open.focus(); } });
      wrap.replaceChildren(form);
      form.querySelector("textarea").focus();
    } }, icon("flag"), "Report this");
    wrap.append(open);
    return wrap;
  }

  // The end-of-lesson prompt, handed to the player for signed-in accounts only (a downloaded lesson has none).
  function lessonFeedback(lesson) {
    const ctx = { kind: "lesson", page: pageOf(location.hash), lesson_title: String(lesson.title || "").slice(0, 300) };
    if (/^[A-Za-z0-9_-]{1,64}$/.test(lesson.id || "")) ctx.lesson_id = lesson.id;
    return h("section", { class: "fb-lesson", "aria-label": "Feedback on this lesson" }, feedbackForm(ctx, { variant: "lesson" }));
  }

  // A check's finding starts with the field it is about ("understand.quote: …"); the common ones get a plain name.
  const FIELD_WORDS = { quote: "Quote", understand: "Explanation", model: "Model", goals: "Goal", explore: "Try it", predict: "Question",
    check: "Check", connect: "Equation", activities: "Activity", concept: "Concept", recap: "Recap", title: "Title", idea: "Idea" };
  function checkWords(p) {
    const m = /^([a-z_]+)((?:\.[a-z_]+|\[\d+\])*): (.*)$/s.exec(String(p));
    if (!m) return p;
    const path = (m[1] + m[2]).split(/[.[\]]+/).filter((x) => x && !/^\d+$/.test(x));
    const word = path.includes("quote") ? FIELD_WORDS.quote : path[0] === "explore" && path.includes("goals") ? FIELD_WORDS.goals : FIELD_WORDS[path[0]];
    return word ? `${word}: ${m[3]}` : p;
  }

  const STATE_MARK = { waiting: "", active: "", done: "check", failed: "cross", skipped: "dash" };
  const clock = (sec) => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;

  /* A build's progress: how many concepts are ready, then each step with what it's doing now, how long it has
     taken and, while a concept is being fixed, what the checks found. It updates in place on every poll, so an
     opened list of findings stays open, and its timers tick between polls. */
  function buildProgress() {
    const count = h("p", { class: "bp-count" }), bar = h("progress", { class: "bp-bar", "aria-hidden": "true" });
    const list = h("ol", { class: "build-steps", "aria-live": "off" });  // ticks constantly: shown, not announced
    const said = h("p", { class: "sr-only", role: "status" });
    const el = h("div", { class: "build-progress" }, h("div", { class: "bp-summary" }, count, bar), list, said);
    const rows = new Map();
    let offset = 0, timer = null, lastSaid = "";
    const tick = () => {
      if (!el.isConnected) { clearInterval(timer); timer = null; return; }
      const nowSec = Date.now() / 1000 - offset;
      el.querySelectorAll(".bs-time[data-since]").forEach((t) => { t.textContent = clock(Math.max(0, nowSec - Number(t.dataset.since))); });
    };
    function row(s) {
      let r = rows.get(s.id);
      if (!r) {
        r = { li: h("li", {}), icon: h("span", { class: "bs-icon", "aria-hidden": "true" }), label: h("span", { class: "bs-label" }),
              time: h("span", { class: "bs-time" }), detail: h("span", { class: "bs-detail" }), state: h("span", { class: "sr-only" }),
              found: h("ul", {}), findings: h("details", { class: "bs-found" }, h("summary", {}), null) };
        r.findings.append(r.found);
        r.li.append(r.icon, h("span", { class: "bs-line" }, r.label, r.time), r.detail, r.findings, r.state);
        rows.set(s.id, r);
      }
      return r;
    }
    function update(steps, now) {
      offset = now ? Date.now() / 1000 - now : 0;  // the server's clock against this one, for the timers
      const concepts = steps.filter((s) => s.label.startsWith("Concept "));
      const ready = concepts.filter((s) => s.state === "done").length, out = concepts.filter((s) => s.state === "failed").length;
      if (concepts.length) {
        count.textContent = `${ready} of ${concepts.length} concepts ready` + (out ? ` · ${out} left out` : "");
        bar.max = concepts.length;
        bar.value = ready + out;
      } else {
        const active = steps.find((s) => s.state === "active");
        count.textContent = active ? active.label : "Getting started…";
        bar.removeAttribute("value");  // no count yet: an indeterminate bar
      }
      if (count.textContent !== lastSaid) { said.textContent = lastSaid = count.textContent; }
      list.replaceChildren(...steps.map((s, i) => {
        const r = row(s);
        r.li.className = "build-step " + s.state;
        r.icon.replaceChildren(STATE_MARK[s.state] ? icon(STATE_MARK[s.state]) : String(i + 1));
        r.label.textContent = s.label;
        r.detail.textContent = s.detail || "";
        r.detail.hidden = !s.detail;
        r.state.textContent = ` (${s.state})`;
        if (s.state === "active" && s.started) { r.time.dataset.since = s.started; r.time.hidden = false; }
        else if (s.started && s.finished) { delete r.time.dataset.since; r.time.textContent = clock(s.finished - s.started); r.time.hidden = false; }
        else { delete r.time.dataset.since; r.time.hidden = true; }
        const found = s.state === "active" ? s.problems || [] : [];
        r.findings.hidden = !found.length;
        r.findings.querySelector("summary").textContent = `What the checks found (technical, ${found.length})`;
        r.found.replaceChildren(...found.map((p) => h("li", {}, checkWords(p))));
        return r.li;
      }));
      tick();
      if (!timer) timer = setInterval(tick, 1000);
    }
    return { el, update };
  }

  function download(filename, text) {
    const url = URL.createObjectURL(new Blob([text], { type: "text/html" }));
    const a = h("a", { href: url, download: filename });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }
  // A file name from a title, cut at a word rather than mid-word when the title is long.
  const slug = (s) => {
    const full = fold(s || "lesson").replace(/['’]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    return (full.length > 60 ? full.slice(0, 61).replace(/-[^-]*$/, "") || full.slice(0, 60) : full) || "lesson";
  };

  /* ------------------------------------------------------------ AI provider */
  const TAGLINES = {
    "opencode-go": "Many models through an OpenCode Go plan. Reads long sources: about 1M tokens, roughly 750,000 words.",
    openai: "OpenAI's models, billed to your OpenAI API account.",
    claude: "Anthropic's Claude models, billed to your Claude API account. Reads long sources: about 1M tokens, roughly 750,000 words.",
    chatgpt: "Your ChatGPT Plus or Pro plan, no key needed. For OpenLemma on your own computer.",
  };

  // Said wherever the key comes up, so it reads the same each time.
  const KEY_NOTE = "Your key stays in this browser and is never saved in OpenLemma's storage. The server uses it only while a request or build runs.";

  /* Pick a provider, then paste a key or sign in; Lemma checks either by listing the provider's models.
     `compact` (the connect step) picks the provider's default model and keeps the model list folded away.
     `quiet` (the account page, which says where the key lives above the form) leaves out the key note. */
  function keyForm(onSaved, { compact = false, quiet = false, onCheck = null } = {}) {
    const providers = status.providers || [];
    let selected = providers.some((x) => x.id === cred.provider) ? cred.provider : (providers[0] || {}).id;
    const signins = {};  // sign-in provider id -> its status, e.g. { signed_in, email }
    let poll = null;
    const body = h("div");
    const msg = h("div", { role: "status" });
    const stopPoll = () => { clearTimeout(poll); poll = null; };
    cleanups.push(stopPoll);
    const ready = (x) => (x.sign_in ? !!(signins[x.id] || {}).signed_in : !!cred.keys[x.id]);
    function draw() {
      const p = providers.find((x) => x.id === selected) || {};
      const key = h("input", { id: "ai-key", type: "password", autocomplete: "off", spellcheck: "false", placeholder: `Paste your ${p.name} key` });
      key.value = cred.keys[p.id] || "";
      const model = h("select", { id: "model", disabled: true }, h("option", { value: cred.models[p.id] || p.default_model }, cred.models[p.id] || p.default_model));
      const note = h("p", { class: "muted small" }, p.sign_in ? "Sign in to choose from your plan's models." : "Add a key to choose from the models it can use.");
      const modelName = h("span", {}, cred.models[p.id] || p.default_model);
      const choice = h("div", { class: "provider-choice", role: "radiogroup", "aria-label": "AI provider" }, providers.map((x) =>
        h("label", { class: "provider-option" },
          h("input", { type: "radio", name: "provider", value: x.id, checked: x.id === selected, onchange: () => { selected = x.id; msg.replaceChildren(); draw(); } }),
          h("span", { class: "po-body" },
            h("span", { class: "po-name" }, x.name),
            h("span", { class: "po-tagline" }, TAGLINES[x.id] || "")),
          ready(x) ? h("span", { class: "po-status ok" }, icon("check"), x.sign_in ? "Signed in" : "Key added") : null)));
      async function loadModels(c) {
        const r = await api("/api/models", undefined, undefined, credHeaders(c));
        model.replaceChildren(...r.models.map((m) => h("option", { value: m.id, selected: m.id === r.current }, `${m.name}${m.context ? ` · ${Math.round(m.context / 1000)}k context` : ""}`)));
        if (!r.models.some((m) => m.id === r.current)) model.prepend(h("option", { value: r.current, selected: true }, `${r.current} (not offered right now)`));
        model.disabled = false;
        note.textContent = `${r.models.length} model${r.models.length === 1 ? "" : "s"} offered by ${p.name}.`;
        modelName.textContent = model.selectedOptions[0] ? model.value : r.current;
      }
      // `onCheck` hears whether the saved provider's key still lists models, so the account page can say so.
      const checked = (ok) => { if (onCheck && p.id === cred.provider) onCheck(ok); };
      if (ready(p)) loadModels(Object.assign({}, cred, { provider: p.id })).then(() => checked(true), (err) => { note.replaceChildren(errorBox(err.message)); checked(false); });
      const save = h("button", { class: "primary", disabled: p.sign_in && !ready(p), onclick: async () => {
        const next = { provider: p.id, keys: Object.assign({}, cred.keys), models: Object.assign({}, cred.models) };
        if (!p.sign_in) next.keys[p.id] = key.value.trim();
        if (!model.disabled && model.value) next.models[p.id] = model.value;
        if (!p.sign_in && !next.keys[p.id]) return msg.replaceChildren(errorBox(`Paste your ${p.name} key first.`));
        busy(save, true);
        msg.replaceChildren(h("p", { class: "muted" }, p.sign_in ? "Checking your sign-in…" : "Checking the key…"));
        try {
          await loadModels(next);  // a key that can't list models won't build lessons either
          if (!model.disabled && model.value) next.models[p.id] = model.value;
          saveCred(next);
          status = await api("/api/status");
          msg.replaceChildren(h("p", { class: "ok" }, icon("check"), ` Saved. Lessons will be built with ${status.provider.label}.`));
          if (onSaved) onSaved();
        } catch (err) { msg.replaceChildren(errorBox(err.message)); }
        busy(save, false);
      } }, compact ? "Connect and continue" : p.sign_in ? "Check and save" : "Check and save key");
      model.addEventListener("change", () => { modelName.textContent = model.value; });
      const modelPart = compact
        ? h("details", { class: "model-pick" }, h("summary", {}, "Model: ", modelName, h("span", { class: "mp-change" }, "Change")),
            h("label", { for: "model", class: "sr-only" }, `${p.name} model`), model, note)
        : h("div", {}, h("label", { for: "model" }, `${p.name} model`), model, note);
      body.replaceChildren(choice, ...(p.sign_in ? signInPart(p) : [
        h("label", { for: "ai-key" }, `${p.name} key`), key,
        h("p", { class: "muted small" }, ext(p.key_url, `Get ${/^[aeiou]/i.test(p.name) ? "an" : "a"} ${p.name} key`),
          quiet ? "." : [". ", KEY_NOTE])]),
        modelPart, msg,
        h("div", { class: "actions" }, save));
    }
    function signInPart(p) {  // ChatGPT, the one provider signed in to instead of given a key
      const chatgpt = signins.chatgpt || {};
      if (chatgpt.signed_in) {
        return [h("p", {}, icon("check"), ` Signed in${chatgpt.email ? ` as ${chatgpt.email}` : ""}. `,
          h("button", { class: "ghost small", onclick: async () => { signins.chatgpt = await api("/api/chatgpt/logout", {}); draw(); } }, "Sign out"))];
      }
      if (chatgpt.waiting) {  // the learner types this code on OpenAI's page; nothing on this computer listens for them
        const open = h("button", { class: "primary", onclick: () => {
          navigator.clipboard?.writeText(chatgpt.code).catch(() => {});
          window.open(chatgpt.url, "_blank", "noopener");
        } }, "Copy code and open OpenAI");
        return [h("div", { class: "device-step" },
          h("p", {}, "Enter this code on OpenAI's sign-in page:"),
          h("p", { class: "device-code" }, chatgpt.code),
          open,
          h("p", { class: "muted small" }, "OpenAI's page calls this the Codex CLI and says the code is in your terminal. It means this code. "
            + "OpenLemma notices when you're done, and the code lasts 15 minutes."))];
      }
      const start = h("button", { class: "primary", onclick: async () => {
        try {
          signins.chatgpt = await api("/api/chatgpt/login", {});
          draw();
          body.querySelector(".device-step")?.scrollIntoView({ block: "center", behavior: "smooth" });
          waitForSignIn();
        } catch (err) { msg.replaceChildren(errorBox(err.message)); }
      } }, `Sign in with ${p.name}`);
      return [start, h("p", { class: "muted small" }, "Lessons count against your plan's usage. OpenLemma keeps your sign-in on this computer only, in ~/.lemma, and you can sign out at any time.")];
    }
    function waitForSignIn() {
      stopPoll();
      poll = setTimeout(async () => {
        if (!body.isConnected) return;  // the learner left the account page
        let chatgpt;
        try { chatgpt = signins.chatgpt = await api("/api/chatgpt"); } catch (e) { return waitForSignIn(); }
        if (chatgpt.signed_in) { msg.replaceChildren(); return draw(); }
        if (chatgpt.error) { draw(); return msg.replaceChildren(errorBox(chatgpt.error)); }  // the code is gone: back to the button
        if (chatgpt.waiting) waitForSignIn();
      }, 1500);
    }
    draw();
    for (const x of providers.filter((x) => x.sign_in)) {
      api("/api/chatgpt").then((r) => {
        signins[x.id] = r; draw();
        if (r.waiting) waitForSignIn();  // a sign-in started before this page was opened
      }).catch(() => {});
    }
    return body;
  }

  /* ------------------------------------------------------------ home */
  // Starting points for "Ask about a concept"; Surprise me picks one at random.
  const TOPICS = ["Regression to the mean", "The prisoner's dilemma", "Herd immunity", "Simpson's paradox", "Small-world networks",
    "Schelling segregation model", "Statistical power", "Confounding variables", "Bayes' theorem", "Natural selection",
    "Diminishing returns", "Network contagion", "Random walks", "Signal detection theory", "The wisdom of crowds",
    "Opinion dynamics", "Sampling bias", "Loss aversion", "Supply and demand", "Exponential growth"];


  /* The doorway concept: one live model from the example lesson, playable the moment the page opens.
     The label rail's three verbs light up as the visitor plays; until then the model sweeps by itself. */
  const MEAN = 68.25, SHARE = 2 / 3;
  let exhibitStep = 0;
  let exampleP = null;
  const exampleLesson = () => (exampleP = exampleP || api("/api/example").catch((e) => { exampleP = null; throw e; }));
  /* A signed-in learner with saved lessons gets them back on the home page, under the ways in, in the library's own rows.
     Signed out, or with nothing saved yet, there is no row at all. */
  function homeRecent() {
    const sec = h("section", { class: "he-recent", "aria-labelledby": "he-recent-title", hidden: true });
    if (!status.user || !status.library_count) return sec;
    api("/api/lessons").then((items) => {
      if (!items.length || !sec.isConnected) return;
      sec.replaceChildren(
        h("div", { class: "he-recent-head" },
          h("h2", { id: "he-recent-title" }, "Your recent lessons"),
          h("a", { class: "btn ghost small", href: "#/library" }, "All in your library", icon("next"))),
        h("ul", { class: "lib-list" }, items.slice(0, 3).map((it) => h("li", { class: "lib-row lib-lesson" },
          h("div", { class: "lib-text" },
            h("h3", { class: "lib-title" }, h("a", { class: "lib-open", href: `#/lesson/${it.id}` }, it.title || "Untitled lesson")),
            it.source ? h("p", { class: "lib-source" }, it.source) : null,
            h("p", { class: "lib-meta" }, it.category ? h("span", {}, it.category) : null, h("span", { class: "lib-num" }, plural(it.concepts, "concept")), h("span", {}, "Saved ", when(it.saved))))))));
      sec.hidden = false;
    }).catch(() => {});
    return sec;
  }

  const NOTICED = ["dev", "child_dev"];  // the readouts the home model's Notice step names: parents' and children's distance from average
  function homeExhibit() {
    const M = window.LemmaModel;
    const stage = h("div", { class: "he-stage", "aria-busy": "true" }, h("p", { class: "muted" }, "Setting up the concept…"));
    const verbEls = [];
    const verb = (n, title, ...body) => {
      const li = h("li", { class: "verb" },
        // Steps open as the visitor plays, and any step can be opened straight away.
        h("button", { type: "button", class: "verb-head", onclick: () => setStep(n - 1) }, h("span", { class: "verb-mark", "aria-hidden": "true" }, String(n)), title, h("span", { class: "sr-only verb-state" })),
        h("div", { class: "verb-body" }, ...body));
      verbEls.push(li);
      return li;
    };
    const noticeLine = h("p", { class: "he-live" }, "Watch two numbers as you drag: how far the parents are from average, and how far their children are.");
    const noticeMore = h("p", {}, "Try tall parents first, then short ones.");
    const tryText = h("p", {}, "Regression to the mean, taught from Galton's 1886 study of heredity. Drag the parents' height away from the middle and watch where their children land.");
    const whyBtn = h("button", { type: "button", class: "small he-skip", onclick: () => setStep(2, true) }, "Tell me why");
    const verbs = h("ol", { class: "verbs", "aria-live": "polite" },
      verb(1, "Try this", tryText),
      verb(2, "Notice", noticeLine, noticeMore, whyBtn),
      verb(3, "What's going on",
        h("figure", { class: "he-quote" },
          h("blockquote", {}, "the height-deviate of the offspring is, on the average, two-thirds of the height-deviate of its mid-parentage."),
          h("figcaption", {}, "Galton, 1886, page 252")),
        h("p", {}, "Galton called it regression towards mediocrity. Today it's called regression to the mean, and it shows up wherever two measurements are related but not perfectly.")));
    // Sits at the foot of the steps, level with the bottom of the model, so the two columns start and end together.
    const wholeLesson = h("a", { class: "btn ghost", href: "#/example" }, icon("play"), "Try the example lesson");
    function setStep(n, focus) {
      exhibitStep = Math.max(exhibitStep, n);
      verbEls.forEach((li, i) => {
        li.className = "verb " + (i < exhibitStep ? "done" : i === exhibitStep ? "active" : "later");
        li.querySelector(".verb-mark").replaceChildren(i < exhibitStep ? icon("check") : String(i + 1));
        li.querySelector(".verb-state").textContent = i < exhibitStep ? " (done)" : i === exhibitStep ? " (now)" : "";
        li.querySelector(".verb-body").hidden = i > exhibitStep;
        li.querySelector(".verb-head").setAttribute("aria-expanded", String(i <= exhibitStep));
      });
      whyBtn.hidden = exhibitStep !== 1;
      if (focus && exhibitStep === 2) wholeLesson.focus({ preventScroll: true });
    }
    setStep(exhibitStep);

    // Two equal ways in: ask about a concept (it opens the build page already searching), or bring a source.
    const askIn = h("input", { type: "search", id: "he-ask", placeholder: "How do vaccines work?", autocomplete: "off", maxlength: 200 });
    const ask = (q) => { session.ask = q; session.mode = "search"; location.hash = "#/make"; };
    const el = h("section", { class: "home-exhibit", "aria-labelledby": "home-title" },
      h("div", { class: "he-intro" },
        h("h1", { id: "home-title" }, "See how complex ideas work"),
        h("p", { class: "lead" }, "Ask about any concept, or bring a paper or article. OpenLemma teaches each idea on a live model you can move, with every quote checked against its source.")),
      h("div", { class: "he-ways" },
        h("form", { class: "he-ask", role: "search", onsubmit: (e) => { e.preventDefault(); const q = askIn.value.trim(); if (q) ask(q); else askIn.focus(); } },
          h("label", { for: "he-ask" }, "What do you want to understand?"),
          h("div", { class: "he-ask-row" }, askIn, h("button", { type: "submit", class: "primary" }, "Find sources")),
          h("div", { class: "chips", role: "group", "aria-label": "Try a concept" },
            ["Herd immunity", "Bayes' theorem", "Random walks"].map((t) => h("button", { type: "button", class: "chip", onclick: () => ask(t) }, t)))),
        h("div", { class: "he-or" },
          h("span", { class: "he-or-word" }, "or"),
          h("a", { class: "btn", href: "#/make", onclick: () => { session.mode = "bring"; } }, icon("doc"), "Bring a source")),
        h("p", { class: "he-example" },
          h("a", { class: "btn ghost small", href: "#/example" }, icon("play"), "Try the example lesson"),
          h("span", { class: "small" }, "About 10 minutes. No account or key needed."))),
      filmPlayer(),
      homeRecent(),
      h("div", { class: "he-try" },
        h("h2", { class: "he-try-title" }, "Try it yourself"),
        h("div", { class: "he-verbs" }, verbs),
        h("p", { class: "he-try-foot" }, wholeLesson),
        stage));

    exampleLesson().then((lesson) => {
      const c = lesson.concepts.find((x) => x.id === "regression_line");
      if (!c || !el.isConnected) return;
      // The two numbers the Notice step compares sit side by side, ahead of the expected height.
      const named = (o) => (NOTICED.includes(o.id) ? NOTICED.indexOf(o.id) : NOTICED.length);
      const model = Object.assign({}, c.model, { controls: c.model.controls.filter((k) => k.id === "mp"), outputs: [...c.model.outputs].sort((a, b) => named(a) - named(b)) });
      const k = model.controls[0];
      let values = { mp: 72, ratio: SHARE };
      const seen = { above: false, below: false };
      const vizBox = h("div", { class: "viz-box" });
      const view = new M.ModelView(vizBox, model);
      view.trailsOn = true;  // the home concept always leaves a trail; the learner's saved choice is untouched
      const outs = h("dl", { class: "outputs" });
      const valueEl = h("output", { for: "he-mp", class: "ctl-value" });
      const input = h("input", { type: "range", id: "he-mp", min: k.min, max: k.max, step: k.step, value: values.mp });
      const playBtn = h("button", { type: "button", class: "play", "aria-label": `Play ${k.label} through its range`, onclick: () => { stopDemo(); sweep(); } }, icon("play"), "Play");
      function render(user) {
        const env = view.update(values) || {};
        input.value = values.mp;
        input.style.setProperty("--fill", `${((values.mp - k.min) / (k.max - k.min)) * 100}%`);
        valueEl.textContent = M.fmt(values.mp, 2, 1, k.unit);
        pin(deck.firstChild, "1", exhibitStep === 0);
        outs.replaceChildren(...model.outputs.map((o, i) => { const noticed = NOTICED.includes(o.id); return h("div", { class: "out" + (exhibitStep === 1 && noticed ? " hl" : ""), style: `--k:var(--model-${(o.color ?? i) % 8})`,
          "data-pin": exhibitStep >= 1 && noticed ? "2" : null, "data-pin-state": exhibitStep > 1 && noticed ? "said" : null },
          h("dt", {}, h("span", { class: "key", "aria-hidden": "true" }), o.label), h("dd", {}, M.fmt(env[o.id], o.decimals ?? 2, 1, o.unit || ""))); }));
        if (!user) return;
        const lead = values.mp - MEAN;
        if (lead >= 2) seen.above = true;
        if (lead <= -2) seen.below = true;
        if (Math.abs(lead) >= 2) setStep(1);
        if (exhibitStep >= 1) {
          const side = lead >= 0 ? "above" : "below";
          noticeLine.replaceChildren(h("b", {}, `Parents ${M.fmt(Math.abs(lead), 1, 1, " in")} ${side} average.`), " ",
            h("b", {}, `Their children: ${M.fmt(Math.abs(env.child_dev), 1, 1, " in")} ${side}.`));
          noticeMore.textContent = seen.above && seen.below
            ? "Either way, children land closer to the average than their parents. Short parents' children are pulled up towards the middle too."
            : lead >= 0 ? "Tall parents have tall children, but less tall. Now try short parents." : "Short parents have short children, but less short. Now try tall parents.";
          if (seen.above && seen.below) setStep(2);
        }
      }
      // Attract mode: a slow sweep until someone touches the concept. Off under reduced motion.
      let demo = null, onscreen = true;
      if (typeof IntersectionObserver !== "undefined") {
        const io = new IntersectionObserver(([e]) => { onscreen = e.isIntersecting; });
        io.observe(stage);
        cleanups.push(() => io.disconnect());
      }
      function stopDemo() {
        if (demo) cancelAnimationFrame(demo);
        demo = null;
        playBtn.disabled = false;
      }
      function startDemo() {
        if (M.reduceMotion()) return;
        const t0 = performance.now();
        const tick = (t) => {
          if (!el.isConnected) return stopDemo();
          if (!document.hidden && onscreen) {
            values = Object.assign({}, values, { mp: MEAN + 4.75 * Math.cos(((t - t0) / 9000) * 2 * Math.PI) });
            render(false);
          }
          demo = requestAnimationFrame(tick);
        };
        demo = requestAnimationFrame(tick);
      }
      function sweep() {
        playBtn.disabled = true;
        const from = values.mp, legs = [[from, k.max], [k.max, k.min], [k.min, MEAN + 4]];
        let leg = 0, t0 = performance.now();
        if (M.reduceMotion()) { values = Object.assign({}, values, { mp: k.min }); render(true); values = Object.assign({}, values, { mp: k.max }); render(true); playBtn.disabled = false; return; }
        const tick = (t) => {
          if (!el.isConnected || !playBtn.disabled) return;
          const [a, b] = legs[leg], dur = Math.abs(b - a) * 220, f = dur ? Math.min(1, (t - t0) / dur) : 1;
          const e = f < 0.5 ? 4 * f * f * f : 1 - Math.pow(-2 * f + 2, 3) / 2;
          values = Object.assign({}, values, { mp: a + (b - a) * e });
          render(true);
          if (f >= 1) { leg++; t0 = t; }
          if (leg < legs.length) requestAnimationFrame(tick); else playBtn.disabled = false;
        };
        requestAnimationFrame(tick);
      }
      const take = () => { if (demo) stopDemo(); };
      input.addEventListener("pointerdown", take);
      input.addEventListener("keydown", take);
      input.addEventListener("input", () => { take(); playBtn.disabled = false; values = Object.assign({}, values, { mp: +input.value }); render(true); });
      const pin = (n, num, now) => { n.dataset.pin = num; if (now) delete n.dataset.pinState; else n.dataset.pinState = "said"; };
      const deck = h("div", { class: "controls", role: "group", "aria-label": "Controls" },
        h("div", { class: "ctl", style: `--k:var(--model-${(k.color ?? 0) % 8})` },
          h("label", { for: "he-mp" }, h("span", { class: "key", "aria-hidden": "true" }), "Parents' average height"), valueEl, input, playBtn));
      stage.replaceChildren(
        h("div", { class: "model-head" },
          h("p", { class: "he-from" }, lesson.source.title),
          h("span", { class: "tag", title: model.note }, "Teaching model")),
        h("div", { class: "he-viz" }, vizBox), outs, deck,
        h("p", { class: "model-note" }, model.note));
      stage.removeAttribute("aria-busy");
      render(exhibitStep > 0);
      if (exhibitStep === 0) startDemo();
      cleanups.push(() => { stopDemo(); view.destroy(); });
    }).catch(() => {
      stage.replaceChildren(h("p", { class: "muted" }, "The example model couldn't load. You can still ask about a concept at the top of the page."));
      stage.removeAttribute("aria-busy");
    });
    return el;
  }


  /* From paper to lesson: one scroll-scrubbed sequence. The page of the paper is marked up, each marked
     idea grows out of it into a numbered concept, then the page steps back and the concepts stand.
     Without JavaScript, or with reduced motion, it is a static figure beside the four steps. */
  const HALL_STEPS = [
    ["Ask, or bring a source", "A concept you want to understand, or a paper, article or chapter you already have. You say who the lesson is for."],
    ["OpenLemma finds the ideas", "For a concept, it suggests encyclopedias, textbooks and papers to teach from. It reads the sources and drafts an outline you can edit before anything is built."],
    ["Each idea gets a live model", "A model you can move, checked before you see it, with the sources' own words quoted and verified."],
    ["Learn it, then keep it", "Start while later concepts are still building. The finished lesson is saved in your Library, and you can download it as one file that works offline."],
  ];
  const MINI = {
    bars: '<rect x="8" y="30" width="14" height="26"/><rect x="29" y="18" width="14" height="38" class="m1"/><rect x="50" y="24" width="14" height="32" class="m2"/>',
    curves: '<path d="M6 58L74 6" class="dash"/><path d="M6 46L74 18" class="m0"/><circle cx="52" cy="27" r="5" class="dot"/>',
    sampling: [[12,48],[18,40],[24,44],[28,34],[33,38],[38,30],[42,33],[47,26],[52,28],[56,21],[61,24],[66,16],[20,50],[45,36],[58,30],[30,42],[64,20],[36,26]]
      .map(([x, y], i) => `<circle cx="${x}" cy="${y}" r="2.6" class="${i % 5 === 0 ? "m1" : "m0"}"/>`).join(""),
  };
  function hallSection() {
    const M = window.LemmaModel;
    const stepEls = HALL_STEPS.map(([t, d], i) => h("li", { class: "hs-step" },
      h("span", { class: "plate", "aria-hidden": "true" }, String(i + 1)),
      h("div", {}, h("h3", {}, t), h("p", {}, d))));
    const lines = Array.from({ length: 6 }, (_, i) => h("span", { class: "hp-line" + ([1, 3, 5].includes(i) ? " idea" : "") }));
    const ideas = lines.filter((l) => l.classList.contains("idea"));
    const fallback = [["bars", "One number for two parents"], ["curves", "Children are two-thirds as unusual"], ["sampling", "Where the regression comes from"]];
    const cards = fallback.map(([type, title], i) => {
      const art = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      art.setAttribute("viewBox", "0 0 80 62");
      art.setAttribute("class", "hx-art");
      art.innerHTML = MINI[type] || MINI.curves;
      return h("div", { class: "hx-card" },
        h("div", { class: "hx-top" }, h("span", { class: "plate" }, String(i + 1)), h("span", { class: "hx-title" }, title)),
        art, h("div", { class: "hx-deck" }, h("span", { class: "hx-thumb", style: `--at:${[38, 72, 55][i]}%` })));
    });
    const paper = h("div", { class: "hp-paper" },
      h("p", { class: "hp-title" }, "Regression towards Mediocrity in Hereditary Stature"),
      h("p", { class: "hp-by" }, "Francis Galton, 1886"), h("div", { class: "hp-lines" }, lines));
    const art = h("div", { class: "hall-art", "aria-hidden": "true" }, paper, h("div", { class: "hall-cards" }, cards));
    const sec = h("section", { class: "paper-hall", "aria-labelledby": "hall-title" },
      h("div", { class: "hall-pin" },
        h("div", { class: "hall-copy" },
          h("h2", { id: "hall-title" }, "How OpenLemma teaches a concept"),
          h("ol", { class: "hall-steps" }, stepEls)),
        art));
    exampleLesson().then((lesson) => {
      lesson.concepts.slice(0, 3).forEach((c, i) => { cards[i].querySelector(".hx-title").textContent = c.title; });
      // Real lines from the paper: a primer quote before each concept's own quote, which is the marked idea.
      const clip = (q) => { const w = String(q || "").split(/\s+/); return w.length > 16 ? w.slice(0, 16).join(" ") + " …" : w.join(" "); };
      const context = (lesson.primer || []).map((pg) => pg.quote).filter(Boolean);
      lines.forEach((l, i) => { l.textContent = clip(i % 2 ? (lesson.concepts[(i - 1) / 2] || {}).understand?.quote : context[i / 2] || context[0]); });
      measure?.();
      paper.querySelector(".hp-title").textContent = lesson.source.title;
      paper.querySelector(".hp-by").textContent = `${lesson.source.authors}, ${lesson.source.year}`;
    }).catch(() => {});
    if (M.reduceMotion() || typeof requestAnimationFrame === "undefined" || typeof IntersectionObserver === "undefined") return sec;

    // It plays by itself, once, when it comes into view, and never touches the page's scroll.
    sec.classList.add("is-live");
    const DURATION = 5600;
    const clamp = (x) => Math.max(0, Math.min(1, x));
    const ease = (x) => 1 - Math.pow(1 - x, 3);
    // Where each concept starts: centred on its marked line, measured untransformed (offsets ignore transforms).
    const offsetIn = (node, ancestor) => { let x = 0, y = 0; for (let n = node; n && n !== ancestor; n = n.offsetParent) { x += n.offsetLeft; y += n.offsetTop; } return [x, y]; };
    function measure() {
      cards.forEach((card, i) => {
        const [lx, ly] = offsetIn(ideas[i], art), [cx, cy] = offsetIn(card, art);
        card.style.setProperty("--dx", `${lx + ideas[i].offsetWidth / 2 - (cx + card.offsetWidth / 2)}px`);
        card.style.setProperty("--dy", `${ly + ideas[i].offsetHeight / 2 - (cy + card.offsetHeight / 2)}px`);
      });
    }
    let lastStep = -1;
    function show(p) {
      art.style.setProperty("--hl", ease(clamp((p - 0.12) / 0.18)).toFixed(3));
      art.style.setProperty("--back", ease(clamp((p - 0.84) / 0.14)).toFixed(3));
      cards.forEach((card, i) => card.style.setProperty("--t", ease(clamp((p - 0.36 - i * 0.08) / 0.22)).toFixed(3)));
      const step = p < 0.1 ? 0 : p < 0.34 ? 1 : p < 0.8 ? 2 : 3;
      if (step !== lastStep) {
        lastStep = step;
        stepEls.forEach((li, i) => li.className = "hs-step" + (i < step ? " done" : i === step ? " now" : ""));
        art.dataset.step = step;
      }
    }
    let raf = 0;
    // Replay keeps its place while the figure plays (hidden, not removed), so the figure's card never changes height.
    const replay = h("button", { type: "button", class: "ghost small hall-replay is-waiting", onclick: () => play() }, icon("refresh"), "Replay");
    const waiting = () => replay.classList.contains("is-waiting");
    sec.querySelector(".hall-copy").append(replay);
    function play() {
      cancelAnimationFrame(raf);
      replay.classList.add("is-waiting");
      measure();
      const t0 = performance.now();
      const tick = (t) => {
        if (!sec.isConnected) return;
        const p = clamp((t - t0) / DURATION);
        show(p);
        if (p < 1) raf = requestAnimationFrame(tick); else replay.classList.remove("is-waiting");
      };
      raf = requestAnimationFrame(tick);
    }
    show(0);
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { io.disconnect(); play(); } }, { threshold: 0.45 });
    const onResize = () => { if (waiting() && raf) measure(); };
    // Attach after view() has mounted the page: it runs the previous screen's cleanups first.
    requestAnimationFrame(() => {
      if (!sec.isConnected) return;
      io.observe(art);
      addEventListener("resize", onResize);
      cleanups.push(() => { io.disconnect(); removeEventListener("resize", onResize); cancelAnimationFrame(raf); });
      measure();
    });
    if (document.fonts) document.fonts.ready.then(() => sec.isConnected && measure());
    return sec;
  }

  /* The gallery: finished lessons anyone can open, each led by one of its own models, drawn live at rest. */
  const TAB_INKS = ["violet", "green", "ochre", "blue"];  // the lesson's concept tabs, in the same order
  let galleryP = null;
  const galleryItems = () => (galleryP = galleryP || api("/api/gallery").catch((e) => { galleryP = null; throw e; }));
  const shortAuthors = (a) => {
    const names = String(a || "").split(/,\s*/).filter((n) => n && n !== "et al.");
    return names.length > 2 || /et al/.test(a || "") ? `${names[0]} et al.` : names.join(" and ");
  };
  // `pick` (slugs, in order) gives the home page's model wall: the model, the field and a short title only.
  // Without it, the Gallery page: every lesson, each tile also carrying its source and concept count.
  // `onTiles` gets the tiles each time they land (again after "Try again"), so the Gallery page can filter them.
  function galleryList(level, pick, onTiles) {
    const M = window.LemmaModel;
    // Until the list arrives, quiet tiles of the same shape hold the space, so nothing jumps when it lands.
    const skeleton = () => Array.from({ length: pick ? pick.length : 6 }, () => h("li", { class: "gal-item gal-skel", "aria-hidden": "true" },
      h("div", { class: "gal-plate" }), h("span", { class: "gal-skel-line" }), h("span", { class: "gal-skel-line is-mid" }), pick ? null : h("span", { class: "gal-skel-line is-short" })));
    const list = h("ul", { class: "gallery" + (pick ? " gallery-wall" : ""), "aria-busy": "true" },
      h("li", { class: "sr-only" }, "Opening the gallery…"), ...skeleton());
    const load = () => galleryItems().then((all) => {
      const views = [];
      const items = pick ? pick.map((slug) => all.find((it) => it.slug === slug)).filter(Boolean) : all;
      list.replaceChildren(...items.map((it) => {
        const plate = h("div", { class: "gal-plate", "aria-hidden": "true" });
        plate.dataset.slug = it.slug;
        views.push([plate, it.cover]);
        if (pick) return h("li", { class: "gal-item" },
          plate,
          h("p", { class: "gal-field" }, it.field),
          h(level, { class: "gal-title" }, h("a", { href: `#/gallery/${it.slug}`, title: it.title }, it.title.split(":")[0])));
        const by = [shortAuthors(it.source.authors), it.source.year].filter(Boolean).join(", ");
        const li = h("li", { class: "gal-item" },
          plate,
          h(level, { class: "gal-title" }, h("a", { href: `#/gallery/${it.slug}` }, it.title)),
          h("p", { class: "gal-paper" }, h("cite", {}, it.source.title), by ? h("span", {}, by) : null),
          h("p", { class: "gal-meta" }, h("span", {}, it.field), h("span", { class: "gal-count" }, `${it.concepts.length} concepts`)));
        li.dataset.slug = it.slug;
        li.dataset.find = fold([it.title, it.field, it.source.title, it.source.authors, it.source.year, ...it.concepts].join(" "));
        return li;
      }));
      list.removeAttribute("aria-busy");
      // Draw each model as it comes into view; drawing them all at once would hold up the page.
      const draw = (plate, cover) => {
        if (plate.dataset.drawn) return;
        plate.dataset.drawn = "1";
        if (!cover.model) {  // a lesson taught without a model shows the source's own words
          if (cover.quote) {
            plate.classList.add("gal-quote-plate");
            plate.append(h("figure", { class: "gal-quote" + (cover.quote.split(" ").length <= 16 ? " is-short" : "") },
              h("span", { class: "gal-mark" }, "“"), h("blockquote", {}, cover.quote), cover.quote_author ? h("figcaption", {}, `— ${cover.quote_author}`) : null));
          } else plate.append(h("div", { class: "gal-reading" }, h("p", {}, cover.title), h("p", { class: "small" }, cover.idea)));
          return;
        }
        const box = h("div", { class: "viz-box" });
        plate.append(box);
        const view = new M.ModelView(box, cover.model);
        view.trailsOn = false;
        view.update(Object.assign(M.defaults(cover.model), cover.values || {}));
        cleanups.push(() => view.destroy());
        // A table model taller than its plate is shrunk to fit whole, rather than cut off at the plate's edge.
        const table = box.querySelector(".table-scroll");
        if (table && typeof ResizeObserver !== "undefined") {
          const fit = new ResizeObserver(() => {
            table.style.zoom = "";
            const k = box.clientHeight / table.scrollHeight;
            if (k < 1) table.style.zoom = Math.max(k, 0.5).toFixed(3);
          });
          fit.observe(box);
          cleanups.push(() => fit.disconnect());
        }
      };
      if (typeof IntersectionObserver === "undefined") views.forEach(([pl, c]) => draw(pl, c));
      else {
        const io = new IntersectionObserver((entries) => entries.forEach((e) => {
          if (!e.isIntersecting) return;
          io.unobserve(e.target);
          const v = views.find(([pl]) => pl === e.target);
          if (v) draw(...v);
        }), { rootMargin: "200px 0px" });
        views.forEach(([pl]) => io.observe(pl));
        cleanups.push(() => io.disconnect());
      }
      if (onTiles) onTiles([...list.children]);
    }).catch(() => {
      list.removeAttribute("aria-busy");
      const again = h("button", { type: "button", onclick: () => { list.setAttribute("aria-busy", "true"); list.replaceChildren(h("li", { class: "sr-only" }, "Opening the gallery…"), ...skeleton()); load(); } }, icon("refresh"), "Try again");
      list.replaceChildren(h("li", { class: "gal-error", role: "alert" }, h("p", {}, "The gallery couldn't load. Check your connection, then try again."), again));
    });
    load();
    return list;
  }
  const GALLERY_LEAD = "Finished visual lessons on complex ideas, from how attention reads every word at once to how ice can lock a planet in the cold. Each is taught from real sources you can check, with no account or key.";
  const HOME_WALL = ["attention-2017", "wuhan-2020", "wave-interference", "mendel-1866", "ice-albedo-feedback", "opinion-dynamics-2002"];
  function gallerySection() {
    const all = h("a", { class: "btn gal-all", href: "#/gallery" }, "See all lessons", icon("next"));
    galleryItems().then((items) => { all.firstChild.textContent = `See all ${items.length} lessons`; }).catch(() => {});
    return h("section", { class: "gallery-sec", "aria-labelledby": "gallery-title" },
      h("div", { class: "gal-head" }, h("h2", { id: "gallery-title" }, "Lessons to explore"), h("p", { class: "lead" }, "Finished lessons across subjects. Open one, no account or key needed.")),
      galleryList("h3", HOME_WALL),
      h("p", { class: "gal-more" }, all));
  }
  // Lower case without accents, so "poincare" finds "Poincaré".
  const fold = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  let galleryReturn = "";  // the lesson last opened from the Gallery, so Back lands on its tile
  function showGallery() {
    const q0 = new URLSearchParams(location.hash.split("?")[1] || "").get("q") || "";
    const findIn = h("input", { type: "search", id: "gal-find", value: q0, placeholder: "Topic, field, author or year", autocomplete: "off", spellcheck: "false", maxlength: 80 });
    const count = h("p", { class: "gal-count-line", "aria-live": "polite" });
    const none = h("div", { class: "gal-none", hidden: "" });
    let tiles = [];
    const back = galleryReturn;
    galleryReturn = "";
    const list = galleryList("h2", null, (lis) => {
      tiles = lis.filter((li) => li.dataset.find);
      apply(true);
      const tile = back && tiles.find((li) => li.dataset.slug === back && !li.hidden);
      if (tile) { tile.scrollIntoView({ block: "center" }); tile.querySelector("a").focus({ preventScroll: true }); }
    });
    const apply = (keepHash) => {
      const q = findIn.value.trim();
      const words = fold(q).split(/\s+/).filter(Boolean);
      let shown = 0;
      tiles.forEach((li) => { const hit = words.every((w) => li.dataset.find.includes(w)); li.hidden = !hit; shown += hit; });
      if (tiles.length) count.textContent = words.length ? `${shown} of ${tiles.length} lessons` : `${tiles.length} lessons`;
      none.hidden = !(tiles.length && words.length && !shown);
      if (!none.hidden) none.replaceChildren(h("p", {}, `No lesson matches “${q}”.`),
        h("button", { type: "button", class: "ghost", onclick: () => { findIn.value = ""; apply(); findIn.focus(); } }, icon("cross"), "Clear the search"));
      if (!keepHash) history.replaceState(null, "", q ? `#/gallery?q=${encodeURIComponent(q)}` : "#/gallery");
    };
    findIn.addEventListener("input", () => apply());
    findIn.addEventListener("keydown", (e) => { if (e.key === "Escape" && findIn.value) { e.preventDefault(); findIn.value = ""; apply(); } });
    setTitle("Gallery");
    view(h("section", { class: "gallery-sec gallery-page", "aria-labelledby": "gallery-title" },
      h("div", { class: "gal-page-head" },
        h("div", { class: "gal-head" }, h("h1", { id: "gallery-title" }, "Gallery"), h("p", { class: "lead" }, GALLERY_LEAD)),
        h("form", { class: "gal-find", role: "search", onsubmit: (e) => { e.preventDefault(); findIn.blur(); } },
          h("label", { for: "gal-find" }, "Find a lesson"),
          h("div", { class: "gal-find-row" }, icon("search"), findIn),
          count)),
      list, none));
  }
  async function openGallery(slug) { galleryReturn = slug; try { openLesson(await api(`/api/gallery/${slug}`)); } catch (err) { showHome(err.message); } }

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
  function findPanel() {
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
        // A sign-in provider (ChatGPT, on your own computer only) has no key to speak of.
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

  function loadRecent(recent) {
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

  function showHome(msg) {
    const was = pageOf(location.hash);
    setHash("");
    setTitle("");
    view(msg ? errorBox(msg, null, null, was) : null, homeExhibit(), hallSection(), gallerySection());
  }

  /* A returning learner's fast path: the build panel alone, no intro to scroll past. */
  function showMake() {
    setHash("#/make");
    setTitle("New lesson");
    const { form, results, recent } = findPanel();
    view(h("section", {},
      h("h1", {}, "What do you want to understand?"),
      h("p", { class: "lead" }, "Ask about a concept, or bring your own papers, articles or chapters, up to 10 links and files. OpenLemma turns them into one short lesson, with a live model for each idea."),
      form, results, recent));
    loadRecent(recent);
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
  /* Connect an AI provider: shown the first time an AI step is needed, then the flow carries on. */
  function showConnect(then) {
    setTitle("Connect an AI provider");
    view(h("section", { class: "panel connect", "aria-labelledby": "connect-title" },
      h("h1", { id: "connect-title" }, "Connect an AI provider"),
      h("p", { class: "lead" }, "OpenLemma works out what to look up and reads your sources with an AI provider you choose, using your own key. Pick one and paste its key. OpenLemma carries on as soon as the key works."),
      keyForm(then, { compact: true }),
      h("div", { class: "actions" }, h("button", { class: "ghost", onclick: () => showMake() }, "Back"))));
  }

  // The outline's tags, in plain words: each concept's role, and how it is shown (lesson.py's OUTLINE_VISUALS).
  const ROLE_WORDS = { prerequisite: "Background", core: "Core idea", contribution: "Main result" };
  const VISUAL_WORDS = { curves: "Graph", bars: "Bar chart", table: "Table", agents: "Simulation", network: "Network", causal: "Cause and effect",
    sampling: "Sampling", geometry: "Diagram", none: "Reading only" };

  function showOutline() {
    setHash(session.requestId ? `#/request/${session.requestId}` : "#/outline");
    setTitle("Review the outline");
    const o = session.outline;
    const list = h("ol", { class: "outline-list" });
    const removedBox = h("div");
    const buildBtn = h("button", { class: "primary", onclick: startBuild });
    // What the lesson builds on (its question's answer, or the sources the learner brought), and where each piece is taught.
    const buildsOn = h("section", { class: "bo-card", "aria-labelledby": "builds-on-title", hidden: !(o.subjects || []).length });
    const toAdd = new Set();  // assumed subjects the learner ticked, added together with one remake of the outline
    async function addSources(btn) {
      busy(btn, true);
      try { await api(`/api/requests/${session.requestId}/add`, { titles: [...toAdd] }); showRequest(session.requestId); }
      catch (e) { busy(btn, false); buildsOn.append(errorBox(e.message)); }
    }
    function drawBuildsOn() {
      if (!(o.subjects || []).length) return;
      const taught = new Map(o.concepts.map((c, i) => [c.subject, c.known ? null : i + 1]).filter(([s]) => s));
      const known = new Set(o.concepts.filter((c) => c.known && c.subject).map((c) => c.subject));
      const assumed = new Set([...(o.assumes || []), ...known, ...(o.subjects || []).filter((s) => s.relation === null).map((s) => s.title)]);
      // An assumed subject whose own article search found, and no chosen source covers, can be added.
      const addable = new Set((o.subjects || []).filter((s) => s.url && !s.source && assumed.has(s.title)).map((s) => s.title));
      const n = toAdd.size;
      const addBtn = h("button", { type: "button", class: "small", disabled: !n, onclick: (e) => addSources(e.currentTarget) },
        icon("plus"), n ? `Add ${n} ${n === 1 ? "source" : "sources"} and remake the outline` : "Tick the ones to add");
      const tick = (t) => h("label", { class: "bo-pick" },
        h("input", { type: "checkbox", checked: toAdd.has(t), onchange: (e) => { e.target.checked ? toAdd.add(t) : toAdd.delete(t); drawBuildsOn(); buildsOn.querySelector(`input[value="${CSS.escape(t)}"]`)?.focus(); }, value: t }), t);
      const groups = [
        ["Covered", "", (o.subjects || []).filter((s) => taught.get(s.title)).map((s) => `${s.title}: concept ${taught.get(s.title)}`)],
        ["Assumed", addable.size ? "The lesson takes these as known. Tick the ones you'd like it to teach from their own articles. Adding remakes the outline; your edits to this one are lost." : "The lesson takes these as known.",
          [...assumed].map((t) => addable.has(t) ? tick(t) : t), addable.size ? addBtn : null],
        ["Later", "Not in this lesson.", (o.subjects || []).filter((s) => !taught.get(s.title) && !assumed.has(s.title)).map((s) => s.title)],
      ].filter(([, , items]) => items.length);
      buildsOn.replaceChildren(h("h2", { id: "builds-on-title" }, "What this lesson builds on"),
        ...groups.map(([name, note, items, after]) => h("div", { class: "bo-group" }, h("h3", {}, name), note ? h("p", { class: "muted small" }, note) : null,
          h("ul", {}, items.map((x) => h("li", {}, x))), after ? h("div", { class: "bo-add" }, after) : null)));
    }
    // A concept relies on the ones it needs and the one whose model it reuses; it must come after them.
    const reliesOn = (c) => [...(Array.isArray(c.needs) ? c.needs : []), ...(c.builds_on ? [c.builds_on] : [])];
    const reliesOnAt = (a, b) => reliesOn(a).includes(b.id);  // a can't move above b
    function draw(focusSel) {
      const cs = o.concepts;
      list.replaceChildren(...cs.map((c, i) => h("li", { class: "outline-item" + (c.known ? " known" : "") },
        h("div", {},
          h("div", { class: "oi-title" }, h("strong", {}, c.title), h("span", { class: "tag" }, ROLE_WORDS[c.role || "core"] || c.role), h("span", { class: "tag" }, VISUAL_WORDS[c.visual] || c.visual),
            c.hard ? h("span", { class: "tag" }, "Has a quiz") : null,
            (() => { const b = cs.findIndex((x) => x.id === c.builds_on); return b >= 0 && b < i ? h("span", { class: "tag" }, `Uses concept ${b + 1}'s model`) : null; })(),
            (() => { const n = cs.map((x, j) => (Array.isArray(c.needs) && c.needs.includes(x.id) ? j + 1 : 0)).filter(Boolean); return n.length ? h("span", { class: "tag" }, `Comes after ${n.length > 1 ? `${n.slice(0, -1).join(", ")} and ${n[n.length - 1]}` : n[0]}`) : null; })()),
          h("p", { class: "oi-idea" }, c.idea),
          c.known ? h("p", { class: "muted small" }, "You know this one: it will be skipped.") : null),
        h("div", { class: "oi-btns" },
          h("button", { class: "small", "data-k": `up-${i}`, "aria-label": `Move “${c.title}” up`, disabled: i === 0 || reliesOnAt(c, cs[i - 1]), title: i > 0 && reliesOnAt(c, cs[i - 1]) ? `It relies on “${cs[i - 1].title}”, so it comes after it` : null, onclick: () => { [cs[i - 1], cs[i]] = [cs[i], cs[i - 1]]; draw(`[data-k="up-${i - 1}"]`); } }, icon("up")),
          h("button", { class: "small", "data-k": `down-${i}`, "aria-label": `Move “${c.title}” down`, disabled: i === cs.length - 1 || reliesOnAt(cs[i + 1], c), title: i < cs.length - 1 && reliesOnAt(cs[i + 1], c) ? `“${cs[i + 1].title}” relies on it, so it comes first` : null, onclick: () => { [cs[i + 1], cs[i]] = [cs[i], cs[i + 1]]; draw(`[data-k="down-${i + 1}"]`); } }, icon("down")),
          h("button", { class: "small", "aria-pressed": c.known ? "true" : "false", "aria-label": `I know “${c.title}”`, onclick: () => { c.known = !c.known; draw(); } }, c.known ? icon("check") : null, "I know this"),
          h("button", { class: "small danger", "aria-label": `Remove “${c.title}”`, onclick: () => { session.removed.push(cs.splice(i, 1)[0]); draw(); } }, "Remove")))));
      removedBox.replaceChildren(session.removed.length ? h("div", { class: "removed" }, h("h3", {}, "Removed"), h("ul", {}, session.removed.map((c, i) => h("li", {}, c.title, " ", h("button", { class: "small", "aria-label": `Restore “${c.title}”`, onclick: () => {
            // Back in before the first concept that relies on it, or at the end.
            const r = session.removed.splice(i, 1)[0], at = o.concepts.findIndex((x) => reliesOnAt(x, r));
            o.concepts.splice(at < 0 ? o.concepts.length : at, 0, r); draw();
          } }, "Restore"))))) : "");
      drawBuildsOn();
      const n = cs.filter((c) => !c.known).length;
      buildBtn.textContent = `Build ${n} concept${n === 1 ? "" : "s"}`;
      buildBtn.disabled = n === 0;
      if (focusSel) { const b = list.querySelector(focusSel); if (b && !b.disabled) b.focus(); }
    }
    draw();
    view(h("section", {},
      h("h1", {}, o.title),
      ...(session.requestWarnings || []).map((w) => h("p", { class: "note" }, w)),
      h("p", { class: "muted" }, [o.source?.title, o.source?.authors, o.source?.year ? `(${o.source.year})` : ""].filter(Boolean).join(" · ")),
      h("p", { style: "font-size:19px;max-width:66ch" }, o.summary),
      (o.primer || []).length ? h("details", { class: "advanced" },
        h("summary", {}, `The idea in brief: ${plural(o.primer.length, "page")} read before the first concept`),
        ...o.primer.map((pg) => h("div", {}, h("h3", {}, pg.heading), h("p", { style: "max-width:66ch;white-space:pre-line" }, pg.body)))) : null,
      o.question ? h("p", { class: "muted" }, `Your question: “${o.question}”`) : null,
      buildsOn,
      h("p", { class: "note" }, `Here's the proposed outline, from ${o.question ? "what it builds on to the answer" : (o.subjects || []).length ? "what it builds on to the main result" : "background to the main result"}. Reorder the concepts, remove any, or mark ones you already know.`),
      list, removedBox,
      h("div", { class: "actions" }, buildBtn,
        session.requestId ? h("button", { class: "ghost", onclick: async () => { await api(`/api/requests/${session.requestId}/cancel`, {}); showRequest(session.requestId); } }, "Cancel this lesson") : null,
        h("a", { class: "btn ghost", href: "#/library" }, "Return later"), h("button", { class: "ghost", onclick: () => showHome() }, "Back to home"))));
  }

  /* ------------------------------------------------------------ build */
  async function startBuild() {
    // The outline may have been made in another browser or before the key was removed; the reviewed outline stays in session.
    if (!(status.provider || {}).ok) return showConnect(() => startBuild());
    try { await api(`/api/requests/${session.requestId}/outline`, { outline: session.outline }); showRequest(session.requestId); }
    catch (err) { alertInline(err.message); }
  }

  const STOPPED_TITLES = { error: "This build stopped", interrupted: "This build was interrupted", cancelled: "You cancelled this build" };

  function showRequest(id) {
    session.requestId = id;
    setHash(`#/request/${id}`);
    setTitle("Preparing your lesson");
    const title = h("h1", {}, "Preparing your lesson"), progress = buildProgress(), steps = progress.el, warnings = h("div"), errors = h("div");
    const eta = h("p", { class: "muted", role: "status" }, "Estimating time remaining…");
    const open = h("button", { class: "primary", disabled: true }, "Start the first concept");
    const cancel = h("button", { class: "ghost", onclick: async () => {
      try { await api(`/api/requests/${id}/cancel`, {}); showRequest(id); } catch (e) { errors.replaceChildren(errorBox(e.message)); }
    } }, "Cancel build");
    const retry = h("button", { class: "primary", hidden: true, onclick: async () => {
      const begin = async () => {
        try { await api(`/api/requests/${id}/retry`, {}); showRequest(id); } catch (e) { errors.replaceChildren(errorBox(e.message)); }
      };
      if (!(status.provider || {}).ok) return showConnect(begin);
      await begin();
    } }, "Retry build");
    view(h("section", { class: "panel" }, title,
      h("p", { class: "muted" }, "You can leave this page and come back with this link or from your Library. Finished lessons are saved automatically."),
      eta, steps, warnings, errors, h("div", { class: "actions" }, open, cancel, retry, h("a", { href: "#/library", class: "btn ghost" }, "Library"))));
    const poll = async () => {
      if (location.hash !== `#/request/${id}`) return;
      try {
        const s = await api(`/api/requests/${id}`);
        if (location.hash !== `#/request/${id}`) return;
        if (s.status === "awaiting_outline") {
          session.outline = s.outline || s.result; session.requestWarnings = s.warnings || []; session.removed = []; return showOutline();
        }
        title.textContent = s.status === "running" ? "Building your lesson" : s.status === "done" ? "Your lesson is ready" : STOPPED_TITLES[s.status] || "This build stopped";
        setTitle(title.textContent);
        progress.update(s.steps || [], s.now);
        warnings.replaceChildren(...(s.warnings || []).map((w) => h("p", { class: "note" }, typeof w === "string" ? w : JSON.stringify(w))));
        // A build that stopped with an error can be reported from here, with the build's id.
        errors.replaceChildren(s.error && s.status !== "cancelled" ? errorBox(s.error, null, s.status === "error" && /^[0-9a-f]{12}$/.test(id)
          ? { kind: "build", request_id: id, error_id: (s.error.match(ERROR_ID) || [])[1] } : null) : "");
        eta.textContent = s.status !== "running" ? (s.status === "done" ? "Checked and saved to your library." : "You can retry with the same source selections.")
          : s.eta_seconds ? `About ${Math.max(1, Math.ceil(s.eta_seconds[0] / 60))}–${Math.max(1, Math.ceil(s.eta_seconds[1] / 60))} minutes left. Concepts that need fixing can take longer.` : "Estimating time remaining…";
        open.disabled = !s.lesson?.concepts?.length && s.status !== "done";
        open.textContent = s.status === "done" ? "Open lesson" : "Start the first concept";
        open.onclick = () => openLesson(s.status === "done" ? s.result : s.lesson, s.status === "done" ? { saved: true } : { live: id, request: true });
        cancel.hidden = s.status !== "running";
        retry.hidden = !["error", "cancelled", "interrupted"].includes(s.status);
        if (s.status === "running") pollTimer = setTimeout(poll, 1500);
      } catch (e) {
        errors.replaceChildren(errorBox(e.message), h("button", { class: "small", onclick: poll }, "Reconnect"));
      }
    };
    poll();
  }

  /* ------------------------------------------------------------ learn */
  function openLesson(lesson, opts = {}) {
    view();
    setHash(opts.request ? `#/request/${opts.live}/learn` : lesson.gallery ? `#/gallery/${lesson.gallery.slug}` : lesson.example ? "#/example" : opts.saved ? `#/lesson/${lesson.id}` : "#/learn");
    setTitle(lesson.title || "Lesson");
    const host = h("div", { class: "player-host" });
    main.replaceChildren(host);
    player = LemmaPlayer.mount(host, lesson, {
      onExit: () => showHome(),
      // Library lessons and finished builds are saved already; a built-in lesson can't be saved at all.
      onSave: lesson.example || opts.saved || opts.request ? null : saveLesson,
      saved: !!opts.saved && !opts.preview,
      onDownload: downloadLesson,
      onEdit: lesson.example ? null : (l) => showEditor(l),
      onOwnPaper: lesson.example ? () => showHome() : null,
      onEvent: (name) => { api("/api/event", { name }, "POST", {}).catch(() => {}); },
      feedback: status.user ? lessonFeedback : null,  // signed in only; a downloaded lesson is mounted without it
    });
    if (opts.live) {
      const jobId = opts.live;
      const activePlayer = player;
      const poll = async () => {
        let s;
        try { s = await api(`/api/${opts.request ? "requests" : "jobs"}/${jobId}`); } catch (e) { return; }
        if (player !== activePlayer) return;
        if (s.status === "running") { player.update(s.lesson); pollTimer = setTimeout(poll, 1500); }
        else if (s.status === "done") { session.lesson = s.result; player.update(s.result); }
        else if (["error", "cancelled", "interrupted"].includes(s.status)) {
          if (s.lesson) { const l = Object.assign({}, s.lesson); delete l.plan; player.update(l); }
          alertInline(`${STOPPED_TITLES[s.status] || "This build stopped"}. You can retry it from your Library.${s.status !== "cancelled" && s.error ? ` ${s.error}` : ""}`);
        }
      };
      pollTimer = setTimeout(poll, 1500);
    }
  }

  async function saveLesson(lesson, btn) {
    try {
      await api("/api/lessons", { lesson });
      if (btn) { btn.replaceChildren(icon("check"), "Saved in your library"); btn.disabled = true; }
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

  // The offline file, named after the lesson's title.
  async function exportLesson(lesson) {
    const res = await fetch("api/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lesson }) });
    if (!res.ok) throw new Error((await res.json().catch(() => null))?.error || `Download failed (${res.status}). Try again in a moment.`);
    download(`${slug(lesson.title)}.html`, await res.text());
  }
  async function downloadLesson(lesson) {
    try { await exportLesson(lesson); } catch (err) { alertInline(err.message); }
  }

  /* The film: embedded in the hero, loaded and played only when the visitor presses play. */
  const FILM = { hd: "static/film-v5-1080.mp4", sd: "static/film-v5-720.mp4", poster: "static/film-v5-poster.jpg" };
  function filmPlayer() {
    const video = h("video", { class: "film-video", preload: "none", poster: FILM.poster, playsinline: true, "aria-label": "OpenLemma film, 32 seconds, with music" });
    const status = h("p", { class: "film-status", role: "status" });
    const start = () => {
      if (!video.src) video.src = matchMedia("(max-width: 900px)").matches ? FILM.sd : FILM.hd;
      video.controls = true;
      cover.hidden = after.hidden = true;
      video.play().catch(() => {});  // some browsers refuse; the native controls are there now
    };
    const cover = h("button", { type: "button", class: "film-cover", onclick: start, "aria-label": "Play the 32-second OpenLemma film (with music)" },
      h("span", { class: "film-disc", "aria-hidden": "true" }, icon("play")));
    const after = h("div", { class: "film-after", hidden: true },
      h("p", { class: "film-after-title" }, "Now try it on something you want to understand."),
      h("div", { class: "film-after-actions" },
        h("button", { type: "button", class: "primary", onclick: () => document.getElementById("he-ask")?.focus() }, icon("search"), "Ask about a concept"),
        h("a", { class: "btn", href: "#/make", onclick: () => { session.mode = "bring"; } }, icon("doc"), "Bring a source"),
        h("button", { type: "button", class: "ghost", onclick: () => { video.currentTime = 0; start(); } }, icon("refresh"), "Replay")));
    video.addEventListener("ended", () => { after.hidden = false; after.querySelector("button").focus({ preventScroll: true }); });
    video.addEventListener("error", () => status.replaceChildren("The film couldn't load. ", ext(video.currentSrc || video.src, "Open the video file"), "."));
    cleanups.push(() => { video.pause(); video.removeAttribute("src"); video.load(); });
    return h("figure", { class: "he-film" }, h("div", { class: "film-frame" }, video, cover, after), status);
  }

  async function openExample() { try { openLesson(await api("/api/example")); } catch (err) { showHome(err.message); } }

  /* ------------------------------------------------------------ library */
  /* The account's saved lessons, newest first, beside its builds that haven't finished, each build with its next
     step. Typing finds a lesson once there are enough to look through. Deletes and cancels ask inside the row, and
     anything the server refuses is said in that row. */
  const BUILD_STATES = {
    running: { mark: "running", says: "Building now" },
    awaiting_outline: { mark: "outline", says: "Outline ready to review" },
    error: { mark: "failed", says: "Stopped with an error" },
    interrupted: { mark: "failed", says: "Interrupted when the server stopped" },
    cancelled: { mark: "stopped", says: "Cancelled" },
  };
  const BUILD_ORDER = Object.keys(BUILD_STATES);
  const LIB_FIND_FROM = 7;  // fewer lessons than this fit on one screen, where a search field would only be in the way
  let libraryReturn = "";  // the lesson last opened from the library, so Back lands on its row
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  function when(sec, withTime) {
    const d = new Date(sec * 1000), now = new Date();
    const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const ago = Math.round((day(now) - day(d)) / 864e5);
    const date = ago === 0 ? "today" : ago === 1 ? "yesterday"
      : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
    const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    return h("time", { datetime: d.toISOString() }, withTime && ago < 2 ? `${date} at ${time}` : date);
  }

  /* Ask inside the row: the question, the action in red and a way out. Escape or "Keep" puts the row back. */
  function ask(li, opener, { question, yes, busyText, no, act }) {
    const acts = li.querySelector(".lib-acts");
    li.querySelector(".lib-msg").hidden = true;
    const close = () => { li.classList.remove("is-asking"); box.remove(); acts.hidden = false; opener.focus(); };
    const yesBtn = h("button", { type: "button", class: "small lib-yes", onclick: async () => {
      busy(yesBtn, true); noBtn.disabled = true;
      yesBtn.textContent = busyText;
      await act();
    } }, yes);
    const noBtn = h("button", { type: "button", class: "small ghost", onclick: close }, no);
    const qid = `ask-${li.dataset.key.replace(/\W/g, "")}`;
    const box = h("div", { class: "lib-ask", role: "group", "aria-labelledby": qid, onkeydown: (e) => { if (e.key === "Escape") { e.preventDefault(); close(); } } },
      h("p", { id: qid }, question), h("div", { class: "lib-ask-btns" }, yesBtn, noBtn));
    li.classList.add("is-asking");
    acts.hidden = true;
    li.append(box);
    noBtn.focus();
  }

  function showLibrary() {
    const q0 = new URLSearchParams(location.hash.split("?")[1] || "").get("q") || "";
    const live = h("p", { class: "sr-only", role: "status" });
    const body = h("div", { class: "lib-body", "aria-busy": "true" });
    setTitle("Library");
    view(h("section", { class: "lib", "aria-labelledby": "lib-title" },
      h("div", { class: "lib-head" }, h("h1", { id: "lib-title" }, "Library"),
        h("p", { class: "lead" }, "Every lesson you build is saved here. Download any one as a single file that works offline and sends nothing anywhere.")),
      body, live));
    let lessons = [], builds = [], rows = [], countEl = null, noneEl = null;
    const findIn = h("input", { type: "search", id: "lib-find", value: q0, placeholder: "Title, source or subject", autocomplete: "off", spellcheck: "false", maxlength: 80 });
    const say = (msg) => { live.textContent = ""; setTimeout(() => { live.textContent = msg; }, 60); };

    async function load() {
      const [ls, rs] = await Promise.all([api("/api/lessons"), api("/api/requests")]);
      lessons = ls;
      builds = rs.filter((r) => BUILD_STATES[r.status])
        .sort((a, b) => BUILD_ORDER.indexOf(a.status) - BUILD_ORDER.indexOf(b.status) || (b.created || 0) - (a.created || 0));
    }

    function showMsg(li, text) {
      const msg = li.querySelector(".lib-msg");
      msg.replaceChildren(icon("cross"), h("span", {}, text));
      msg.hidden = false;
    }
    // After the server refuses something, show the row as it is now and say why there.
    async function refuse(key, text) {
      try { await load(); } catch (e) { /* the row stays as it was */ }
      draw();
      const li = body.querySelector(`[data-key="${key}"]`);
      if (!li) return say(text);
      showMsg(li, text);
      (li.querySelector(".lib-acts button, .lib-acts a") || li.querySelector(".lib-open")).focus();
    }
    function focusRow(key, fallbackKey) {
      const li = body.querySelector(`[data-key="${key}"]`) || (fallbackKey && body.querySelector(`[data-key="${fallbackKey}"]`))
        || body.querySelector(".lib-lessons .lib-row:not([hidden])");
      const target = li ? li.querySelector(".lib-open") : main.querySelector("h1");
      target.focus({ preventScroll: !!li });
      if (li) li.scrollIntoView({ block: "nearest" });
    }

    function buildRow(r) {
      const st = BUILD_STATES[r.status], key = `b:${r.id}`, title = r.title || "Lesson in progress";
      const acts = h("div", { class: "lib-acts" });
      const li = h("li", { class: `lib-row lib-build is-${st.mark}`, "data-key": key },
        h("span", { class: "lib-mark", "aria-hidden": "true" }, st.mark === "running" ? null : icon({ outline: "doc", failed: "cross", stopped: "dash" }[st.mark])),
        h("div", { class: "lib-text" },
          h("h3", { class: "lib-title" }, h("a", { class: "lib-open", href: `#/request/${r.id}` }, title)),
          h("p", { class: "lib-meta" }, h("span", { class: "lib-state" }, st.says), r.created ? h("span", {}, "Started ", when(r.created, true)) : null)),
        acts, h("p", { class: "lib-msg", role: "alert", hidden: true }));
      const del = () => h("button", { type: "button", class: "small danger lib-del", "aria-label": `Delete the build “${title}”`, onclick: (e) => ask(li, e.currentTarget, {
        question: "Delete this build? Its sources and progress go with it.", yes: "Delete build", busyText: "Deleting…", no: "Keep it",
        act: async () => {
          try { await api(`/api/requests/${r.id}`, undefined, "DELETE"); } catch (err) { return refuse(key, err.message); }
          const next = li.nextElementSibling?.dataset.key || li.previousElementSibling?.dataset.key;
          await reload();
          focusRow(next);
          say(`Deleted the build “${title}”.`);
        } }) }, "Delete");
      if (r.status === "running") {
        acts.append(h("a", { class: "btn small", href: `#/request/${r.id}` }, "View progress"),
          h("button", { type: "button", class: "small danger lib-del", onclick: (e) => ask(li, e.currentTarget, {
            question: "Cancel this build? Retrying later starts again from reading the sources.", yes: "Cancel build", busyText: "Cancelling…", no: "Keep building",
            act: async () => {
              try { await api(`/api/requests/${r.id}/cancel`, {}); } catch (err) { return refuse(key, err.message); }
              await new Promise((ok) => setTimeout(ok, 600));  // the build stops between steps
              await reload();
              focusRow(key);
              say(`Cancelling “${title}”.`);
            } }) }, "Cancel"));
      } else if (r.status === "awaiting_outline") {
        acts.append(h("a", { class: "btn small", href: `#/request/${r.id}` }, "Review outline"), del());
      } else {
        const retry = h("button", { type: "button", class: "small", onclick: async () => {
          const begin = async () => {
            try { await api(`/api/requests/${r.id}/retry`, {}); showRequest(r.id); }
            catch (err) { if (body.isConnected) refuse(key, err.message); else alertInline(err.message); }
          };
          if (!(status.provider || {}).ok) return showConnect(begin);
          busy(retry, true);
          await begin();
          busy(retry, false);
        } }, icon("refresh"), "Retry build");
        acts.append(retry, del());
        if (r.status === "error" && status.user && /^[0-9a-f]{12}$/.test(r.id)) acts.append(reportRow(li, r.id));
      }
      return li;
    }

    /* "Report this" on a build that stopped with an error: the form opens inside the row, as a question does. */
    function reportRow(li, rid) {
      const btn = h("button", { type: "button", class: "small ghost", onclick: () => {
        const acts = li.querySelector(".lib-acts");
        li.querySelector(".lib-msg").hidden = true;
        const close = () => { li.classList.remove("is-reporting"); panel.remove(); acts.hidden = false; btn.focus(); };
        const sent = (thanks) => { li.classList.remove("is-reporting"); btn.remove(); acts.hidden = false; thanks.focus({ preventScroll: true }); };
        const panel = h("div", { class: "lib-report" }, feedbackForm({ kind: "build", request_id: rid, page: "#/library" }, { variant: "report", onCancel: close, onSent: sent }));
        li.classList.add("is-reporting");
        acts.hidden = true;
        li.append(panel);
        panel.querySelector("textarea").focus();
      } }, icon("flag"), "Report this");
      return btn;
    }

    function lessonRow(it) {
      const key = `l:${it.id}`, title = it.title || "Untitled lesson";
      const fetchLesson = () => api(`/api/lessons/${it.id}`);
      const dlLabel = h("span", {}, "Download");
      const li = h("li", { class: "lib-row lib-lesson", "data-key": key },
        h("div", { class: "lib-text" },
          h("h3", { class: "lib-title" }, h("a", { class: "lib-open", href: `#/lesson/${it.id}`, onclick: () => { libraryReturn = it.id; } }, title)),
          it.source ? h("p", { class: "lib-source" }, it.source) : null,
          h("p", { class: "lib-meta" }, it.category ? h("span", {}, it.category) : null, h("span", { class: "lib-num" }, plural(it.concepts, "concept")), h("span", {}, "Saved ", when(it.saved)))),
        h("div", { class: "lib-acts" },
          h("button", { type: "button", class: "small ghost", "aria-label": `Download “${title}” as one offline file`, onclick: async (e) => {
            const b = e.currentTarget;
            busy(b, true); dlLabel.textContent = "Preparing…"; li.querySelector(".lib-msg").hidden = true;
            try { await exportLesson(await fetchLesson()); say(`Downloaded “${title}”.`); }
            catch (err) { showMsg(li, err.message); }
            busy(b, false); dlLabel.textContent = "Download";
          } }, icon("down"), dlLabel),
          h("button", { type: "button", class: "small ghost", "aria-label": `Edit “${title}”`, onclick: async () => {
            try { showEditor(await fetchLesson()); } catch (err) { showMsg(li, err.message); }
          } }, "Edit"),
          h("button", { type: "button", class: "small danger lib-del", "aria-label": `Delete “${title}”`, onclick: (e) => ask(li, e.currentTarget, {
            question: "Delete this lesson from your library? This can't be undone.", yes: "Delete lesson", busyText: "Deleting…", no: "Keep it",
            act: async () => {
              try { await api(`/api/lessons/${it.id}`, undefined, "DELETE"); } catch (err) { return refuse(key, err.message); }
              const sib = (dir) => { let n = li[dir]; while (n && n.hidden) n = n[dir]; return n?.dataset.key; };
              const next = sib("nextElementSibling"), prev = sib("previousElementSibling");
              await reload();
              focusRow(next, prev);
              say(`Deleted “${title}”.`);
            } }) }, "Delete")),
        h("p", { class: "lib-msg", role: "alert", hidden: true }));
      li.dataset.find = fold([title, it.source, it.category].join(" "));
      return li;
    }

    function apply(keepHash) {
      const q = findIn.value.trim(), words = fold(q).split(/\s+/).filter(Boolean);
      let shown = 0;
      rows.forEach((li) => { const hit = words.every((w) => li.dataset.find.includes(w)); li.hidden = !hit; shown += hit; });
      if (rows[0]?.parentNode) rows[0].parentNode.hidden = !shown;  // no empty white card above "no match"
      if (countEl) countEl.textContent = words.length ? `${shown} of ${plural(rows.length, "lesson")}` : plural(rows.length, "lesson");
      if (noneEl) {
        noneEl.hidden = !(words.length && !shown);
        if (!noneEl.hidden) noneEl.replaceChildren(h("p", {}, `No saved lesson matches “${q}”.`),
          h("button", { type: "button", class: "ghost", onclick: () => { findIn.value = ""; apply(); findIn.focus(); } }, icon("cross"), "Clear the search"));
      }
      if (!keepHash) history.replaceState(null, "", q ? `#/library?q=${encodeURIComponent(q)}` : "#/library");
    }
    findIn.addEventListener("input", () => apply());
    findIn.addEventListener("keydown", (e) => { if (e.key === "Escape" && findIn.value) { e.preventDefault(); findIn.value = ""; apply(); } });

    function lessonsSection() {
      const heading = h("h2", { id: "lib-lessons-title" }, "Saved lessons");
      rows = lessons.map(lessonRow);
      countEl = noneEl = null;
      if (!rows.length) return h("section", { class: "lib-sec lib-lessons", "aria-labelledby": "lib-lessons-title" },
        h("div", { class: "lib-sec-head" }, heading),
        h("p", { class: "lib-wait" }, "A lesson appears here as soon as its build finishes."));
      const many = rows.length >= LIB_FIND_FROM;
      if (many) {
        countEl = h("p", { class: "lib-count-line", "aria-live": "polite" });
        noneEl = h("div", { class: "lib-none", hidden: true });
      } else findIn.value = "";
      return h("section", { class: "lib-sec lib-lessons", "aria-labelledby": "lib-lessons-title" },
        h("div", { class: "lib-sec-head" + (many ? " has-find" : "") }, heading,
          many ? h("form", { class: "lib-find", role: "search", onsubmit: (e) => { e.preventDefault(); findIn.blur(); } },
            h("label", { class: "sr-only", for: "lib-find" }, "Find a saved lesson"),
            h("div", { class: "gal-find-row" }, icon("search"), findIn), countEl) : h("span", { class: "lib-count" }, String(rows.length))),
        h("ul", { class: "lib-list" }, rows), noneEl);
    }

    function draw() {
      // Redrawn in place, so focus stays on the same control of the same row wherever it still exists.
      const at = document.activeElement, atRow = at?.closest?.("[data-key]");
      const keep = atRow && body.contains(atRow) ? [atRow.dataset.key, [...atRow.querySelectorAll("a, button")].indexOf(at)] : null;
      const inFind = at === findIn, caret = inFind ? findIn.selectionStart : 0;
      body.removeAttribute("aria-busy");
      if (!lessons.length && !builds.length) {
        body.replaceChildren(h("div", { class: "lib-empty" },
          h("h2", {}, "No saved lessons yet"),
          h("p", {}, "Ask about a concept or bring a source. OpenLemma builds a short lesson with a live model for each idea, usually within a few minutes, and keeps it here."),
          h("div", { class: "actions" },
            h("a", { class: "btn primary", href: "#/make" }, "New lesson"),
            h("a", { class: "btn ghost", href: "#/example" }, icon("play"), "Try the example lesson"))));
      } else {
        const buildsSec = builds.length ? h("section", { class: "lib-sec lib-builds", "aria-labelledby": "lib-builds-title" },
          h("div", { class: "lib-sec-head" }, h("h2", { id: "lib-builds-title" }, "In progress"), h("span", { class: "lib-count" }, String(builds.length))),
          h("ul", { class: "lib-list" }, builds.map(buildRow))) : null;
        body.replaceChildren(h("div", { class: "lib-grid" + (buildsSec ? "" : " is-solo") }, lessonsSection(), buildsSec));
        apply(true);
      }
      if (keep) {
        const li = body.querySelector(`[data-key="${keep[0]}"]`);
        const el = li && ([...li.querySelectorAll("a, button")][keep[1]] || li.querySelector(".lib-open"));
        if (el) el.focus({ preventScroll: true });
      } else if (inFind && findIn.isConnected) { findIn.focus({ preventScroll: true }); findIn.setSelectionRange(caret, caret); }
      stopPolling();
      if (builds.some((r) => r.status === "running")) pollTimer = setTimeout(poll, 4000);
    }
    const reload = async () => { try { await load(); } catch (e) { /* keep what's shown */ } draw(); };

    // While a build runs, check on it, and redraw only when something changed and no question is open.
    const signature = () => builds.map((r) => r.id + r.status).join() + "|" + lessons.map((l) => l.id).join();
    async function poll() {
      if (!body.isConnected) return;
      const before = signature();
      try { await load(); } catch (e) { pollTimer = setTimeout(poll, 8000); return; }
      if (!body.isConnected) return;
      if (signature() !== before && !body.querySelector(".is-asking, .is-reporting")) draw();
      else pollTimer = setTimeout(poll, 4000);
    }

    (async function first() {
      try { await load(); } catch (err) {
        body.removeAttribute("aria-busy");
        const again = h("button", { type: "button", onclick: () => { body.setAttribute("aria-busy", "true"); first(); } }, icon("refresh"), "Try again");
        body.replaceChildren(h("div", { class: "lib-none", role: "alert" }, h("p", {}, `Your library couldn't load. ${err.message}`), again));
        return;
      }
      if (!body.isConnected) return;
      draw();
      const back = libraryReturn;
      libraryReturn = "";
      const li = back && body.querySelector(`[data-key="l:${back}"]:not([hidden])`);
      if (li) { li.scrollIntoView({ block: "center" }); li.querySelector(".lib-open").focus({ preventScroll: true }); }
    })();
  }

  /* ------------------------------------------------------------ editor */
  const EDIT_FIELDS = [
    ["title", "Title"], ["idea", "Idea"],
    ["understand.explanation", "In plain words"], ["understand.quote", "Quote (must match the source word for word)"], ["understand.quote_where", "Where the quote appears"],
    ["explore.prompt", "Try-it prompt"], ["predict.question", "Use-it question"],
    ["understand.feedback.correct", "Feedback on a right answer"], ["understand.feedback.incorrect", "Feedback on a wrong answer"],
    ["model.note", "Teaching-model note"], ["check.hint", "Check hint (hard concepts only)"], ["check.misconception", "Common mix-up (hard concepts only)"], ["connect.caption", "Equation caption"], ["recap", "In one line"],
  ];
  const getPath = (o, p) => p.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
  const setPath = (o, p, v) => { const ks = p.split("."); const last = ks.pop(); const t = ks.reduce((a, k) => (a[k] ||= {}), o); t[last] = v; };

  function showEditor(lessonIn) {
    setHash("#/edit");
    setTitle("Edit lesson");
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
      busy(save, true);
      try { await api("/api/lessons", { lesson: edited }); errSlot.append(h("p", { class: "ok", role: "status" }, icon("check"), " Checked and saved to your library.")); }
      catch (err) { errSlot.append(errorBox(err.message + " The lesson was not saved, because a lesson that fails its checks is never shown to learners.", err.problems)); }
      busy(save, false);
    } }, "Check and save");
    view(h("section", {},
      h("h1", {}, "Edit lesson"),
      h("p", { class: "muted", style: "max-width:66ch" }, "Correct anything before sharing. Saving re-runs every quality check against the sources: quotes must still match word for word, and every goal must still be reachable."),
      h("fieldset", {}, h("legend", {}, "Lesson"), field("Lesson title", lesson, "title"), field("Summary", lesson, "intro.summary", true)),
      Array.isArray(lesson.primer) ? h("fieldset", {}, h("legend", {}, "The idea in brief"),
        ...lesson.primer.flatMap((pg, i) => [field(`Page ${i + 1} heading`, pg, "heading"), field(`Page ${i + 1} text`, pg, "body", true),
          field(`Page ${i + 1} quote (optional; must match the source word for word)`, pg, "quote", true)])) : null,
      ...lesson.concepts.map((c, i) => h("fieldset", {}, h("legend", {}, `Concept ${i + 1}: ${c.title}`),
        EDIT_FIELDS.filter(([p]) => !p.startsWith("check.") || c.check).map(([p, label]) => field(label, c, p, /explanation|feedback|quote$|caption|misconception|note|idea|question|prompt/.test(p))))),
      advanced, errSlot,
      h("div", { class: "actions sticky-actions" }, save,
        h("button", { class: "ghost", onclick: () => openLesson(lesson, { saved: true, preview: true }) }, "Preview"),
        h("a", { class: "btn ghost", href: "#/library" }, "Back to library"))));
  }

  /* ------------------------------------------------------------ account */
  const PROVIDER_NAMES = { google: "Google", github: "GitHub" };

  function avatar(user, size) {
    const initial = (user.name || user.email || "?").trim().charAt(0).toUpperCase();
    const fallback = h("span", { class: "avatar", style: `--size:${size}px`, "aria-hidden": "true" }, initial);
    if (!user.avatar) return fallback;
    const img = h("img", { class: "avatar", style: `--size:${size}px`, src: user.avatar, alt: "", referrerpolicy: "no-referrer" });
    img.addEventListener("error", () => img.replaceWith(fallback));
    return img;
  }

  function drawAccountLink() {
    const a = $("#account-link"), signedOut = !status.user;
    $("#library-link").hidden = signedOut;  // signed out, Library would only ask you to sign in
    a.classList.toggle("signin-link", signedOut);
    if (status.user) {
      a.href = "#/account";
      a.onclick = null;
      a.replaceChildren(avatar(status.user, 26), h("span", { class: "account-name" }, status.user.name || "Account"));
      a.setAttribute("aria-label", `Your account and AI provider: ${status.user.name || status.user.email}`);
    } else {
      a.href = "#/signin";
      a.onclick = () => { if (!location.hash.startsWith("#/signin")) holdIntent({ route: location.hash }); };  // come back to this page
      a.replaceChildren("Sign in");
      a.removeAttribute("aria-label");
    }
  }

  // Google's own pre-approved "Sign in with Google" button (light theme, pill), shown exactly as Google draws it:
  // their branding guidelines forbid altering the logo, colours, type or spacing, so it is the image, not a restyle.
  const googleButton = () => {
    const src = (n) => `static/google-sign-in-${n}x.png`;
    return h("a", { class: "google-signin", href: "auth/google/start" },
      h("img", { src: src(2), srcset: [1, 2, 3, 4].map((n) => `${src(n)} ${180 * n}w`).join(", "), sizes: "216px", width: 216, height: 48, alt: "Sign in with Google" }));
  };

  function showSignIn(error, next) {
    if (status.user) { location.hash = "#/account"; return; }
    const options = status.sign_in || [];
    const held = heldIntent(false), ask = next === "build" ? held?.ask : null;
    const back = { "#/library": "your library", "#/account": "your account", "#/settings": "your account page", "#/feedback": "the feedback form" }[pageOf(held?.route)];
    // What happens after Google, said before anything else: the question they asked, or the page they'll return to.
    const context = ask
      ? [h("p", { class: "signin-lead" }, "Sign in, and you'll go straight to sources for"), h("blockquote", { class: "signin-ask" }, ask)]
      : [h("p", { class: "signin-lead" }, back ? `Sign in to open ${back}. You'll go straight back to it.`
        : next === "build" ? "Sign in to ask about a concept or bring a source, and build a lesson from it."
        : `Sign in to build lessons from your questions and sources.${held && "route" in held ? " You'll come back to this page." : ""}`)];
    const point = (text) => h("li", {}, h("span", { class: "signin-tick", "aria-hidden": "true" }, icon("check")), text);
    const mark = $(".site-head .logo").cloneNode(true);
    setTitle("Sign in");
    view(h("section", { class: "signin", "aria-labelledby": "signin-title" },
      h("div", { class: "signin-card" },
        mark,
        h("h1", { id: "signin-title" }, "Sign in to OpenLemma"),
        ...context,
        error ? errorBox(error) : null,
        options.length
          ? h("div", { class: "signin-options" }, options.map((p) => p.id === "google"
              ? googleButton()
              : h("a", { class: "btn" + (p.id === options[0].id ? " primary" : ""), href: `auth/${p.id}/start` }, p.label)))
          : errorBox("Signing in isn't set up on this server yet."),
        h("ul", { class: "signin-points" },
          point("Ask about anything: OpenLemma finds sources that teach it."),
          point("Every lesson you build is saved to your library."),
          point("Lessons are built with your own AI provider key, which stays in this browser.")),
        h("p", { class: "signin-fine" }, "OpenLemma keeps your name, email address and picture, and asks Google for nothing else. ",
          h("a", { href: "privacy" }, "Privacy"))),
      h("p", { class: "signin-alt" }, "Not ready yet? ",
        h("a", { href: "#/example" }, "Try the example lesson"), ", with no account or key.")));
  }


  /* Who you're signed in as, then the AI model you build with (the page's main task, its state shown at a
     glance from the server's status), then Sign out, quiet and apart. */
  async function showAccount(toProvider) {
    if (!status.user) { holdIntent({ route: toProvider ? "#/settings" : "#/account" }); return showSignIn(); }
    const u = status.user;
    const out = h("button", { class: "ghost small account-signout", onclick: async () => {
      busy(out, true);
      try { await api("/api/logout", {}); } catch (e) { /* signed out either way */ }
      status = await api("/api/status").catch(() => Object.assign(status, { user: null }));
      drawAccountLink();
      location.hash = "#/";
    } }, icon("leave"), "Sign out");
    const n = status.library_count || 0;
    setTitle("Account");
    const row = (label, value) => h("div", { class: "af-row" }, h("dt", {}, label), h("dd", {}, value));
    const profile = h("section", { class: "account-card account-profile", "aria-labelledby": "account-title" },
      h("div", { class: "account-head" }, avatar(u, 64),
        h("div", { class: "ah-text" }, h("h1", { id: "account-title" }, u.name || "Your account"), u.email ? h("p", {}, u.email) : null)),
      h("dl", { class: "account-facts" },
        h("div", { class: "af-row af-link" }, h("dt", {}, "Library"),
          h("dd", {}, h("a", { href: "#/library" }, n ? `${n} saved lesson${n === 1 ? "" : "s"}` : "No saved lessons yet"), icon("chevron"))),
        row("Signed in with", PROVIDER_NAMES[u.provider] || u.provider),
        row("Member since", new Date(u.created * 1000).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" })),
        // Only admins' status carries feedback_new.
        "feedback_new" in status ? h("div", { class: "af-row af-link af-last" }, h("dt", {}, "Feedback"),
          h("dd", {}, h("a", { href: "#/feedback/inbox" }, `${status.feedback_new} new`), icon("chevron"))) : null));
    // Connected or not, and with what: read from the server's status, and redrawn whenever the form saves.
    const state = h("div", { class: "ai-state", role: "status" });
    let working = true;  // false once the saved key fails its check (listing models)
    function drawState() {
      const p = status.provider || {};
      const broken = p.ok && !working;
      state.className = "ai-state" + (broken ? " bad" : p.ok ? " on" : "");
      state.replaceChildren(
        h("span", { class: "ai-state-mark", "aria-hidden": "true" }, icon(broken ? "cross" : p.ok ? "check" : "plus")),
        broken
          ? h("p", {}, h("strong", {}, "Needs attention. "), `Your saved ${p.name} key didn't work just now. The reason is shown below; paste a new key and save.`)
          : p.ok
          ? h("p", {}, h("strong", {}, "Connected. "), "Lessons are built with ", h("strong", {}, p.name), p.model ? [" using ", h("span", { class: "ai-model" }, p.model)] : null, ".")
          : h("p", {}, h("strong", {}, "Not connected yet. "), `Choose a provider below and ${(status.providers || []).some((x) => x.sign_in) ? "add its key or sign in" : "add its key"} to build lessons.`));
    }
    drawState();
    const provider = h("section", { class: "account-card account-ai", "aria-labelledby": "ai-title" },
      h("h2", { id: "ai-title", tabindex: "-1" }, "AI provider"),
      state,
      h("p", { class: "account-ai-note" }, "Your key stays in this browser and is never stored by OpenLemma. Your sources go only to the provider chosen here, and only when you build. The model has no tools: it only reads what OpenLemma sends."),
      keyForm(() => { working = true; drawState(); }, { quiet: true, onCheck: (ok) => { working = ok; drawState(); } }));
    view(h("div", { class: "account" }, profile, provider,
      h("div", { class: "account-out" }, h("p", {}, u.email ? `Signed in as ${u.email}` : "Signed in"), out)));
    if (toProvider) { provider.scrollIntoView({ block: "start" }); provider.querySelector("h2").focus({ preventScroll: true }); }
  }

  /* ------------------------------------------------------------ feedback page and inbox */
  let lastRoute = "";  // the route before this one, so the feedback page can say where it was opened from
  /* #/feedback: the form on its own page, from the footer. Signed out, it asks you to sign in and brings you back. */
  function showFeedback() {
    const params = new URLSearchParams(location.hash.split("?")[1] || "");
    let from = params.get("from") || "";
    if (!from && lastRoute && !pageOf(lastRoute).startsWith("#/feedback")) from = pageOf(lastRoute) || "#/";
    from = from.slice(0, 300);
    if (from) setHash(`#/feedback?from=${encodeURIComponent(from)}`);  // kept through the sign-in round trip
    if (!status.user) { holdIntent({ route: location.hash }); return showSignIn(); }
    setTitle("Feedback");
    view(h("section", { class: "fb-page", "aria-labelledby": "fb-title" },
      h("div", { class: "fb-card" },
        h("h1", { id: "fb-title" }, "Send feedback"),
        h("p", { class: "fb-lead" }, "Tell the people who run OpenLemma what's working and what isn't."),
        feedbackForm({ kind: "general", page: from }, { variant: "page" }))));
  }

  /* #/feedback/inbox: every account's feedback, newest first, for admins (the server says 404 to anyone else).
     Filter by New, Done or All; reply by email, mark done or new, or delete after asking in the row. */
  const FB_FILTERS = { new: "New", done: "Done", all: "All" };
  const FB_KINDS = { general: "General", lesson: "Lesson", error: "Error", build: "Build" };
  function showInbox() {
    const q = new URLSearchParams(location.hash.split("?")[1] || "").get("status");
    let filter = FB_FILTERS[q] ? q : "new", items = [];
    const live = h("p", { class: "sr-only", role: "status" });
    const say = (m) => { live.textContent = ""; setTimeout(() => { live.textContent = m; }, 60); };
    const body = h("div", { class: "fbx-body", "aria-busy": "true" });
    const countEl = h("p", { class: "lib-count-line fbx-count" });
    const tabs = Object.fromEntries(Object.entries(FB_FILTERS).map(([k, label]) =>
      [k, h("button", { type: "button", role: "tab", class: "seg", onclick: () => { if (k !== filter) { filter = k; load(); } } }, label)]));
    const head = h("div", { class: "fbx-head" },
      h("h1", { id: "fbx-title" }, "Feedback"),
      h("div", { class: "fbx-filter" }, h("div", { class: "segmented", role: "tablist", "aria-label": "Show" }, Object.values(tabs)), countEl));
    setTitle("Feedback inbox");
    view(h("section", { class: "lib fbx", "aria-labelledby": "fbx-title" }, head, body, live));

    const ctxLine = (it) => {
      const bits = [];
      const bit = (label, value, mono) => bits.push(h("span", {}, h("span", { class: "fbx-k" }, label), " ", h(mono ? "code" : "span", {}, value)));
      if (it.lesson_title || it.lesson_id) bit("Lesson", it.lesson_title || it.lesson_id);
      if (it.error_id) bit("Error", it.error_id, true);
      if (it.request_id) bit("Build", it.request_id, true);
      if (it.page) bit("Page", it.page, true);
      return bits.length ? h("p", { class: "fbx-ctx" }, bits) : null;
    };
    function row(it) {
      const key = `f:${it.id}`, who = it.name || it.email || "Someone";
      const acts = h("div", { class: "lib-acts" });
      const li = h("li", { class: `lib-row fbx-row${it.status === "done" ? " is-done" : ""}`, "data-key": key },
        h("div", { class: "lib-text" },
          h("div", { class: "fbx-top" },
            it.rating ? h("span", { class: `fbx-rate ${it.rating === "helpful" ? "is-good" : "is-bad"}` },
              icon(it.rating === "helpful" ? "up_thumb" : "down_thumb"), it.rating === "helpful" ? "Helpful" : "Not helpful") : null,
            h("span", { class: "tag" }, FB_KINDS[it.kind] || it.kind),
            filter === "all" && it.status === "done" ? h("span", { class: "tag fbx-done" }, icon("check"), "Done") : null),
          it.message ? h("p", { class: "fbx-msg" }, it.message) : h("p", { class: "fbx-msg is-empty" }, "No message."),
          ctxLine(it),
          h("p", { class: "lib-meta fbx-from" }, h("span", {}, who), it.email && it.name ? h("span", {}, it.email) : null, h("span", {}, when(it.created, true)))),
        acts, h("p", { class: "lib-msg", role: "alert", hidden: true }));
      if (it.email) acts.append(h("a", { class: "btn small ghost", href: `mailto:${it.email}?subject=${encodeURIComponent("Your OpenLemma feedback")}`, "aria-label": `Reply to ${who} by email` }, icon("mail"), "Reply"));
      const next = it.status === "done" ? "new" : "done";
      const mark = h("button", { type: "button", class: "small ghost", onclick: async () => {
        busy(mark, true);
        try { await api(`/api/feedback/${it.id}/status`, { status: next }); }
        catch (err) { busy(mark, false); return failed(li, err); }
        await load(filter === "all" ? key : neighbour(li));  // in All the row stays; otherwise it leaves the list
        say(next === "done" ? `Marked done: feedback from ${who}.` : `Marked new: feedback from ${who}.`);
      } }, icon(next === "done" ? "check" : "refresh"), next === "done" ? "Mark done" : "Mark new");
      const del = h("button", { type: "button", class: "small danger lib-del", "aria-label": `Delete the feedback from ${who}`, onclick: (e) => ask(li, e.currentTarget, {
        question: "Delete this feedback? This can't be undone.", yes: "Delete", busyText: "Deleting…", no: "Keep it",
        act: async () => {
          try { await api(`/api/feedback/${it.id}`, undefined, "DELETE"); } catch (err) { return failed(li, err); }
          await load(neighbour(li));
          say(`Deleted the feedback from ${who}.`);
        } }) }, "Delete");
      acts.append(mark, del);
      return li;
    }
    const neighbour = (li) => li.nextElementSibling?.dataset.key || li.previousElementSibling?.dataset.key || "-";  // "-": none left, focus the filter
    async function failed(li, err) {
      const key = li.dataset.key;
      await load(key);
      const now = body.querySelector(`[data-key="${key}"]`);
      if (!now) return say(err.message);
      const m = now.querySelector(".lib-msg");
      m.replaceChildren(icon("cross"), h("span", {}, err.message));
      m.hidden = false;
    }

    async function load(focusKey) {
      for (const [k, b] of Object.entries(tabs)) { b.classList.toggle("active", k === filter); b.setAttribute("aria-selected", String(k === filter)); }
      history.replaceState(null, "", filter === "new" ? "#/feedback/inbox" : `#/feedback/inbox?status=${filter}`);
      try { items = await api(`/api/feedback${filter === "all" ? "" : `?status=${filter}`}`); }
      catch (err) {
        if (err.status === 404) {  // not an admin: the page isn't there for you
          setTitle("Not found");
          return view(h("section", { class: "lib-empty fbx-404", "aria-labelledby": "nf-title" },
            h("h1", { id: "nf-title" }, "Not found"), h("p", {}, "There's no page at this address."),
            h("div", { class: "actions" }, h("a", { class: "btn", href: "#/" }, "Go to the home page"))));
        }
        body.removeAttribute("aria-busy");
        return body.replaceChildren(h("div", { class: "lib-none", role: "alert" }, h("p", {}, `The feedback couldn't load. ${err.message}`),
          h("button", { type: "button", onclick: () => load() }, icon("refresh"), "Try again")));
      }
      if (!body.isConnected) return;
      body.removeAttribute("aria-busy");
      const newCount = filter === "new" ? items.length : null;
      if (newCount !== null) status.feedback_new = newCount;
      countEl.textContent = plural(items.length, filter === "all" ? "message" : `${FB_FILTERS[filter].toLowerCase()} message`);
      body.replaceChildren(items.length
        ? h("ul", { class: "lib-list fbx-list" }, items.map(row))
        : h("div", { class: "lib-none fbx-none" }, h("p", {}, { new: "No new feedback.", done: "Nothing marked done yet.", all: "No feedback yet." }[filter])));
      const li = focusKey && body.querySelector(`[data-key="${focusKey}"]`);
      if (focusKey) (li ? li.querySelector(".lib-acts button, .lib-acts a") : tabs[filter]).focus({ preventScroll: !!li });
    }
    load();
  }

  /* ------------------------------------------------------------ routing */
  // The nav link for the page you are on says so (aria-current), and is drawn as the current pill.
  function markNav(hash) {
    const page = { "#/settings": "#/account", "#/": "", "": "" }[hash.split("?")[0]] ?? hash.split("?")[0];
    document.querySelectorAll(".site-nav a").forEach((a) => {
      if (page && a.getAttribute("href") === page) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
  }

  async function route() {
    const hash = location.hash;
    markNav(hash);
    if (hash.startsWith("#/request/")) {
      if (player && hash.endsWith("/learn")) return;
      return showRequest(hash.split("/")[2]);
    }
    if (hash === "#/library" || hash.startsWith("#/library?")) return showLibrary();
    if (hash === "#/make") return showMake();
    if (hash === "#/settings") return showAccount(true);  // the AI provider is part of the account page
    if (hash.startsWith("#/signin")) {
      const params = new URLSearchParams(hash.split("?")[1] || "");
      return showSignIn(params.get("error"), params.get("next"));
    }
    if (hash === "#/account") return showAccount();
    if (hash === "#/feedback/inbox" || hash.startsWith("#/feedback/inbox?")) return showInbox();
    if (hash === "#/feedback" || hash.startsWith("#/feedback?")) return showFeedback();
    if (hash === "#/example") return player ? null : openExample();
    if (hash === "#/gallery" || hash.startsWith("#/gallery?")) return showGallery();
    if (hash.startsWith("#/gallery/")) return player ? null : openGallery(hash.slice(10));
    if (hash.startsWith("#/lesson/")) {
      if (player) return;
      try { return openLesson(await api(`/api/lessons/${hash.slice(9)}`), { saved: true }); } catch (e) { return showHome(e.message); }
    }
    if (hash === "#/outline" && session.outline) return;
    if (hash === "#/learn" || hash === "#/edit") return;
    return showHome();
  }

  window.addEventListener("hashchange", (e) => {
    try { lastRoute = new URL(e.oldURL).hash; } catch (err) { lastRoute = ""; }
    if (["#/library", "#/gallery", "#/make", "#/settings", "#/account", "#/signin", "#/feedback", "#/feedback/inbox", "#/", ""].includes(location.hash.split("?")[0]) && player) { player.destroy(); player = null; }
    route();
  });

  (async function init() {
    try { status = await api("/api/status"); } catch (e) { /* the server will report */ }
    // A provider saved here that this server doesn't offer (gone, or ChatGPT when hosted) is forgotten, so the account page starts from the rest.
    if (cred.provider && status.providers && !status.providers.some((x) => x.id === cred.provider)) saveCred(Object.assign({}, cred, { provider: "" }));
    drawAccountLink();
    const held = status.user && heldIntent(true);
    if (held && "route" in held) history.replaceState(null, "", held.route.startsWith("#/signin") ? "#/" : held.route || "#/");
    else if (held) {
      session.mode = held.mode;
      if (held.ask) session.ask = held.ask;
      history.replaceState(null, "", "#/make");
    }
    route();
  })();
})();
