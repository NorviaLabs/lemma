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

  // The learner's provider, models and keys stay in this browser and go to the server with each request.
  const CRED_KEY = "lemma.ai";
  function loadCred() {
    try { return Object.assign({ provider: "", models: {}, keys: {} }, JSON.parse(localStorage.getItem(CRED_KEY) || "{}")); }
    catch (e) { return { provider: "", models: {}, keys: {} }; }
  }
  let cred = loadCred();
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
    const res = await fetch(path, {
      method: method || (body === undefined ? "GET" : "POST"),
      headers: Object.assign(body === undefined ? {} : { "Content-Type": "application/json" }, headers || credHeaders()),
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

  /* ------------------------------------------------------------ AI provider */
  const TAGLINES = {
    "opencode-go": "Many models through an OpenCode Go plan. Fits long papers (about 1M tokens).",
    openai: "OpenAI's models, billed to your OpenAI API account.",
    chatgpt: "Your ChatGPT Plus or Pro plan, no key needed. For Lemma on your own computer.",
  };

  /* Pick a provider, then paste a key or sign in; Lemma checks either by listing the provider's models. */
  function keyForm(onSaved) {
    const providers = status.providers || [];
    let selected = cred.provider || (providers[0] || {}).id;
    let chatgpt = { signed_in: false };
    let poll = null;
    const body = h("div");
    const msg = h("div", { role: "status" });
    const stopPoll = () => { clearTimeout(poll); poll = null; };
    cleanups.push(stopPoll);
    const ready = (x) => (x.sign_in ? chatgpt.signed_in : !!cred.keys[x.id]);
    function draw() {
      const p = providers.find((x) => x.id === selected) || {};
      const key = h("input", { id: "ai-key", type: "password", autocomplete: "off", spellcheck: "false", placeholder: `Paste your ${p.name} key` });
      key.value = cred.keys[p.id] || "";
      const model = h("select", { id: "model", disabled: true }, h("option", { value: cred.models[p.id] || p.default_model }, cred.models[p.id] || p.default_model));
      const note = h("p", { class: "muted small" }, p.sign_in ? "Sign in to choose from your plan's models." : "Save a key to choose from the models it can use.");
      const choice = h("div", { class: "provider-choice", role: "radiogroup", "aria-label": "AI provider" }, providers.map((x) =>
        h("label", { class: "provider-option" },
          h("input", { type: "radio", name: "provider", value: x.id, checked: x.id === selected, onchange: () => { selected = x.id; msg.replaceChildren(); draw(); } }),
          h("span", { class: "po-body" },
            h("span", { class: "po-name" }, x.name),
            h("span", { class: "po-tagline" }, TAGLINES[x.id] || ""),
            h("span", { class: "po-status " + (ready(x) ? "ok" : "") }, ready(x) ? icon("check") : null,
              ready(x) ? (x.sign_in ? "Signed in" : "Key saved") : (x.sign_in ? "Not signed in" : "No key yet"))))));
      async function loadModels(c) {
        const r = await api("/api/models", undefined, undefined, credHeaders(c));
        model.replaceChildren(...r.models.map((m) => h("option", { value: m.id, selected: m.id === r.current }, `${m.name}${m.context ? ` · ${Math.round(m.context / 1000)}k context` : ""}`)));
        if (!r.models.some((m) => m.id === r.current)) model.prepend(h("option", { value: r.current, selected: true }, `${r.current} (not offered right now)`));
        model.disabled = false;
        note.textContent = `${r.models.length} model${r.models.length === 1 ? "" : "s"} offered by ${p.name}.`;
      }
      if (ready(p)) loadModels(Object.assign({}, cred, { provider: p.id })).catch((err) => note.replaceChildren(errorBox(err.message)));
      const save = h("button", { class: "primary", disabled: p.sign_in && !chatgpt.signed_in, onclick: async () => {
        const next = { provider: p.id, keys: Object.assign({}, cred.keys), models: Object.assign({}, cred.models) };
        if (!p.sign_in) next.keys[p.id] = key.value.trim();
        if (!model.disabled && model.value) next.models[p.id] = model.value;
        if (!p.sign_in && !next.keys[p.id]) return msg.replaceChildren(errorBox(`Paste your ${p.name} key first.`));
        save.disabled = true;
        msg.replaceChildren(h("p", { class: "muted" }, p.sign_in ? "Checking your sign-in…" : "Checking the key…"));
        try {
          await loadModels(next);  // a key that can't list models won't build lessons either
          if (!model.disabled && model.value) next.models[p.id] = model.value;
          saveCred(next);
          status = await api("/api/status");
          msg.replaceChildren(h("p", { class: "ok" }, icon("check"), ` Saved. Lessons will be built with ${status.provider.label}.`));
          if (onSaved) onSaved();
        } catch (err) { msg.replaceChildren(errorBox(err.message)); }
        save.disabled = false;
      } }, "Save");
      body.replaceChildren(choice, ...(p.sign_in ? signInPart(p) : [
        h("label", { for: "ai-key" }, `${p.name} key`), key,
        h("p", { class: "muted small" }, h("a", { href: p.key_url, target: "_blank", rel: "noopener noreferrer" }, `Get a ${p.name} key`),
          ". It stays in this browser. Lemma's server uses it only while building your lesson and never stores it.")]),
        h("label", { for: "model" }, `${p.name} model`), model, note, msg,
        h("div", { class: "actions" }, save));
    }
    function signInPart(p) {
      if (chatgpt.signed_in) {
        return [h("p", {}, icon("check"), ` Signed in${chatgpt.email ? ` as ${chatgpt.email}` : ""}. `,
          h("button", { class: "ghost small", onclick: async () => { chatgpt = await api("/api/chatgpt/logout", {}); draw(); } }, "Sign out"))];
      }
      const start = h("button", { class: "primary", onclick: async () => {
        const tab = window.open("", "_blank");  // opened now, while the click still counts, so it isn't blocked
        try {
          const r = await api("/api/chatgpt/login", {});
          if (tab) tab.location = r.url; else location.assign(r.url);
          msg.replaceChildren(h("p", { class: "muted" }, "Finish signing in in the new tab. Lemma will notice when you're done."));
          waitForSignIn();
        } catch (err) { if (tab) tab.close(); msg.replaceChildren(errorBox(err.message)); }
      } }, `Sign in with ${p.name}`);
      return [start, h("p", { class: "muted small" }, "Lessons count against your plan's usage. Lemma keeps your sign-in on this computer only, in ~/.lemma, and you can sign out at any time.")];
    }
    function waitForSignIn() {
      stopPoll();
      poll = setTimeout(async () => {
        if (!body.isConnected) return;  // the learner left Settings
        try { chatgpt = await api("/api/chatgpt"); } catch (e) { return waitForSignIn(); }
        if (chatgpt.signed_in) { msg.replaceChildren(); return draw(); }
        if (chatgpt.error) return msg.replaceChildren(errorBox(chatgpt.error));
        if (chatgpt.waiting) waitForSignIn();
      }, 1500);
    }
    draw();
    api("/api/chatgpt").then((r) => { chatgpt = r; draw(); }).catch(() => {});
    return body;
  }

  /* ------------------------------------------------------------ home */
  // Starting points for "Search a topic"; Surprise me picks one at random.
  const TOPICS = ["Regression to the mean", "The prisoner's dilemma", "Herd immunity", "Simpson's paradox", "Small-world networks",
    "Schelling segregation model", "Statistical power", "Confounding variables", "Bayes' theorem", "Natural selection",
    "Diminishing returns", "Network contagion", "Random walks", "Signal detection theory", "The wisdom of crowds",
    "Opinion dynamics", "Sampling bias", "Loss aversion", "Supply and demand", "Exponential growth"];

  const AUDIENCES = ["A curious learner with no special background", "An undergraduate student", "An educator preparing a class", "A researcher from a neighbouring field"];

  /* The doorway exhibit: one live model from the example lesson, playable the moment the page opens.
     The label rail's three verbs light up as the visitor plays; until then the model sweeps by itself. */
  const MEAN = 68.25, SHARE = 2 / 3;
  let exhibitStep = 0;
  let exampleP = null;
  const exampleLesson = () => (exampleP = exampleP || api("/api/example").catch((e) => { exampleP = null; throw e; }));
  function homeExhibit() {
    const M = window.LemmaModel;
    const stage = h("div", { class: "he-stage", "aria-busy": "true" }, h("p", { class: "muted" }, "Setting up the exhibit…"));
    const verbEls = [];
    const verb = (n, title, ...body) => {
      const li = h("li", { class: "verb" },
        h("div", { class: "verb-head" }, h("span", { class: "verb-mark", "aria-hidden": "true" }, String(n)), title, h("span", { class: "sr-only verb-state" })),
        h("div", { class: "verb-body" }, ...body));
      verbEls.push(li);
      return li;
    };
    const noticeLine = h("p", { class: "he-live" });
    const noticeMore = h("p");
    const tryText = h("p", {}, "This exhibit comes from Galton's 1886 paper on heredity. Drag the parents' height away from the middle and watch where their children land.");
    const whyBtn = h("button", { type: "button", class: "he-skip", onclick: () => setStep(2, true) }, "Tell me why");
    const verbs = h("ol", { class: "verbs", "aria-live": "polite" },
      verb(1, "Try this", tryText),
      verb(2, "Notice", noticeLine, noticeMore, whyBtn),
      verb(3, "What's going on",
        h("figure", { class: "he-quote" },
          h("blockquote", {}, "the height-deviate of the offspring is, on the average, two-thirds of the height-deviate of its mid-parentage."),
          h("figcaption", {}, "Galton, 1886, page 252")),
        h("p", {}, "Galton called it regression towards mediocrity. Today it's called regression to the mean, and it shows up wherever two measurements are related but not perfectly."),
        h("div", { class: "he-cta" },
          h("button", { class: "primary", onclick: openExample }, icon("play"), "Walk the whole lesson"),
          h("span", { class: "small" }, "About 10 minutes, with no setup."))));
    function setStep(n, focus) {
      exhibitStep = Math.max(exhibitStep, n);
      verbEls.forEach((li, i) => {
        li.className = "verb " + (i < exhibitStep ? "done" : i === exhibitStep ? "active" : "later");
        li.querySelector(".verb-mark").replaceChildren(i < exhibitStep ? icon("check") : String(i + 1));
        li.querySelector(".verb-state").textContent = i < exhibitStep ? " (done)" : i === exhibitStep ? " (now)" : "";
        li.querySelector(".verb-body").hidden = i > exhibitStep;
      });
      whyBtn.hidden = exhibitStep !== 1;
      if (focus && exhibitStep === 2) verbEls[2].querySelector("button").focus({ preventScroll: true });
    }
    setStep(exhibitStep);

    const el = h("section", { class: "home-exhibit", "aria-labelledby": "home-title" },
      h("div", { class: "he-intro" },
        h("h1", { id: "home-title" }, "Learn a paper by playing with it"),
        h("p", { class: "lead" }, "Search any topic or bring a paper, and Lemma turns it into a hall of hands-on exhibits. You don't need to have read anything: it tells you the paper's story, walks you through a live model of each idea, then lets you try it yourself.")),
      stage,
      h("div", { class: "he-verbs" }, verbs));

    exampleLesson().then((lesson) => {
      const c = lesson.concepts.find((x) => x.id === "regression_line");
      if (!c || !el.isConnected) return;
      const model = Object.assign({}, c.model, { controls: c.model.controls.filter((k) => k.id === "mp") });
      const k = model.controls[0];
      let values = { mp: 72, ratio: SHARE };
      const seen = { above: false, below: false };
      const vizBox = h("div", { class: "viz-box" });
      const view = new M.ModelView(vizBox, model);
      view.trailsOn = true;  // the home exhibit always leaves a trail; the learner's saved choice is untouched
      const outs = h("dl", { class: "outputs" });
      const valueEl = h("output", { for: "he-mp", class: "ctl-value" });
      const input = h("input", { type: "range", id: "he-mp", min: k.min, max: k.max, step: k.step, value: values.mp });
      const playBtn = h("button", { type: "button", class: "play", "aria-label": `Play ${k.label} through its range`, onclick: () => { stopDemo(); sweep(); } }, icon("play"), "Play");
      const demoNote = h("p", { class: "caption he-demo" }, h("span", {}, "It's moving on its own. Grab the slider to take over."),
        h("button", { type: "button", class: "small", onclick: () => { stopDemo(); input.focus(); } }, "Stop"));
      function render(user) {
        const env = view.update(values) || {};
        input.value = values.mp;
        input.style.setProperty("--fill", `${((values.mp - k.min) / (k.max - k.min)) * 100}%`);
        valueEl.textContent = M.fmt(values.mp, 2, 1, k.unit);
        outs.replaceChildren(...model.outputs.map((o, i) => h("div", { class: "out" + (exhibitStep >= 1 && o.id === "child" ? " hl" : ""), style: `--k:var(--model-${(o.color ?? i) % 8})` },
          h("dt", {}, h("span", { class: "key", "aria-hidden": "true" }), o.label), h("dd", {}, M.fmt(env[o.id], o.decimals ?? 2, 1, o.unit || "")))));
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
      // Attract mode: a slow sweep until someone touches the exhibit. Off under reduced motion.
      let demo = null, onscreen = true;
      if (typeof IntersectionObserver !== "undefined") {
        const io = new IntersectionObserver(([e]) => { onscreen = e.isIntersecting; });
        io.observe(stage);
        cleanups.push(() => io.disconnect());
      }
      function stopDemo() {
        if (demo) cancelAnimationFrame(demo);
        demo = null;
        demoNote.hidden = true;
        playBtn.disabled = false;
      }
      function startDemo() {
        if (M.reduceMotion()) { demoNote.hidden = true; return; }
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
      const deck = h("div", { class: "controls", role: "group", "aria-label": "Controls" },
        h("div", { class: "ctl", style: `--k:var(--model-${(k.color ?? 0) % 8})` },
          h("label", { for: "he-mp" }, h("span", { class: "key", "aria-hidden": "true" }), "Parents' average height"), valueEl, input, playBtn));
      stage.replaceChildren(
        h("div", { class: "model-head" },
          h("p", { class: "he-from" }, h("span", { class: "plate", "aria-hidden": "true" }, "2"), h("span", {}, "Exhibit 2 of the example lesson", h("br"), h("em", {}, lesson.source.title))),
          h("span", { class: "tag", title: model.note }, "Teaching model")),
        h("div", { class: "he-viz" }, vizBox, demoNote), outs, deck,
        h("p", { class: "model-note" }, model.note));
      stage.removeAttribute("aria-busy");
      render(exhibitStep > 0);
      if (exhibitStep === 0) startDemo(); else demoNote.hidden = true;
      cleanups.push(() => { stopDemo(); view.destroy(); });
    }).catch(() => {
      stage.replaceChildren(h("p", { class: "muted" }, "The example exhibit couldn't load. You can still make a lesson below."));
      stage.removeAttribute("aria-busy");
    });
    return el;
  }


  /* From paper to hall: one scroll-scrubbed sequence. The page of the paper is marked up, each marked
     idea grows out of it into a numbered exhibit, then the page steps back and the hall stands.
     Without JavaScript, or with reduced motion, it is a static figure beside the four steps. */
  const HALL_STEPS = [
    ["Bring a paper", "A topic to search, a link, a PDF or a saved web page. You say who the lesson is for."],
    ["Lemma finds the ideas", "It reads the paper and drafts an outline of its main ideas. You can review and edit it before anything is built."],
    ["Each idea becomes an exhibit", "A live model you can play with, checked before you see it, with the paper's own words quoted and verified."],
    ["Walk the hall", "Start while later exhibits are still building. Save the lesson to your library, or download one file that works offline."],
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
    const lines = Array.from({ length: 15 }, (_, i) => h("span", { class: "hp-line" + ([2, 7, 11].includes(i) ? " idea" : ""), style: `--w:${[96, 88, 92, 100, 74, 94, 90, 84, 98, 70, 93, 89, 97, 80, 60][i]}%` }));
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
          h("h2", { id: "hall-title" }, "From a paper to a hall of exhibits"),
          h("ol", { class: "hall-steps" }, stepEls)),
        art));
    exampleLesson().then((lesson) => {
      lesson.concepts.slice(0, 3).forEach((c, i) => { cards[i].querySelector(".hx-title").textContent = c.title; });
      paper.querySelector(".hp-title").textContent = lesson.source.title;
      paper.querySelector(".hp-by").textContent = `${lesson.source.authors}, ${lesson.source.year}`;
    }).catch(() => {});
    if (M.reduceMotion() || typeof requestAnimationFrame === "undefined") return sec;

    sec.classList.add("is-live");
    const clamp = (x) => Math.max(0, Math.min(1, x));
    const ease = (x) => 1 - Math.pow(1 - x, 3);
    // Where each card starts: centred on its marked line, measured untransformed (offsets ignore transforms).
    const offsetIn = (node, ancestor) => { let x = 0, y = 0; for (let n = node; n && n !== ancestor; n = n.offsetParent) { x += n.offsetLeft; y += n.offsetTop; } return [x, y]; };
    function measure() {
      cards.forEach((card, i) => {
        const [lx, ly] = offsetIn(ideas[i], art), [cx, cy] = offsetIn(card, art);
        card.style.setProperty("--dx", `${lx + ideas[i].offsetWidth / 2 - (cx + card.offsetWidth / 2)}px`);
        card.style.setProperty("--dy", `${ly + ideas[i].offsetHeight / 2 - (cy + card.offsetHeight / 2)}px`);
      });
    }
    let raf = 0, lastStep = -1;
    function frame() {
      raf = 0;
      const r = sec.getBoundingClientRect(), run = sec.offsetHeight - innerHeight;
      if (run <= 0) return;
      const p = clamp(-r.top / run);
      art.style.setProperty("--hl", ease(clamp((p - 0.16) / 0.2)).toFixed(3));
      art.style.setProperty("--back", ease(clamp((p - 0.8) / 0.14)).toFixed(3));
      cards.forEach((card, i) => card.style.setProperty("--t", ease(clamp((p - 0.42 - i * 0.07) / 0.2)).toFixed(3)));
      const step = p < 0.14 ? 0 : p < 0.4 ? 1 : p < 0.78 ? 2 : 3;
      if (step !== lastStep) {
        lastStep = step;
        stepEls.forEach((li, i) => li.className = "hs-step" + (i < step ? " done" : i === step ? " now" : ""));
        art.dataset.step = step;
      }
    }
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(frame); };
    const onResize = () => { measure(); onScroll(); };
    // Attach after view() has mounted the page: it runs the previous screen's cleanups first.
    requestAnimationFrame(() => {
      if (!sec.isConnected) return;
      addEventListener("scroll", onScroll, { passive: true });
      addEventListener("resize", onResize);
      cleanups.push(() => { removeEventListener("scroll", onScroll); removeEventListener("resize", onResize); cancelAnimationFrame(raf); });
      measure();
      frame();
    });
    if (document.fonts) document.fonts.ready.then(() => sec.isConnected && onResize());
    return sec;
  }

  function showHome(msg) {
    setHash("");
    const p = status.provider || {};
    if (!p.ok) {
      view(msg ? errorBox(msg) : null, homeExhibit(), hallSection(),
        h("section", { class: "panel setup", "aria-labelledby": "setup-title" },
          h("h2", { id: "setup-title" }, "Make lessons from your own papers"),
          h("p", {}, "Lemma doesn't come with an AI model. It uses your own key, so your papers go only where you choose. Pick a provider; you can switch later in Settings."),
          keyForm(() => showHome())));
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
    view(msg ? errorBox(msg) : null, homeExhibit(), hallSection(), h("div", { class: "home-make" }, h("div", { class: "hm-main" }, form, results), recent));
    if (status.library_count) {
      api("/api/lessons").then((items) => {
        if (!items.length) return;
        recent.hidden = false;
        recent.replaceChildren(h("h2", { id: "recent-title" }, "Your recent lessons"),
          h("ul", { class: "recent-list" }, items.slice(0, 3).map((it) => h("li", {},
            h("button", { class: "recent-item", onclick: async () => openLesson(await api(`/api/lessons/${it.id}`), { saved: true }) },
              h("span", { class: "ri-title" }, it.title), h("span", { class: "ri-meta" }, `${it.concepts} exhibit${it.concepts === 1 ? "" : "s"} · ${it.source}`))))),
          ...(items.length > 3 ? [h("a", { href: "#/library" }, `All ${items.length} lessons`)] : []));
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
    view(h("section", { class: "panel", style: "max-width:900px" },
      h("h1", {}, "Settings"),
      h("p", { style: "max-width:66ch" }, "Lemma builds lessons with your own AI provider key. It sends a paper's text only when you build a lesson, and only to the provider and model chosen here. The model gets no tools: it can only read what Lemma sends and reply with text."),
      h("h3", {}, "AI provider"), keyForm(),
      h("div", { class: "actions" }, h("a", { class: "btn ghost", href: "#/" }, "Back"))));
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
