/* Learning: the player for a lesson, where the learner left off (kept in this browser, progress.js), saving, downloads,
   and the film. */
import { api, cleanups, download, errorBox, ext, h, icon, main, player, session, setHash, setPlayer, setPollTimer, setTitle, slug, status, view } from "./shell.js";
import { lessonFeedback } from "./feedback.js";
import { showHome } from "./home.js";
import { showRequest, STOPPED_TITLES } from "./build.js";
import { showEditor } from "./editor.js";
import { showReview } from "./sharing.js";

// Where the learner is in each lesson, kept in this browser only, per account (see progress.js).
const Progress = window.LemmaProgress;
const localStore = () => { try { return window.localStorage; } catch (e) { return null; } };
const progressKey = (lessonKey) => Progress.storageKey(status.user && status.user.id, lessonKey);
const savedProgress = (lessonKey) => Progress.load(localStore(), progressKey(lessonKey));
/* The player's hook: load, save and clear this lesson's place. For someone else's shared lesson, each save that moves
   the reader on also tells the author how far they got (never what they answered). */
function progressHook(lesson) {
  const key = progressKey(Progress.lessonKey(lesson));
  const sh = lesson.shared && !lesson.shared.owner ? lesson.shared : null;
  let told = null;
  return {
    load: () => Progress.load(localStore(), key),
    save: (state) => {
      Progress.save(localStore(), key, state);
      if (!sh) return;
      // Starting is what records the reader; `anonymous` carries what they were told when they opened it.
      const report = { ...Progress.report(state, lesson), anonymous: !sh.named }, said = JSON.stringify(report);
      if (said === told) return;
      told = said;
      api(`/api/shared/${sh.token}/progress`, report, "POST", {}).catch(() => { told = null; });
    },
    clear: () => Progress.clear(localStore(), key),
  };
}
// A library line for a lesson's saved place: "Concept 2 of 4" with its bar, or "Completed".
export function progressLine(lessonKey) {
  const b = Progress.brief(savedProgress(lessonKey));
  if (b.status === "finished") return h("p", { class: "lib-progress is-done" }, icon("check"), "Completed");
  if (b.status === "primer") return h("p", { class: "lib-progress" }, "Reading the idea in brief");
  if (b.status !== "started") return null;
  return h("p", { class: "lib-progress" }, progressSegments(b.total, b.concept), `Concept ${b.concept} of ${b.total}`);
}
export function progressSegments(total, at, finished) {
  return h("span", { class: "prog-bar", "aria-hidden": "true" },
    Array.from({ length: Math.min(total, 12) }, (_, i) => h("i", { class: finished || i < at - 1 ? "done" : i === at - 1 ? "cur" : "" })));
}

