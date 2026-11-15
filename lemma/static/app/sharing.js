/* Sharing: a reader's link (signing in for it, or its end), the author's Share page with what readers did, and the
   admins' gallery review. */
import { $, api, busy, errorBox, h, holdIntent, icon, plural, setTitle, status, view, when } from "./shell.js";
import { showHome } from "./home.js";
import { alertInline, openLesson, progressSegments } from "./learn.js";
import { googleButton, showSignIn } from "./account.js";

// A reader's link, #/shared/<token>. Signed out, it asks to sign in, naming the lesson, and comes back here after.
export async function openShared(token) {
  if (!status.user) return showSharedSignIn(token);
  setTitle("Opening the lesson");
  view(h("section", { class: "shared-loading", role: "status", "aria-live": "polite" }, h("div", { class: "spinner", "aria-hidden": "true" }), h("p", {}, "Opening the lesson…")));
  try { openLesson(await api(`/api/shared/${token}`)); }
  catch (err) { if (err.status === 404) showSharedGone(); else if (err.status !== 401) showHome(err.message); }
}

async function showSharedSignIn(token) {
  holdIntent({ route: `#/shared/${token}` });
  let about;
  try { about = await api(`/api/shared/${token}/about`); } catch (err) { return err.status === 404 ? showSharedGone() : showSignIn(err.message); }
  const who = about.author || "Someone", options = status.sign_in || [];
  const point = (text) => h("li", {}, h("span", { class: "signin-tick", "aria-hidden": "true" }, icon("check")), text);
  setTitle("Sign in to read this lesson");
  view(h("section", { class: "signin", "aria-labelledby": "signin-title" },
    h("div", { class: "signin-card" },
      $(".site-head .logo").cloneNode(true),
      h("h1", { id: "signin-title" }, "Sign in to read this lesson"),
      h("p", { class: "signin-lead" }, `${who} shared a lesson with you. You'll go straight to it after signing in.`),
      h("div", { class: "signin-lesson" }, h("p", { class: "t" }, about.title),
        h("p", { class: "m" }, [plural(about.concepts, "concept"), about.category].filter(Boolean).join(" · "))),
      options.length
        ? h("div", { class: "signin-options" }, options.map((p) => p.id === "google" ? googleButton()
            : h("a", { class: "btn" + (p.id === options[0].id ? " primary" : ""), href: `auth/${p.id}/start` }, p.label)))
        : errorBox("Signing in isn't set up on this server yet."),
      h("ul", { class: "signin-points" },
        point("Reading is free. You don't need an AI provider key."),
        point("Your place is remembered in this browser, so you can stop and come back."),
        point(about.named ? `Once you start, ${about.author || "the author"} will see your name and how far you get.` : "The author sees only how many readers reach each concept, not who.")),
      h("p", { class: "signin-fine" }, "OpenLemma keeps your name, email address and picture, and asks Google for nothing else. ", h("a", { href: "privacy" }, "Privacy"))),
    h("p", { class: "signin-alt" }, "Not ready yet? ", h("a", { href: "#/example" }, "Try the example lesson"), ", with no account or key.")));
}

function showSharedGone() {
  setTitle("No longer shared");
  view(h("section", { class: "lib-empty shared-gone", "aria-labelledby": "gone-title" },
    h("h1", { id: "gone-title" }, "This lesson is no longer shared"),
    h("p", {}, "Whoever shared it has turned the link off, or shared it again with a new link. Ask them for the new one."),
    h("div", { class: "actions" }, h("a", { class: "btn primary", href: "#/gallery" }, "Open the gallery"), h("a", { class: "btn ghost", href: "#/" }, "Go to the home page"))));
}

/* #/share/<lesson>: the author's page. Who can read it (the link and three choices), then who has, by name, or, while
   it's listed in the gallery, totals only. Before sharing, the choices wait for "Share lesson"; after, each saves at once. */
