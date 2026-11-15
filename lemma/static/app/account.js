/* Signing in and the account page: the profile, the AI provider and, for admins, today's use. */
import { $, api, busy, errorBox, h, heldIntent, holdIntent, icon, setStatus, setTitle, status, view } from "./shell.js";
import { pageOf } from "./feedback.js";
import { keyForm } from "./provider.js";

const PROVIDER_NAMES = { google: "Google", github: "GitHub" };

function avatar(user, size) {
  const initial = (user.name || user.email || "?").trim().charAt(0).toUpperCase();
  const fallback = h("span", { class: "avatar", style: `--size:${size}px`, "aria-hidden": "true" }, initial);
  if (!user.avatar) return fallback;
  const img = h("img", { class: "avatar", style: `--size:${size}px`, src: user.avatar, alt: "", referrerpolicy: "no-referrer" });
  img.addEventListener("error", () => img.replaceWith(fallback));
  return img;
}

export function drawAccountLink() {
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
export const googleButton = () => {
  const src = (n) => `static/google-sign-in-${n}x.png`;
  return h("a", { class: "google-signin", href: "auth/google/start" },
    h("img", { src: src(2), srcset: [1, 2, 3, 4].map((n) => `${src(n)} ${180 * n}w`).join(", "), sizes: "216px", width: 216, height: 48, alt: "Sign in with Google" }));
};

export function showSignIn(error, next) {
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
export async function showAccount(toProvider) {
  if (!status.user) { holdIntent({ route: toProvider ? "#/settings" : "#/account" }); return showSignIn(); }
  const u = status.user;
  const out = h("button", { class: "ghost small account-signout", onclick: async () => {
    busy(out, true);
    try { await api("/api/logout", {}); } catch (e) { /* signed out either way */ }
    setStatus(await api("/api/status").catch(() => Object.assign(status, { user: null })));
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
      // Only admins' status carries feedback_new and site_today.
      status.site_today ? h("div", { class: "af-row af-site" }, h("dt", {}, "Today, for everyone"),
        h("dd", {}, ...Object.values(status.site_today).map(s => h("span", s.limit !== null && s.used >= s.limit ? { class: "full" } : {},
          s.limit === null ? `${s.used} ${s.what}` : `${s.used} of ${s.limit} ${s.what}${s.used >= s.limit ? " (limit reached)" : ""}`)))) : null,
      "gallery_waiting" in status ? h("div", { class: "af-row af-link af-review" }, h("dt", {}, "Gallery review"),
        h("dd", {}, h("a", { href: "#/gallery/review" }, `${status.gallery_waiting} waiting`), icon("chevron"))) : null,
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
