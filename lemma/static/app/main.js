/* The app's entry: the route for each address, and starting up (who is signed in, and what they were about to do
   before signing in). */
import { api, cred, heldIntent, player, saveCred, session, setPlayer, setStatus, status } from "./shell.js";
import { showFeedback, showInbox } from "./feedback.js";
import { showHome, showMake } from "./home.js";
import { openGallery, showGallery } from "./gallery.js";
import { showRequest } from "./build.js";
import { openExample, openLesson } from "./learn.js";
import { showLibrary } from "./library.js";
import { drawAccountLink, showAccount, showSignIn } from "./account.js";
import { openShared, showReview, showShare } from "./sharing.js";

export let lastRoute = "";  // the route before this one, so the feedback page can say where it was opened from

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
  if (hash === "#/gallery/review" || hash.startsWith("#/gallery/review?")) return showReview();  // before the gallery's lessons
  if (hash.startsWith("#/gallery/")) return player ? null : openGallery(hash.slice(10));
  if (hash.startsWith("#/share/")) return showShare(hash.slice(8).split("?")[0]);
  if (hash.startsWith("#/shared/")) {
    const token = hash.slice(9).split("?")[0];
    if (player && player.lesson.shared && player.lesson.shared.token === token) return;  // already open
    return openShared(token);
  }
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
  if (["#/library", "#/gallery", "#/make", "#/settings", "#/account", "#/signin", "#/feedback", "#/feedback/inbox", "#/", ""].includes(location.hash.split("?")[0]) && player) { player.destroy(); setPlayer(null); }
  route();
});

(async function init() {
  try { setStatus(await api("/api/status")); } catch (e) { /* the server will report */ }
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
