/* The library: the account's lessons and builds, with their progress, sharing and the row actions. */
import { api, busy, fold, h, icon, main, plural, setPollTimer, setTitle, status, stopPolling, view, when } from "./shell.js";
import { feedbackForm } from "./feedback.js";
import { keptByAnotherModel, showConnect, showRequest, startOverQuestion, theUnread } from "./build.js";
import { alertInline, exportLesson, exportShared, progressLine } from "./learn.js";
import { showEditor } from "./editor.js";

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

/* Choose inside a stopped build's row: continue it or start over, in a neutral wash. Starting over with finished
   concepts asks once more, in red, before deleting them. Escape or "Not now" puts the row back. */
function choose(li, opener, r, start) {
  const acts = li.querySelector(".lib-acts"), n = r.resume.kept;
  li.querySelector(".lib-msg").hidden = true;
  const qid = `choose-${li.dataset.key.replace(/\W/g, "")}`;
  const box = h("div", { class: "lib-choice", role: "group", "aria-labelledby": qid });
  const close = () => { li.classList.remove("is-choosing", "is-asking"); box.remove(); acts.hidden = false; opener.focus(); };
  const draw = (confirming) => {
    li.classList.toggle("is-choosing", !confirming);
    li.classList.toggle("is-asking", confirming);
    const other = keptByAnotherModel(r.resume);
    if (confirming) {
      const yes = h("button", { type: "button", class: "small lib-yes", onclick: () => start("start_over", yes) }, "Delete and start over");
      const no = h("button", { type: "button", class: "small ghost", onclick: () => draw(false) }, "Keep them");
      box.onkeydown = (e) => { if (e.key === "Escape") { e.preventDefault(); draw(false); } };
      box.replaceChildren(h("p", { id: qid }, startOverQuestion(n)), h("div", { class: "lib-choice-btns" }, yes, no));
      no.focus();
    } else {
      const cont = h("button", { type: "button", class: "small primary", onclick: () => start("continue", cont) }, "Continue building");
      const over = h("button", { type: "button", class: "small", onclick: () => (n ? draw(true) : start("start_over", over)) }, "Start over");
      box.onkeydown = (e) => { if (e.key === "Escape") { e.preventDefault(); close(); } };
      box.replaceChildren(
        h("p", { id: qid }, (n ? `Continue with your approved outline and the ${plural(n, "finished concept")}, or start over with a new outline?`
          : "Continue with your approved outline, or start over with a new outline?")
          + ((r.resume.excluded || []).length ? ` Starting over tries ${theUnread(r.resume.excluded)} once more.` : "")),
        other ? h("p", { class: "resume-model" }, other) : null,
        h("div", { class: "lib-choice-btns" }, cont, over, h("button", { type: "button", class: "small ghost", onclick: close }, "Not now")));
      cont.focus();
    }
  };
  acts.hidden = true;
  li.append(box);
  draw(false);
}

