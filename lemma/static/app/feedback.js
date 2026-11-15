/* Feedback, from signed-in accounts only: the one form (a page, the end of a lesson, under an error or a stopped build),
   the #/feedback page, and the admins' inbox. */
import { api, busy, errorBox, h, holdIntent, icon, plural, setHash, setTitle, status, view, when } from "./shell.js";
import { ask } from "./library.js";
import { showSignIn } from "./account.js";
import { lastRoute } from "./main.js";

/* Feedback goes to the people who run OpenLemma, from signed-in accounts only, said where it was asked for:
   the #/feedback page, the end of a lesson, or under an error or a stopped build. The same form everywhere:
   an optional rating, an optional message (one of them is needed, as the server checks), the address a
   reply would go to, then Send. Once sent it gives way to a thank-you line. */
const FB_MAX = 2000, FB_COUNT_FROM = 1700;  // the server's limit, and where the count starts to show
export const pageOf = (hash) => (hash || "").split("?")[0].slice(0, 300);  // where they were, without any search words
let fbSeq = 0;
export function feedbackForm(ctx, { variant = "page", onCancel = null, onSent = null } = {}) {
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
export function reportThis(ctx) {
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
export function lessonFeedback(lesson) {
  const ctx = { kind: "lesson", page: pageOf(location.hash), lesson_title: String(lesson.title || "").slice(0, 300) };
  if (/^[A-Za-z0-9_-]{1,64}$/.test(lesson.id || "")) ctx.lesson_id = lesson.id;
  return h("section", { class: "fb-lesson", "aria-label": "Feedback on this lesson" }, feedbackForm(ctx, { variant: "lesson" }));
}

/* ------------------------------------------------------------ the feedback page and the inbox */

/* #/feedback: the form on its own page, from the footer. Signed out, it asks you to sign in and brings you back. */
export function showFeedback() {
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
export function showInbox() {
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
