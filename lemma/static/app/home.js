/* The home page: the question and source panel, the regression exhibit, the hall of steps, recent lessons and the
   gallery wall; and the #/make page. */
import { api, cleanups, errorBox, h, icon, plural, session, setHash, setTitle, status, view, when } from "./shell.js";
import { pageOf } from "./feedback.js";
import { gallerySection } from "./gallery.js";
import { findPanel, loadRecent } from "./find.js";
import { filmPlayer } from "./learn.js";

// Starting points for "Ask about a concept"; Surprise me picks one at random.
export const TOPICS = ["Regression to the mean", "The prisoner's dilemma", "Herd immunity", "Simpson's paradox", "Small-world networks",
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

export function showHome(msg) {
  const was = pageOf(location.hash);
  setHash("");
  setTitle("");
  view(msg ? errorBox(msg, null, null, was) : null, homeExhibit(), hallSection(), gallerySection());
}

/* A returning learner's fast path: the build panel alone, no intro to scroll past. */
export function showMake() {
  setHash("#/make");
  setTitle("New lesson");
  const { form, results, recent } = findPanel();
  view(h("section", {},
    h("h1", {}, "What do you want to understand?"),
    h("p", { class: "lead" }, "Ask about a concept, or bring your own papers, articles or chapters, up to 10 links and files. OpenLemma turns them into one short lesson, with a live model for each idea."),
    form, results, recent));
  loadRecent(recent);
}
