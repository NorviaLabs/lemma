/* The gallery: shipped lessons as cards with a live cover, the home page's wall and the #/gallery page. */
import { api, cleanups, fold, h, icon, setTitle, status, view } from "./shell.js";
import { showHome } from "./home.js";
import { openLesson } from "./learn.js";

/* The gallery: finished lessons anyone can open, each led by one of its own models, drawn live at rest. */
const TAB_INKS = ["violet", "green", "ochre", "blue"];  // the lesson's concept tabs, in the same order
let galleryP = null;
const galleryItems = () => (galleryP = galleryP || api("/api/gallery").catch((e) => { galleryP = null; throw e; }));
const shortAuthors = (a) => {
  const names = String(a || "").split(/,\s*/).filter((n) => n && n !== "et al.");
  return names.length > 2 || /et al/.test(a || "") ? `${names[0]} et al.` : names.join(" and ");
};
/* A gallery card's cover: one of the lesson's own models, drawn live at rest; a lesson taught without a model shows
   the source's own words. */
function drawCover(plate, cover) {
  const M = window.LemmaModel;
  if (plate.dataset.drawn || !cover) return;
  plate.dataset.drawn = "1";
  if (!cover.model) {
    if (cover.quote) {
      plate.classList.add("gal-quote-plate");
      plate.append(h("figure", { class: "gal-quote" + (cover.quote.split(" ").length <= 16 ? " is-short" : "") },
        h("span", { class: "gal-mark" }, "“"), h("blockquote", {}, cover.quote), cover.quote_author ? h("figcaption", {}, `— ${cover.quote_author}`) : null));
    } else plate.append(h("div", { class: "gal-reading" }, h("p", {}, cover.title), h("p", { class: "small" }, cover.idea)));
    return;
  }
  const box = h("div", { class: "viz-box" });
  plate.append(box);
  const view = new M.ModelView(box, cover.model);
  view.trailsOn = false;
  view.update(Object.assign(M.defaults(cover.model), cover.values || {}));
  cleanups.push(() => view.destroy());
  // A table model taller than its plate is shrunk to fit whole, rather than cut off at the plate's edge.
  const table = box.querySelector(".table-scroll");
  if (table && typeof ResizeObserver !== "undefined") {
    const fit = new ResizeObserver(() => {
      table.style.zoom = "";
      const k = box.clientHeight / table.scrollHeight;
      if (k < 1) table.style.zoom = Math.max(k, 0.5).toFixed(3);
    });
    fit.observe(box);
    cleanups.push(() => fit.disconnect());
  }
}
// `pick` (slugs, in order) gives the home page's model wall: the model, the field and a short title only.
// Without it, the Gallery page: every lesson, each tile also carrying its source and concept count.
// `onTiles` gets the tiles each time they land (again after "Try again"), so the Gallery page can filter them.
function galleryList(level, pick, onTiles) {
  const M = window.LemmaModel;
  // Until the list arrives, quiet tiles of the same shape hold the space, so nothing jumps when it lands.
  const skeleton = () => Array.from({ length: pick ? pick.length : 6 }, () => h("li", { class: "gal-item gal-skel", "aria-hidden": "true" },
    h("div", { class: "gal-plate" }), h("span", { class: "gal-skel-line" }), h("span", { class: "gal-skel-line is-mid" }), pick ? null : h("span", { class: "gal-skel-line is-short" })));
  const list = h("ul", { class: "gallery" + (pick ? " gallery-wall" : ""), "aria-busy": "true" },
    h("li", { class: "sr-only" }, "Opening the gallery…"), ...skeleton());
  const load = () => galleryItems().then((all) => {
    const views = [];
    const items = pick ? pick.map((slug) => all.find((it) => it.slug === slug)).filter(Boolean) : all;
    list.replaceChildren(...items.map((it) => {
      const plate = h("div", { class: "gal-plate", "aria-hidden": "true" });
      plate.dataset.slug = it.slug;
      views.push([plate, it.cover]);
      if (pick) return h("li", { class: "gal-item" },
        plate,
        h("p", { class: "gal-field" }, it.field),
        h(level, { class: "gal-title" }, h("a", { href: `#/gallery/${it.slug}`, title: it.title }, it.title.split(":")[0])));
      const by = [shortAuthors(it.source.authors), it.source.year].filter(Boolean).join(", ");
      const li = h("li", { class: "gal-item" },
        plate,
        h(level, { class: "gal-title" }, h("a", { href: `#/gallery/${it.slug}` }, it.title)),
        h("p", { class: "gal-paper" }, h("cite", {}, it.source.title), by ? h("span", {}, by) : null),
        h("p", { class: "gal-meta" }, h("span", {}, it.field), h("span", { class: "gal-count" }, `${it.concepts.length} concepts`)));
      li.dataset.slug = it.slug;
      li.dataset.find = fold([it.title, it.field, it.source.title, it.source.authors, it.source.year, ...it.concepts].join(" "));
      return li;
    }));
    list.removeAttribute("aria-busy");
    // Draw each model as it comes into view; drawing them all at once would hold up the page.
    const draw = drawCover;
    if (typeof IntersectionObserver === "undefined") views.forEach(([pl, c]) => draw(pl, c));
    else {
      const io = new IntersectionObserver((entries) => entries.forEach((e) => {
        if (!e.isIntersecting) return;
        io.unobserve(e.target);
        const v = views.find(([pl]) => pl === e.target);
        if (v) draw(...v);
      }), { rootMargin: "200px 0px" });
      views.forEach(([pl]) => io.observe(pl));
      cleanups.push(() => io.disconnect());
    }
    if (onTiles) onTiles([...list.children]);
  }).catch(() => {
    list.removeAttribute("aria-busy");
    const again = h("button", { type: "button", onclick: () => { list.setAttribute("aria-busy", "true"); list.replaceChildren(h("li", { class: "sr-only" }, "Opening the gallery…"), ...skeleton()); load(); } }, icon("refresh"), "Try again");
    list.replaceChildren(h("li", { class: "gal-error", role: "alert" }, h("p", {}, "The gallery couldn't load. Check your connection, then try again."), again));
  });
  load();
  return list;
}
const GALLERY_LEAD = "Finished visual lessons on complex ideas, from how attention reads every word at once to how ice can lock a planet in the cold. Each is taught from real sources you can check, with no account or key.";
const HOME_WALL = ["attention-2017", "wuhan-2020", "wave-interference", "mendel-1866", "ice-albedo-feedback", "opinion-dynamics-2002"];
export function gallerySection() {
  const all = h("a", { class: "btn gal-all", href: "#/gallery" }, "See all lessons", icon("next"));
  galleryItems().then((items) => { all.firstChild.textContent = `See all ${items.length} lessons`; }).catch(() => {});
  return h("section", { class: "gallery-sec", "aria-labelledby": "gallery-title" },
    h("div", { class: "gal-head" }, h("h2", { id: "gallery-title" }, "Lessons to explore"), h("p", { class: "lead" }, "Finished lessons across subjects. Open one, no account or key needed.")),
    galleryList("h3", HOME_WALL),
    h("p", { class: "gal-more" }, all));
}
let galleryReturn = "";  // the lesson last opened from the Gallery, so Back lands on its tile
export function showGallery() {
  const q0 = new URLSearchParams(location.hash.split("?")[1] || "").get("q") || "";
  const findIn = h("input", { type: "search", id: "gal-find", value: q0, placeholder: "Topic, field, author or year", autocomplete: "off", spellcheck: "false", maxlength: 80 });
  const count = h("p", { class: "gal-count-line", "aria-live": "polite" });
  const none = h("div", { class: "gal-none", hidden: "" });
  let builtin = [], shared = [];
  const back = galleryReturn;
  galleryReturn = "";
  const list = galleryList("h2", null, (lis) => {
    builtin = lis.filter((li) => li.dataset.find);
    apply(true);
    const tile = back && builtin.find((li) => li.dataset.slug === back && !li.hidden);
    if (tile) { tile.scrollIntoView({ block: "center" }); tile.querySelector("a").focus({ preventScroll: true }); }
  });
  list.classList.add("gal-builtin");
  // Lessons people shared and an admin listed: their own section, after OpenLemma's, once there are any.
  const ownHead = h("div", { class: "gal-head gal-sec-head", hidden: "" }, h("h2", { class: "gal-sec-title" }, "From OpenLemma"),
    h("p", {}, "Built and checked by the OpenLemma team. Open any one, no account or key needed."));
  const communityList = h("ul", { class: "gallery gal-community" });
  const communitySec = h("section", { class: "gal-sec gal-sec-community", hidden: "", "aria-labelledby": "gal-community-title" },
    h("div", { class: "gal-head gal-sec-head" }, h("h2", { class: "gal-sec-title", id: "gal-community-title" }, "From the community"),
      h("p", {}, "Lessons people built and shared. OpenLemma reviewed each one before listing it, and every quote is checked against its source."
        + (status.user ? "" : " Sign in to read them; it's free."))),
    communityList);
  api("/api/gallery/community").then((items) => {
    if (!items.length || !communityList.isConnected) return;
    shared = items.map(communityTile);
    communityList.replaceChildren(...shared);
    // The first row's models at once; the rest as they come into view, as the built-in lessons' are.
    const plates = shared.map((li, i) => [li.querySelector(".gal-plate"), items[i].cover]);
    plates.slice(0, 3).forEach(([plate, cover]) => drawCover(plate, cover));
    if (typeof IntersectionObserver === "undefined") plates.slice(3).forEach(([plate, cover]) => drawCover(plate, cover));
    else {
      const io = new IntersectionObserver((entries) => entries.forEach((e) => {
        if (!e.isIntersecting) return;
        io.unobserve(e.target);
        const hit = plates.find(([plate]) => plate === e.target);
        if (hit) drawCover(...hit);
      }), { rootMargin: "200px 0px" });
      plates.slice(3).forEach(([plate]) => io.observe(plate));
      cleanups.push(() => io.disconnect());
    }
    ownHead.hidden = communitySec.hidden = false;
    apply(true);
  }).catch(() => { /* the built-in gallery still shows */ });
  function communityTile(it) {
    const plate = h("div", { class: "gal-plate", "aria-hidden": "true" });
    const by = [shortAuthors(it.source.authors), it.source.year].filter(Boolean).join(", ");
    const li = h("li", { class: "gal-item" },
      plate,
      h("h2", { class: "gal-title" }, h("a", { href: `#/shared/${it.token}` }, it.title)),
      it.author ? h("p", { class: "gal-by" }, h("span", { class: "avatar", "data-initial": it.author[0], "aria-hidden": "true" }), `Shared by ${it.author}`) : null,
      h("p", { class: "gal-paper" }, h("cite", {}, it.source.title || ""), by ? h("span", {}, by) : null),
      h("p", { class: "gal-meta" }, it.field ? h("span", {}, it.field) : null, h("span", { class: "gal-count" }, `${it.concepts.length} concepts`)));
    li.dataset.find = fold([it.title, it.field, it.author, it.source.title, it.source.authors, it.source.year, ...it.concepts].join(" "));
    return li;
  }
  const apply = (keepHash) => {
    const q = findIn.value.trim();
    const words = fold(q).split(/\s+/).filter(Boolean);
    const tiles = [...builtin, ...shared];
    let shown = 0;
    tiles.forEach((li) => { const hit = words.every((w) => li.dataset.find.includes(w)); li.hidden = !hit; shown += hit; });
    if (tiles.length) count.textContent = words.length ? `${shown} of ${tiles.length} lessons`
      : shared.length ? `${builtin.length} from OpenLemma · ${shared.length} from the community` : `${tiles.length} lessons`;
    communitySec.hidden = !shared.length || !shared.some((li) => !li.hidden);
    none.hidden = !(tiles.length && words.length && !shown);
    if (!none.hidden) none.replaceChildren(h("p", {}, `No lesson matches “${q}”.`),
      h("button", { type: "button", class: "ghost", onclick: () => { findIn.value = ""; apply(); findIn.focus(); } }, icon("cross"), "Clear the search"));
    if (!keepHash) history.replaceState(null, "", q ? `#/gallery?q=${encodeURIComponent(q)}` : "#/gallery");
  };
  findIn.addEventListener("input", () => apply());
  findIn.addEventListener("keydown", (e) => { if (e.key === "Escape" && findIn.value) { e.preventDefault(); findIn.value = ""; apply(); } });
  setTitle("Gallery");
  view(h("section", { class: "gallery-sec gallery-page", "aria-labelledby": "gallery-title" },
    h("div", { class: "gal-page-head" },
      h("div", { class: "gal-head" }, h("h1", { id: "gallery-title" }, "Gallery"), h("p", { class: "lead" }, GALLERY_LEAD)),
      h("form", { class: "gal-find", role: "search", onsubmit: (e) => { e.preventDefault(); findIn.blur(); } },
        h("label", { for: "gal-find" }, "Find a lesson"),
        h("div", { class: "gal-find-row" }, icon("search"), findIn),
        count)),
    ownHead, list, none, communitySec));
}
export async function openGallery(slug) { galleryReturn = slug; try { openLesson(await api(`/api/gallery/${slug}`)); } catch (err) { showHome(err.message); } }
