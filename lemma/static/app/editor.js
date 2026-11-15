/* Editing a saved lesson's words. */
import { api, busy, errorBox, h, icon, setHash, setTitle, view } from "./shell.js";
import { openLesson } from "./learn.js";

const EDIT_FIELDS = [
  ["title", "Title"], ["idea", "Idea"],
  ["understand.explanation", "In plain words"], ["understand.quote", "Quote (must match the source word for word)"], ["understand.quote_where", "Where the quote appears"],
  ["explore.prompt", "Try-it prompt"], ["predict.question", "Use-it question"],
  ["understand.feedback.correct", "Feedback on a right answer"], ["understand.feedback.incorrect", "Feedback on a wrong answer"],
  ["model.note", "Teaching-model note"], ["check.hint", "Check hint (hard concepts only)"], ["check.misconception", "Common mix-up (hard concepts only)"], ["connect.caption", "Equation caption"], ["recap", "In one line"],
];
const getPath = (o, p) => p.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
const setPath = (o, p, v) => { const ks = p.split("."); const last = ks.pop(); const t = ks.reduce((a, k) => (a[k] ||= {}), o); t[last] = v; };

export function showEditor(lessonIn) {
  setHash("#/edit");
  setTitle("Edit lesson");
  const lesson = JSON.parse(JSON.stringify(lessonIn));
  const errSlot = h("div");
  const fields = [];
  // A field writes back only a value the lesson already had, or one the author typed: an empty optional field never
  // adds an empty part (such as a model's note to a concept taught without one), which the checks would refuse.
  const field = (label, obj, path, long) => {
    const id = "f" + fields.length;
    const had = getPath(obj, path) !== undefined;
    const input = long ? h("textarea", { id, rows: 3 }) : h("input", { id, type: "text" });
    input.value = getPath(obj, path) ?? "";
    fields.push(() => { if (had || input.value !== "") setPath(obj, path, input.value); });
    return h("div", {}, h("label", { for: id }, label), input);
  };
  const json = h("textarea", { id: "json-edit", rows: 18, class: "mono", spellcheck: "false", "aria-label": "Lesson JSON" });
  const advanced = h("details", { class: "advanced", ontoggle: () => { if (advanced.open) { fields.forEach((f) => f()); json.value = JSON.stringify(lesson, null, 2); } } },
    h("summary", {}, "Advanced: edit the whole lesson as JSON"), json,
    h("p", { class: "muted small" }, "While this panel is open, saving uses the JSON above."));
  const save = h("button", { class: "primary", onclick: async () => {
    errSlot.replaceChildren();
    let edited = lesson;
    if (advanced.open) { try { edited = JSON.parse(json.value); } catch (e) { errSlot.append(errorBox("The JSON isn't valid: " + e.message)); return; } }
    else fields.forEach((f) => f());
    busy(save, true);
    try {
      const saved = await api("/api/lessons", { lesson: edited });
      errSlot.append(h("p", { class: "ok", role: "status" }, icon("check"), " Checked and saved to your library."
        + (saved.review ? " It's waiting for review before it shows in the gallery again." : "")));
    }
    catch (err) { errSlot.append(errorBox(err.message + " The lesson was not saved, because a lesson that fails its checks is never shown to learners.", err.problems)); }
    busy(save, false);
  } }, "Check and save");
  view(h("section", {},
    h("h1", {}, "Edit lesson"),
    h("p", { class: "muted", style: "max-width:66ch" }, "Correct anything before sharing. Saving re-runs every quality check against the sources: quotes must still match word for word, and every goal must still be reachable."),
    h("fieldset", {}, h("legend", {}, "Lesson"), field("Lesson title", lesson, "title"), field("Summary", lesson, "intro.summary", true)),
    Array.isArray(lesson.primer) ? h("fieldset", {}, h("legend", {}, "The idea in brief"),
      ...lesson.primer.flatMap((pg, i) => [field(`Page ${i + 1} heading`, pg, "heading"), field(`Page ${i + 1} text`, pg, "body", true),
        field(`Page ${i + 1} quote (optional; must match the source word for word)`, pg, "quote", true)])) : null,
    ...lesson.concepts.map((c, i) => h("fieldset", {}, h("legend", {}, `Concept ${i + 1}: ${c.title}`),
      // Only the parts this concept has: one taught without a model has no model, goals or equation to edit.
      EDIT_FIELDS.filter(([p]) => getPath(c, p) !== undefined).map(([p, label]) => field(label, c, p, /explanation|feedback|quote$|caption|misconception|note|idea|question|prompt/.test(p))))),
    advanced, errSlot,
    h("div", { class: "actions sticky-actions" }, save,
      h("button", { class: "ghost", onclick: () => openLesson(lesson, { saved: true, preview: true }) }, "Preview"),
      h("a", { class: "btn ghost", href: "#/library" }, "Back to library"))));
}
