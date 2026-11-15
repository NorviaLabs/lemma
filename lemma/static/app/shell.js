/* What every screen shares: the page and its state (who is signed in, the open player, polling, the build session),
   the learner's provider and keys, calling the API, showing a screen (view), errors, busy buttons, downloads and the build
   progress list. The element builder and icons are ui.js's (LemmaUI). */
import { reportThis } from "./feedback.js";

export const $ = (s, r = document) => r.querySelector(s);
export const main = $("#main");
export let status = { provider: {}, providers: [] };
export let player = null;
let pollTimer = null;
export let cleanups = [];
export const setStatus = (v) => { status = v; };
export const setPlayer = (v) => { player = v; };
export const setPollTimer = (v) => { pollTimer = v; };
export const session = { level: "", outline: null, removed: [], lesson: null, search: null, mode: "search" };

/* ------------------------------------------------------------ helpers */
export const { h, icon, ext, plural, when } = LemmaUI;  // shared with the player: ui.js

// The learner's provider, models and keys stay in this browser and go to the server with each request.
const CRED_KEY = "lemma.ai";
function loadCred() {
  try { return Object.assign({ provider: "", models: {}, keys: {} }, JSON.parse(localStorage.getItem(CRED_KEY) || "{}")); }
  catch (e) { return { provider: "", models: {}, keys: {} }; }
}
export let cred = loadCred();
// What a signed-out visitor was about to do, kept through the sign-in round trip (same tab) so they carry on from it.
const HELD_KEY = "lemma.held";
export function holdIntent(intent) { try { sessionStorage.setItem(HELD_KEY, JSON.stringify({ ...intent, at: Date.now() })); } catch (e) { /* they start again */ } }
export function heldIntent(take) {
  try {
    const v = JSON.parse(sessionStorage.getItem(HELD_KEY) || "null");
    if (take) sessionStorage.removeItem(HELD_KEY);
    return v && Date.now() - v.at < 3600e3 ? v : null;
  } catch (e) { return null; }
}
export function saveCred(next) {
  cred = next;
  try { localStorage.setItem(CRED_KEY, JSON.stringify(next)); } catch (e) { /* kept for this visit only */ }
}
export function credHeaders(c = cred) {
  const out = {};
  if (c.provider) out["X-Lemma-Provider"] = c.provider;
  if (c.provider && c.keys[c.provider]) out["X-Lemma-Key"] = c.keys[c.provider];
  if (c.provider && c.models[c.provider]) out["X-Lemma-Model"] = c.models[c.provider];
  return out;
}

export async function api(path, body, method, headers) {
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

export function view(...kids) {
  cleanups.forEach((fn) => fn());
  cleanups = [];
  stopPolling();
  if (player) { player.destroy(); player = null; }
  main.replaceChildren(...kids.filter(Boolean));
  const head = main.querySelector("h1, h2");
  if (head) { head.setAttribute("tabindex", "-1"); head.focus({ preventScroll: true }); }
  window.scrollTo(0, 0);
}

export const setHash = (hash) => history.replaceState(null, "", hash || location.pathname + location.search);
// Each screen names itself in the tab and history; the home page is just "OpenLemma".
export const setTitle = (t) => { document.title = t ? `${t} · OpenLemma` : "OpenLemma"; };
export function stopPolling() { clearTimeout(pollTimer); pollTimer = null; }

// The id an unexpected error carries, as logs.report writes it: "… (error 1a2b3c4d)." from a build, or "… with error
// id 1a2b3c4d." from the server's own 500 answer. Ordinary refusals have none.
export const ERROR_ID = /\berror (?:id )?([0-9a-f]{8})\b/;
/* An error, said in place. One that carries an error id, or a build that stopped (`report`), can be reported
   from where it is shown, by a signed-in account. */
export function errorBox(msg, problems, report, page) {
  const id = (String(msg).match(ERROR_ID) || [])[1];
  let ctx = report || (id ? { kind: "error", error_id: id } : null);
  if (ctx && page) ctx = { ...ctx, page };  // where it happened, when the page has already moved on (home)
  return h("div", { class: "error", role: "alert" }, h("p", {}, msg),
    problems && problems.length ? h("details", {}, h("summary", {}, `${problems.length} problem${problems.length > 1 ? "s" : ""}`), h("ul", {}, problems.slice(0, 40).map((p) => h("li", {}, p)))) : null,
    ctx && status.user ? reportThis(ctx) : null);
}

// A button that is waiting on the server: disabled and announced busy, but drawn in its own colours (see
// [aria-busy] in styles.css) so it reads as working, not as unavailable.
export function busy(btn, on) {
  btn.disabled = on;
  if (on) btn.setAttribute("aria-busy", "true"); else btn.removeAttribute("aria-busy");
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

const STATE_MARK = { waiting: "", active: "", done: "check", failed: "cross", skipped: "dash", stopped: "dash" };
const clock = (sec) => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;

/* A build's progress: how many concepts are ready, then each step with what it's doing now, how long it has
   taken and, while a concept is being fixed, what the checks found. It updates in place on every poll, so an
   opened list of findings stays open, and its timers tick between polls. */
export function buildProgress() {
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
  // `stopped` is what to say for a build that stopped before it had any concepts to count.
  function update(steps, now, stopped) {
    offset = now ? Date.now() / 1000 - now : 0;  // the server's clock against this one, for the timers
    const concepts = steps.filter((s) => s.label.startsWith("Concept "));
    const ready = concepts.filter((s) => s.state === "done").length, out = concepts.filter((s) => s.state === "failed").length;
    if (concepts.length) {
      count.textContent = `${ready} of ${concepts.length} concepts ready` + (out ? ` · ${out} left out` : "");
      bar.max = concepts.length;
      bar.value = ready + out;
    } else {
      const active = steps.find((s) => s.state === "active");
      count.textContent = active ? active.label : stopped || "Getting started…";
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

export function download(filename, text) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/html" }));
  // The app's own blob: link, set directly: h() lets through only the kinds of link a lesson may carry.
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
// A file name from a title, cut at a word rather than mid-word when the title is long.
export const slug = (s) => {
  const full = fold(s || "lesson").replace(/['’]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return (full.length > 60 ? full.slice(0, 61).replace(/-[^-]*$/, "") || full.slice(0, 60) : full) || "lesson";
};

// Lower case without accents, so "poincare" finds "Poincaré".
export const fold = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