export function openLesson(lesson, opts = {}) {
  view();
  const shared = lesson.shared || null, mine = !shared && !lesson.example && !!opts.saved && !opts.preview;
  setHash(shared ? (opts.review ? location.hash : `#/shared/${shared.token}`) : opts.request ? `#/request/${opts.live}/learn` : lesson.gallery ? `#/gallery/${lesson.gallery.slug}` : lesson.example ? "#/example" : opts.saved ? `#/lesson/${lesson.id}` : "#/learn");
  setTitle(lesson.title || "Lesson");
  const host = h("div", { class: "player-host" });
  main.replaceChildren(host);
  setPlayer(LemmaPlayer.mount(host, lesson, {
    onExit: () => (opts.review ? showReview() : shared ? (location.hash = status.user ? "#/library" : "#/gallery") : showHome()),
    // Library lessons and finished builds are saved already; a built-in or shared lesson can't be saved at all.
    onSave: lesson.example || shared || opts.saved || opts.request ? null : saveLesson,
    saved: !!opts.saved && !opts.preview,
    // A shared lesson downloads only if its author allows it (the server checks again).
    onDownload: shared ? (shared.downloadable || shared.owner ? downloadShared : null) : downloadLesson,
    onEdit: lesson.example || shared ? null : (l) => showEditor(l),
    onShare: mine ? (l) => { location.hash = `#/share/${l.id}`; } : null,
    progress: opts.review ? null : progressHook(lesson),  // an admin's preview keeps no place
    onOwnPaper: lesson.example ? () => showHome() : null,
    onEvent: (name) => { api("/api/event", { name }, "POST", {}).catch(() => {}); },
    feedback: status.user ? lessonFeedback : null,  // signed in only; a downloaded lesson is mounted without it
  }));
  if (opts.live) {
    const jobId = opts.live;
    const activePlayer = player;
    const poll = async () => {
      let s;
      try { s = await api(`/api/${opts.request ? "requests" : "jobs"}/${jobId}`); } catch (e) { return; }
      if (player !== activePlayer) return;
      if (s.status === "running") { player.update(s.lesson); setPollTimer(setTimeout(poll, 1500)); }
      else if (s.status === "done") { session.lesson = s.result; player.update(s.result); }
      else if (["error", "cancelled", "interrupted"].includes(s.status)) {
        if (s.lesson) { const l = Object.assign({}, s.lesson); delete l.plan; player.update(l); }
        const reason = s.status === "error" && s.error ? ` ${s.error}` : "";
        if (s.resume && s.resume.kept) alertInline(`${STOPPED_TITLES[s.status]}. The concepts it finished are kept. Continue it or start over from the build's page.${reason}`,
          null, { label: "Continue or start over", run: () => showRequest(jobId) });
        else alertInline(`${STOPPED_TITLES[s.status] || "This build stopped"}. You can retry it from your Library.${s.status !== "cancelled" && s.error ? ` ${s.error}` : ""}`);
      }
    };
    setPollTimer(setTimeout(poll, 1500));
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

// `action` ({label, run}) adds a way to deal with it, beside Dismiss.
export function alertInline(msg, problems, action) {
  const box = errorBox(msg, problems);
  box.classList.add("floating");
  const dismiss = h("button", { class: "small", onclick: () => box.remove() }, "Dismiss");
  box.append(action ? h("div", { class: "floating-acts" }, h("button", { class: "small", onclick: () => { box.remove(); action.run(); } }, action.label), dismiss) : dismiss);
  document.body.append(box);
}

// The offline file, named after the lesson's title.
export async function exportLesson(lesson) {
  const res = await fetch("api/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lesson }) });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.error || `Download failed (${res.status}). Try again in a moment.`);
  download(`${slug(lesson.title)}.html`, await res.text());
}
async function downloadLesson(lesson) {
  try { await exportLesson(lesson); } catch (err) { alertInline(err.message); }
}
// A shared lesson's offline file, made by the server from the lesson as its author saved it.
export async function exportShared(token, title) {
  const res = await fetch("api/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ shared: token }) });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.error || `Download failed (${res.status}). Try again in a moment.`);
  download(`${slug(title)}.html`, await res.text());
}
async function downloadShared(lesson) {
  try { await exportShared(lesson.shared.token, lesson.title); } catch (err) { alertInline(err.message); }
}

/* The film: embedded in the hero, loaded and played only when the visitor presses play. */
const FILM = { hd: "static/film-v6-1080.mp4", sd: "static/film-v6-720.mp4", poster: "static/film-v6-poster.jpg" };
export function filmPlayer() {
  const video = h("video", { class: "film-video", preload: "none", poster: FILM.poster, playsinline: true, "aria-label": "OpenLemma film, 37 seconds, with music" });
  const status = h("p", { class: "film-status", role: "status" });
  const start = () => {
    if (!video.src) video.src = matchMedia("(max-width: 900px)").matches ? FILM.sd : FILM.hd;
    video.controls = true;
    cover.hidden = after.hidden = true;
    video.play().catch(() => {});  // some browsers refuse; the native controls are there now
  };
  const cover = h("button", { type: "button", class: "film-cover", onclick: start, "aria-label": "Play the 37-second OpenLemma film (with music)" },
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

export async function openExample() { try { openLesson(await api("/api/example")); } catch (err) { showHome(err.message); } }