/* Ask inside the row: the question, the action in red and a way out. Escape or "Keep" puts the row back. */
export function ask(li, opener, { question, yes, busyText, no, act }) {
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

export function showLibrary() {
  const q0 = new URLSearchParams(location.hash.split("?")[1] || "").get("q") || "";
  const live = h("p", { class: "sr-only", role: "status" });
  const body = h("div", { class: "lib-body", "aria-busy": "true" });
  setTitle("Library");
  view(h("section", { class: "lib", "aria-labelledby": "lib-title" },
    h("div", { class: "lib-head" }, h("h1", { id: "lib-title" }, "Library"),
      h("p", { class: "lead" }, "Every lesson you build is saved here. Download any one as a single file that works offline and sends nothing anywhere.")),
    body, live));
  let lessons = [], builds = [], sharedWithMe = [], rows = [], countEl = null, noneEl = null;
  const findIn = h("input", { type: "search", id: "lib-find", value: q0, placeholder: "Title, source or subject", autocomplete: "off", spellcheck: "false", maxlength: 80 });
  const say = (msg) => { live.textContent = ""; setTimeout(() => { live.textContent = msg; }, 60); };

  async function load() {
    const [ls, rs, sw] = await Promise.all([api("/api/lessons"), api("/api/requests"), api("/api/shared").catch(() => sharedWithMe)]);
    lessons = ls;
    sharedWithMe = sw;
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
        h("p", { class: "lib-meta" }, h("span", { class: "lib-state" }, st.says),
          r.resume && r.resume.kept ? h("span", {}, `${r.resume.kept} of ${r.resume.total} concepts kept`) : null,
          r.created ? h("span", {}, "Started ", when(r.created, true)) : null)),
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
          question: "Cancel this build? The concepts it has finished are kept, so you can continue it later.", yes: "Cancel build", busyText: "Cancelling…", no: "Keep building",
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
      // `mode` is the learner's choice for a build with an approved outline; null for one without.
      const start = async (mode, btn) => {
        const begin = async () => {
          try { await api(`/api/requests/${r.id}/retry`, mode ? { mode } : {}); showRequest(r.id); }
          catch (err) { if (body.isConnected) refuse(key, err.message); else alertInline(err.message); }
        };
        if (!(status.provider || {}).ok) return showConnect(begin);
        busy(btn, true);
        await begin();
        busy(btn, false);
      };
      const retry = h("button", { type: "button", class: "small", onclick: () => (r.resume ? choose(li, retry, r, start) : start(null, retry)) },
        icon("refresh"), "Retry build");
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
        h("p", { class: "lib-meta" }, it.category ? h("span", {}, it.category) : null, h("span", { class: "lib-num" }, plural(it.concepts, "concept")), h("span", {}, "Saved ", when(it.saved)),
          shareTag(it.shared)),
        progressLine(`lesson:${it.id}`)),
      h("div", { class: "lib-acts" },
        h("a", { class: "btn small ghost", href: `#/share/${it.id}`, "aria-label": `Share “${title}”`, onclick: () => { libraryReturn = it.id; } }, icon("share"), h("span", {}, "Share")),
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

  // How a lesson is shared, beside when it was saved: by link, waiting for the gallery's review, or listed.
  function shareTag(sh) {
    if (!sh) return null;
    const readers = plural(sh.readers, "reader");
    const says = { listed: `Listed in the gallery · ${readers}`, waiting: "Shared · waiting for gallery review" }[sh.listing] || `Shared by link · ${readers}`;
    return h("span", { class: "lib-share-tag" + (sh.listing === "waiting" ? " is-waiting" : "") }, icon(sh.listing === "waiting" ? "clock" : "link"), says);
  }

  /* "Shared with you": shared lessons this account opened, with how far it got in each (kept in this browser). */
  function sharedRow(it) {
    const key = `s:${it.token}`, title = it.title || "Untitled lesson";
    const li = h("li", { class: "lib-row lib-lesson lib-shared-row", "data-key": key },
      h("div", { class: "lib-text" },
        h("h3", { class: "lib-title" }, h("a", { class: "lib-open", href: `#/shared/${it.token}` }, title)),
        it.source ? h("p", { class: "lib-source" }, it.source) : null,
        h("p", { class: "lib-meta" }, it.author ? h("span", {}, `Shared by ${it.author}`) : null, h("span", { class: "lib-num" }, plural(it.concepts, "concept")),
          h("span", {}, "Opened ", when(it.opened))),
        progressLine(`shared:${it.share}`)),
      h("div", { class: "lib-acts" },
        it.downloadable ? h("button", { type: "button", class: "small ghost", "aria-label": `Download “${title}” as one offline file`, onclick: async (e) => {
          const b = e.currentTarget;
          busy(b, true);
          try { await exportShared(it.token, title); say(`Downloaded “${title}”.`); } catch (err) { showMsg(li, err.message); }
          busy(b, false);
        } }, icon("down"), h("span", {}, "Download")) : null,
        h("button", { type: "button", class: "small ghost", "aria-label": `Remove “${title}” from this list`, onclick: async () => {
          // Off the list at once; if the server refuses, the list is drawn again as it is, with the reason in the row.
          sharedWithMe = sharedWithMe.filter((x) => x.token !== it.token);
          draw();
          focusRow(null);
          try { await api(`/api/shared/${it.token}/hide`, {}); } catch (err) { return refuse(key, err.message); }
          say(`Removed “${title}” from your list. The link still works.`);
        } }, "Remove")),
      h("p", { class: "lib-msg", role: "alert", hidden: true }));
    return li;
  }
  function sharedSection() {
    if (!sharedWithMe.length) return null;
    return h("section", { class: "lib-sec lib-shared", "aria-labelledby": "lib-shared-title" },
      h("div", { class: "lib-sec-head" }, h("h2", { id: "lib-shared-title" }, "Shared with you"), h("span", { class: "lib-count" }, String(sharedWithMe.length))),
      h("ul", { class: "lib-list" }, sharedWithMe.map(sharedRow)));
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

  let drawn = "";  // the signature of what the list shows
  function draw() {
    drawn = signature();
    // Redrawn in place, so focus stays on the same control of the same row wherever it still exists.
    const at = document.activeElement, atRow = at?.closest?.("[data-key]");
    const keep = atRow && body.contains(atRow) ? [atRow.dataset.key, [...atRow.querySelectorAll("a, button")].indexOf(at)] : null;
    const inFind = at === findIn, caret = inFind ? findIn.selectionStart : 0;
    body.removeAttribute("aria-busy");
    if (!lessons.length && !builds.length) {
      rows = [];
      body.replaceChildren(h("div", { class: "lib-empty" },
        h("h2", {}, "No saved lessons yet"),
        h("p", {}, "Ask about a concept or bring a source. OpenLemma builds a short lesson with a live model for each idea, usually within a few minutes, and keeps it here."),
        h("div", { class: "actions" },
          h("a", { class: "btn primary", href: "#/make" }, "New lesson"),
          h("a", { class: "btn ghost", href: "#/example" }, icon("play"), "Try the example lesson"))), sharedSection() || "");
    } else {
      const buildsSec = builds.length ? h("section", { class: "lib-sec lib-builds", "aria-labelledby": "lib-builds-title" },
        h("div", { class: "lib-sec-head" }, h("h2", { id: "lib-builds-title" }, "In progress"), h("span", { class: "lib-count" }, String(builds.length))),
        h("ul", { class: "lib-list" }, builds.map(buildRow))) : null;
      body.replaceChildren(h("div", { class: "lib-grid" + (buildsSec ? "" : " is-solo") }, lessonsSection(), buildsSec), sharedSection() || "");
      apply(true);
    }
    if (keep) {
      const li = body.querySelector(`[data-key="${keep[0]}"]`);
      const el = li && ([...li.querySelectorAll("a, button")][keep[1]] || li.querySelector(".lib-open"));
      if (el) el.focus({ preventScroll: true });
    } else if (inFind && findIn.isConnected) { findIn.focus({ preventScroll: true }); findIn.setSelectionRange(caret, caret); }
    stopPolling();
    if (builds.some((r) => r.status === "running")) setPollTimer(setTimeout(poll, 4000));
  }
  const reload = async () => { try { await load(); } catch (e) { /* keep what's shown */ } draw(); };

  // While a build runs, check on it, and redraw only when something changed and no question is open. It compares
  // with what was last drawn, not last loaded, so a change that arrives while a question is open is drawn once it closes.
  const signature = () => builds.map((r) => r.id + r.status).join() + "|" + lessons.map((l) => l.id).join() + "|" + sharedWithMe.map((x) => x.token).join();
  async function poll() {
    if (!body.isConnected) return;
    try { await load(); } catch (e) { setPollTimer(setTimeout(poll, 8000)); return; }
    if (!body.isConnected) return;
    if (signature() !== drawn && !body.querySelector(".is-asking, .is-choosing, .is-reporting")) draw();
    else setPollTimer(setTimeout(poll, 4000));
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