const LISTING = {
  waiting: { cls: "wait", icon: "clock", says: "Waiting for review" },
  listed: { cls: "listed", icon: "check", says: "Listed" },
  rejected: { cls: "no", icon: "cross", says: "Not approved" },
};
export async function showShare(lessonId) {
  if (!status.user) { holdIntent({ route: location.hash }); return showSignIn(); }
  setTitle("Share lesson");
  let lesson, settings;
  try { [lesson, settings] = await Promise.all([api(`/api/lessons/${lessonId}`), api(`/api/lessons/${lessonId}/share`)]); }
  catch (err) { return showHome(err.message); }
  const page = h("div", { class: "account share-page" });
  const choice = { show_author: settings.show_author, downloadable: settings.downloadable, listed: settings.listing !== "none" };
  const saved = h("p", { class: "share-saved", role: "status" });
  let saving = 0;

  async function change(key, value) {
    choice[key] = value;
    if (!settings.shared) return;  // saved when the lesson is shared
    saving++;
    saved.textContent = "Saving…";
    try {
      settings = await api(`/api/lessons/${lessonId}/share`, { [key]: value });
      if (--saving === 0) { saved.textContent = "Saved."; draw(true); }
    } catch (err) { saving = 0; saved.textContent = ""; page.querySelector(".share-card").append(errorBox(err.message)); }
  }
  function option(key, name, tagline, status_) {
    const box = h("input", { type: "checkbox", checked: !!choice[key], onchange: (e) => change(key, e.target.checked) });
    return h("label", { class: "share-opt" }, box, h("span", { class: "po-body" }, h("span", { class: "po-name" }, name), h("span", { class: "po-tagline" }, tagline)), status_ || null);
  }
  function options() {
    const l = LISTING[settings.shared ? settings.listing : "none"];
    const me = status.user.name || "your name";
    return h("div", { class: "share-opts" },
      option("show_author", "Show my name", `Readers see “Shared by ${me}”.`),
      option("downloadable", "Let readers download it", "They can keep a copy that works offline. Readers' browsers receive the lesson to play it, so leaving this off discourages copying rather than preventing it."),
      option("listed", "Also list it in the gallery",
        settings.listing === "rejected" && settings.shared ? "OpenLemma didn't list this lesson. It's still shared by link. Untick this, edit the lesson, and tick it again to ask again."
          : "Anyone can find it there. OpenLemma reviews it before it appears, and again after you edit it. While it's listed, you see totals only, not who read it.",
        l ? h("span", { class: `share-status ${l.cls}` }, icon(l.icon), l.says) : null));
  }
  function shareCard() {
    const card = h("section", { class: "account-card share-card", "aria-labelledby": "share-card-title" }, h("h2", { id: "share-card-title" }, "Who can read it"));
    if (!settings.shared) {
      const go = h("button", { class: "primary", onclick: async () => {
        busy(go, true);
        try { settings = await api(`/api/lessons/${lessonId}/share`, choice); draw(); }
        catch (err) { busy(go, false); card.append(errorBox(err.message, err.problems)); }
      } }, icon("link"), "Share lesson");
      card.append(h("p", { class: "share-lead" }, "Anyone with the link can read it once they sign in to OpenLemma. Readers can't edit it, and never see your sources' text."),
        options(),
        h("p", { class: "share-fine" }, "You'll see the names of people who start reading from your link and how far they get. They're told this before they start."),
        h("div", { class: "actions" }, go, h("a", { class: "btn ghost", href: "#/library" }, "Cancel")));
      return card;
    }
    const link = `${location.origin}${location.pathname}#/shared/${settings.token}`;
    const input = h("input", { type: "text", id: "share-link", readonly: true, value: link, onfocus: (e) => e.target.select() });
    const copy = h("button", { type: "button", onclick: async () => {
      let ok = false;
      try { await navigator.clipboard.writeText(link); ok = true; } catch (e) {
        input.focus(); input.select();
        try { ok = document.execCommand("copy"); } catch (e2) { ok = false; }
      }
      copy.replaceChildren(icon(ok ? "check" : "copy"), ok ? "Copied" : "Press Ctrl+C to copy");
      setTimeout(() => { if (copy.isConnected) copy.replaceChildren(icon("copy"), "Copy link"); }, 2500);
    } }, icon("copy"), "Copy link");
    const listed = settings.listing === "listed";
    const stop = h("button", { type: "button", class: "small danger", onclick: () => ask() }, "Stop sharing");
    const foot = h("div", { class: "share-foot" }, stop);
    function ask() {
      const back = () => { box.remove(); stop.hidden = false; stop.focus(); };
      const keep = h("button", { type: "button", class: "ghost", onclick: back }, "Keep sharing");
      const yes = h("button", { type: "button", class: "share-yes", onclick: async () => {
        busy(yes, true); keep.disabled = true;
        try { settings = await api(`/api/lessons/${lessonId}/share`, undefined, "DELETE"); choice.listed = false; draw(); }
        catch (err) { busy(yes, false); keep.disabled = false; box.append(errorBox(err.message)); }
      } }, "Stop sharing");
      const box = h("div", { class: "share-ask", role: "group", "aria-labelledby": "share-ask-q", onkeydown: (e) => { if (e.key === "Escape") { e.preventDefault(); back(); } } },
        h("p", { id: "share-ask-q" }, `Stop sharing this lesson? The link stops working straight away${listed || settings.listing === "waiting" ? ", and it leaves the gallery" : ""}. If you share it again, it gets a new link.`),
        h("div", { class: "share-ask-btns" }, yes, keep));
      stop.hidden = true;
      foot.append(box);
      keep.focus();
    }
    card.append(
      h("div", { class: "ai-state on", role: "status" }, h("span", { class: "ai-state-mark", "aria-hidden": "true" }, icon("check")),
        h("p", {}, h("strong", {}, listed ? "Shared and listed. " : "Shared. "),
          listed ? "Anyone can find it in the gallery, and anyone with the link can read it after signing in." : "Anyone with the link can read it after signing in.")),
      h("div", { class: "share-link" }, h("label", { class: "sr-only", for: "share-link" }, "Link to the lesson"), input, copy),
      options(), saved, foot);
    return card;
  }
  function readersCard() {
    const r = settings.readers;
    if (!settings.shared && !r.count) return null;
    const tile = (label, n) => h("div", { class: "share-tile" }, h("dt", {}, label), h("dd", {}, String(n)));
    const card = h("section", { class: "account-card share-readers", "aria-labelledby": "share-readers-title" },
      h("h2", { id: "share-readers-title" }, "Readers", h("span", { class: "lib-count" }, String(r.count))));
    if (!r.count) {
      card.append(h("p", { class: "share-none" }, "No one has started reading it yet."));
      return card;
    }
    card.append(h("dl", { class: "share-tiles" }, tile("Started", r.count), tile("Reading", r.reading), tile("Finished", r.finished)));
    if (!r.named) {
      const top = Math.max(1, ...r.by_concept.map((c) => c.reached));
      card.append(h("h3", {}, "How far readers got"),
        h("ul", { class: "share-funnel" }, r.by_concept.map((c, i) => h("li", {},
          h("span", { class: "sf-title" }, `${i + 1} · ${c.title}`), h("span", { class: "sf-n" }, String(c.reached)),
          h("span", { class: "sf-bar", "aria-hidden": "true" }, h("i", { style: `width:${Math.round((c.reached / top) * 100)}%` }))))),
        h("p", { class: "share-fine" }, "While it's listed in the gallery, you see totals only, so nobody who found it there is named. Your own reading isn't counted."));
      return card;
    }
    const line = (p) => p.completed ? h("span", { class: "lib-progress is-done" }, icon("check"), "Completed")
      : p.reached ? h("span", { class: "lib-progress" }, progressSegments(p.total, p.reached), `Concept ${p.reached} of ${p.total}`)
      : h("span", { class: "lib-progress is-fresh" }, "Not started");
    card.append(r.people.length ? h("ul", { class: "share-people" }, r.people.map((p) => h("li", { class: "share-reader" },
        h("span", { class: "avatar", "data-initial": (p.name || "?")[0], "aria-hidden": "true" }),
        h("div", {}, h("p", { class: "share-reader-name" }, p.name), h("p", { class: "share-reader-when" }, p.reached || p.completed ? "Last read " : "Opened ", when(p.last))),
        line(p)))) : null,
      h("p", { class: "share-fine" }, "People who started reading from your link, most recent first. Your own reading isn't counted."
        + (r.others ? ` ${plural(r.others, "more reader")} found it in the gallery, so ${r.others === 1 ? "isn't" : "aren't"} named.` : "")));
    return card;
  }
  function draw(keepFocus) {
    const at = keepFocus && document.activeElement && page.contains(document.activeElement) ? [...page.querySelectorAll("input, button, a")].indexOf(document.activeElement) : -1;
    page.replaceChildren(
      h("a", { class: "btn ghost small share-back", href: "#/library" }, icon("back"), "Library"),
      h("div", { class: "share-head" }, h("h1", { id: "share-title" }, "Share this lesson"),
        h("p", { class: "lead" }, h("strong", {}, lesson.title || "Untitled lesson"), " · ", h("span", { class: "share-count" }, plural((lesson.concepts || []).length, "concept")))),
      shareCard(), readersCard());
    if (at >= 0) [...page.querySelectorAll("input, button, a")][at]?.focus({ preventScroll: true });
    else page.querySelector("h1").focus({ preventScroll: true });
  }
  view(page);
  draw();
}

