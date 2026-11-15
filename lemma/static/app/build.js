/* From outline to lesson: connecting a provider, reviewing the outline, and the build page (its progress, and a stopped
   build's choice to continue or start over). */
import { api, buildProgress, busy, ERROR_ID, errorBox, h, icon, plural, session, setHash, setPollTimer, setTitle, status, view } from "./shell.js";
import { keyForm } from "./provider.js";
import { showHome, showMake } from "./home.js";
import { alertInline, openLesson } from "./learn.js";

/* Connect an AI provider: shown the first time an AI step is needed, then the flow carries on. */
export function showConnect(then) {
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

export const STOPPED_TITLES = { error: "This build stopped", interrupted: "This build was interrupted", cancelled: "You cancelled this build" };
const STOPPED_STATES = Object.keys(STOPPED_TITLES);

/* A stopped build with an approved outline (`resume` from the server) carries on only as the learner chooses:
   continue it, keeping the outline and its finished concepts, or start over from a new outline. */
const modelName = (m) => `${m.name}${m.model ? ` (${m.model.replace(/-/g, "\u2011")})` : ""}`;  // non-breaking hyphens: a model's name never splits
// Said only when a model other than the learner's current one built the finished concepts; it blocks nothing.
export function keptByAnotherModel(resume) {
  const now = status.provider || {};
  const by = resume.built_with || [];
  if (!resume.kept || !now.ok || !by.some((m) => m.name !== now.name || m.model !== now.model)) return "";
  const all = by.length + (by.some((m) => m.name === now.name && m.model === now.model) ? 0 : 1);
  return `The ${plural(resume.kept, "finished concept")} ${resume.kept === 1 ? "was" : "were"} built with ${new Intl.ListFormat("en").format(by.map(modelName))}. `
    + `The rest will use ${modelName(now)}, your current model, and the lesson will name ${all === 2 ? "both" : "each of them"}.`;
}
// Sources that couldn't be read (`resume.excluded`, their titles): Continue builds without them; Start over tries them again.
const unread = (titles) => `${plural(titles.length, "source")} couldn't be read: ${new Intl.ListFormat("en").format(titles.map((t) => `“${t}”`))}.`;
export const theUnread = (titles) => `${titles.length === 1 ? "the source" : `the ${titles.length} sources`} that couldn't be read`;
function continueWords(resume) {
  const n = resume.kept, left = resume.total - n, from = (resume.excluded || []).length ? ", from the sources that were read" : "";
  if (!n) return `Builds the ${plural(resume.total, "concept")} in the outline you approved${from}, without reviewing it again.`;
  return `Keeps your approved outline and the ${plural(n, "finished concept")}, then ` + (left ? `builds the ${plural(left, "concept")} that's left${from}.` : "saves your lesson.");
}
const startOverWords = (n, excluded = []) => (excluded.length
  ? `Tries ${theUnread(excluded)} once more, then proposes a new outline from your sources for you to review.`
  : "Proposes a new outline from the same sources for you to review.") + (n ? ` The ${plural(n, "finished concept")} ${n === 1 ? "is" : "are"} deleted.` : "");
export const startOverQuestion = (n) => `Start over? The ${plural(n, "finished concept")} will be deleted. This can't be undone.`;

function resumeCard(s, retryWith) {
  const r = s.resume, n = r.kept;
  const why = { interrupted: "OpenLemma stopped before your lesson was finished.", error: "The build stopped before your lesson was finished.",
                cancelled: "You cancelled the build before your lesson was finished." }[s.status];
  const other = keptByAnotherModel(r);
  const cont = h("button", { class: "primary", onclick: () => retryWith("continue", cont) }, "Continue building");
  const start = h("div", { class: "resume-opt" });
  const drawStart = (asking) => {
    start.className = "resume-opt" + (asking ? " is-asking" : "");
    if (asking) {
      const yes = h("button", { class: "lib-yes", onclick: () => retryWith("start_over", yes) }, "Delete and start over");
      const no = h("button", { class: "ghost", onclick: () => { drawStart(false); start.querySelector("button").focus(); } }, "Keep them");
      start.onkeydown = (e) => { if (e.key === "Escape") { e.preventDefault(); no.click(); } };
      start.replaceChildren(h("p", { id: `resume-ask-${s.id}` }, startOverQuestion(n)), h("div", { class: "resume-ask-btns" }, yes, no));
      start.setAttribute("role", "group");
      start.setAttribute("aria-labelledby", `resume-ask-${s.id}`);
      no.focus();
    } else {
      start.onkeydown = null;
      start.removeAttribute("role");
      start.removeAttribute("aria-labelledby");
      const btn = h("button", { onclick: () => (n ? drawStart(true) : retryWith("start_over", btn)) }, "Start over");
      start.replaceChildren(btn, h("p", {}, startOverWords(n, r.excluded)));
    }
  };
  drawStart(false);
  return h("section", { class: "resume", "aria-labelledby": `resume-title-${s.id}` },
    h("h2", { id: `resume-title-${s.id}` }, "How would you like to carry on?"),
    h("p", { class: "resume-lead" }, `${why} ` + (n ? `Your approved outline and the ${plural(n, "finished concept")} are kept.` : "Your approved outline is kept. No concepts were finished yet.")
      + ((r.excluded || []).length ? ` ${unread(r.excluded)}` : "")),
    h("div", { class: "resume-opt" }, cont, h("p", {}, continueWords(r)),
      other ? h("p", { class: "resume-model" }, other + " ", h("a", { href: "#/settings" }, "Change model")) : null),
    start);
}

export function showRequest(id) {
  session.requestId = id;
  setHash(`#/request/${id}`);
  setTitle("Preparing your lesson");
  const title = h("h1", {}, "Preparing your lesson"), progress = buildProgress(), steps = progress.el, warnings = h("div"), errors = h("div");
  const eta = h("p", { class: "muted", role: "status" }, "Estimating time remaining…");
  const open = h("button", { class: "primary", disabled: true }, "Start the first concept"), choice = h("div");
  const cancel = h("button", { class: "ghost", onclick: async () => {
    try { await api(`/api/requests/${id}/cancel`, {}); showRequest(id); } catch (e) { errors.replaceChildren(errorBox(e.message)); }
  } }, "Cancel build");
  // `mode` is the learner's choice for a build with an approved outline ("continue" or "start_over"); null otherwise.
  const retryWith = async (mode, btn) => {
    const begin = async () => {
      if (btn) busy(btn, true);
      try { await api(`/api/requests/${id}/retry`, mode ? { mode } : {}); showRequest(id); }
      catch (e) { if (btn) busy(btn, false); errors.replaceChildren(errorBox(e.message)); }
    };
    if (!(status.provider || {}).ok) return showConnect(begin);  // the choice carries through: no second question
    await begin();
  };
  const retry = h("button", { class: "primary", hidden: true, onclick: () => retryWith(null, retry) }, "Retry build");
  view(h("section", { class: "panel" }, title,
    h("p", { class: "muted" }, "You can leave this page and come back with this link or from your Library. Finished lessons are saved automatically."),
    eta, errors, choice, steps, warnings, h("div", { class: "actions" }, open, cancel, retry, h("a", { href: "#/library", class: "btn ghost" }, "Library"))));
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
      const stopped = STOPPED_STATES.includes(s.status), choosing = stopped && !!s.resume;
      progress.update(s.steps || [], s.now, stopped ? (choosing ? "Stopped before any concept was built" : "Stopped before the outline was ready") : "");
      warnings.replaceChildren(...(s.warnings || []).map((w) => h("p", { class: "note" }, typeof w === "string" ? w : JSON.stringify(w))));
      // A build that stopped with an error can be reported from here, with the build's id.
      // With a choice to make, the card says why it stopped, unless it was an error, which keeps its box and "Report this".
      errors.replaceChildren(s.error && s.status !== "cancelled" && !(choosing && s.status === "interrupted") ? errorBox(s.error, null, s.status === "error" && /^[0-9a-f]{12}$/.test(id)
        ? { kind: "build", request_id: id, error_id: (s.error.match(ERROR_ID) || [])[1] } : null) : "");
      choice.replaceChildren(choosing ? resumeCard(s, retryWith) : "");
      eta.hidden = choosing;
      eta.textContent = s.status !== "running" ? (s.status === "done" ? "Checked and saved to your library." : "You can retry with the same source selections.")
        : s.eta_seconds ? `About ${Math.max(1, Math.ceil(s.eta_seconds[0] / 60))}–${Math.max(1, Math.ceil(s.eta_seconds[1] / 60))} minutes left. Concepts that need fixing can take longer.` : "Estimating time remaining…";
      open.disabled = !s.lesson?.concepts?.length && s.status !== "done";
      open.textContent = s.status === "done" ? "Open lesson" : "Start the first concept";
      open.className = choosing ? "" : "primary";  // one primary on the page: with a choice to make, it's Continue building
      open.onclick = () => openLesson(s.status === "done" ? s.result : s.lesson, s.status === "done" ? { saved: true } : { live: id, request: true });
      cancel.hidden = s.status !== "running";
      retry.hidden = !stopped || choosing;
      if (s.status === "running") setPollTimer(setTimeout(poll, 1500));
    } catch (e) {
      errors.replaceChildren(errorBox(e.message), h("button", { class: "small", onclick: poll }, "Reconnect"));
    }
  };
  poll();
}