/* #/gallery/review: lessons people asked to list in the gallery, for admins (the server says 404 to anyone else). In
   the feedback inbox's language: Waiting / Listed / Not approved, then one grouped card of rows. */
const RV_FILTERS = { waiting: "Waiting", listed: "Listed", rejected: "Not approved" };
export function showReview() {
  const q = new URLSearchParams(location.hash.split("?")[1] || "").get("status");
  let filter = RV_FILTERS[q] ? q : "waiting";
  const countEl = h("p", { class: "lib-count-line rv-count", "aria-live": "polite" });
  const body = h("div", { class: "rv-body", "aria-busy": "true" });
  const tabs = {};
  const seg = h("div", { class: "segmented", role: "tablist", "aria-label": "Show" }, Object.entries(RV_FILTERS).map(([k, label]) =>
    (tabs[k] = h("button", { type: "button", role: "tab", class: "seg" + (k === filter ? " active" : ""), "aria-selected": String(k === filter),
      onclick: () => { filter = k; Object.entries(tabs).forEach(([kk, b]) => { b.classList.toggle("active", kk === k); b.setAttribute("aria-selected", String(kk === k)); });
        history.replaceState(null, "", k === "waiting" ? "#/gallery/review" : `#/gallery/review?status=${k}`); load(); } }, label))));
  setTitle("Gallery review");
  view(h("section", { class: "lib fbx rv", "aria-labelledby": "rv-title" },
    h("div", { class: "fbx-head" }, h("h1", { id: "rv-title" }, "Gallery review"), h("div", { class: "fbx-filter" }, seg, countEl)),
    body));
  async function act(item, action, btn) {
    busy(btn, true);
    try { await api(`/api/admin/listings/${item.id}`, { action }); }
    catch (err) { busy(btn, false); return btn.closest("li").append(errorBox(err.message)); }
    if (action === "approve" || action === "reject") status.gallery_waiting = Math.max(0, (status.gallery_waiting || 1) - (filter === "waiting" ? 1 : 0));
    load();
  }
  async function preview(item) {
    try { openLesson(await api(`/api/admin/listings/${item.id}/lesson`), { review: true }); } catch (err) { alertInline(err.message); }
  }
  function row(item) {
    const acts = h("div", { class: "rv-acts" }, h("button", { type: "button", class: "small ghost", onclick: () => preview(item) }, icon("eye"), "Preview"));
    const b = (label, action, cls = "small") => h("button", { type: "button", class: cls, onclick: (e) => act(item, action, e.currentTarget) }, label);
    if (filter === "waiting") acts.append(b("List it", "approve"), b("Don't list", "reject", "small ghost"));
    else if (filter === "listed") acts.append(b("Remove from gallery", "remove", "small danger"));
    else acts.append(b("List it", "approve"));
    const t = item.asked ? when(item.asked) : null;
    return h("li", { class: "lib-row fbx-row rv-row" },
      h("div", { class: "lib-text" },
        h("div", { class: "fbx-top" }, h("span", { class: "tag" }, RV_FILTERS[filter]), item.changed ? h("span", { class: "tag yellow" }, "Changed since it was listed") : null),
        h("p", { class: "rv-title" }, item.title),
        h("p", { class: "fbx-ctx" }, h("span", {}, h("span", { class: "fbx-k" }, "Shared by "), `${item.author} · ${item.email}`),
          h("span", {}, [item.field, plural(item.concepts, "concept")].filter(Boolean).join(" · "), t ? [" · asked ", t] : null))),
      acts);
  }
  async function load() {
    body.setAttribute("aria-busy", "true");
    let items;
    try { items = await api(`/api/admin/listings?status=${filter}`); }
    catch (err) {
      if (err.status === 404) {
        setTitle("Not found");
        return view(h("section", { class: "lib-empty fbx-404", "aria-labelledby": "nf-title" },
          h("h1", { id: "nf-title" }, "Not found"), h("p", {}, "There's no page at this address."),
          h("div", { class: "actions" }, h("a", { class: "btn", href: "#/" }, "Go to the home page"))));
      }
      body.removeAttribute("aria-busy");
      return body.replaceChildren(h("div", { class: "lib-none", role: "alert" }, h("p", {}, `The list couldn't load. ${err.message}`),
        h("button", { type: "button", onclick: () => load() }, icon("refresh"), "Try again")));
    }
    body.removeAttribute("aria-busy");
    countEl.textContent = `${items.length} ${RV_FILTERS[filter].toLowerCase()}`;
    body.replaceChildren(items.length ? h("ul", { class: "lib-list fbx-list" }, items.map(row))
      : h("div", { class: "lib-none fbx-none" }, h("p", {}, { waiting: "Nothing is waiting for review.", listed: "No community lessons are listed yet.", rejected: "Nothing has been turned down." }[filter])));
  }
  load();
}
