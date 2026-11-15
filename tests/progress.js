// Run with node tests/progress.js (tests/test_progress.py runs it). "Continue where you left off" keeps a learner's
// place in this browser only: lemma/static/progress.js (window.LemmaProgress) saves it to localStorage, matches it
// back to the lesson when the lesson has changed, and summarises it for the lesson intro, the library and, for a
// shared lesson, the author. Each case prints "PASS <name>" or "FAIL <name> :: <why>", and runs on its own.
//
// The saved state, one JSON object per account and lesson, under "lemma.progress.<account or anon>.<lesson key>":
//   { v: 1, at: <ms>, total: <concepts in the lesson>,
//     primer: { done: <bool>, page: <0-based page> },
//     current: { concept: <concept id>, index: <0-based>, screen: <0-based>, screen_id: <id> } | null,
//     concepts: { <concept id>: { finished, screen, screen_id, watched, goals: {}, check_done, check_first_try } },
//     finished_at: <ms> | null }
// A lesson's key: "lesson:<id>" (library, and a build being read while it builds, which keeps its id once saved),
// "gallery:<slug>", "example", or "shared:<share id>".
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.join(__dirname, "..");
let P = null;
try {
  require("../lemma/static/progress.js");
  P = globalThis.LemmaProgress;
} catch (e) {
  P = null;
}
const gallery = (slug) => JSON.parse(fs.readFileSync(path.join(ROOT, "lemma/examples/gallery", `${slug}.json`), "utf8"));
const GALTON = gallery("galton-1886");
const [MID, REG, WHY] = GALTON.concepts.map((c) => c.id);  // mid_parent, regression_line, why_regression

// A stand-in for localStorage: the same three methods, kept in a Map.
function memory() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), keys: () => [...m.keys()], raw: m };
}
// Storage that refuses everything, as some private browsing modes do.
const refusing = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); }, removeItem() { throw new Error("denied"); } };

function state(over = {}) {
  return {
    v: 1, at: 1_700_000_000_000, total: 3, primer: { done: true, page: 4 },
    current: { concept: REG, index: 1, screen: 4, screen_id: "goal_0" },
    concepts: {
      [MID]: { finished: true, screen: 0, screen_id: "title", watched: true, goals: { a: "self" }, check_done: false, check_first_try: null },
      [REG]: { finished: false, screen: 4, screen_id: "goal_0", watched: true, goals: {}, check_done: false, check_first_try: null },
    },
    finished_at: null, ...over,
  };
}
const clone = (x) => JSON.parse(JSON.stringify(x));

let failed = 0;
function test(name, fn) {
  try {
    if (!P) throw new Error("lemma/static/progress.js doesn't define window.LemmaProgress yet");
    fn();
    console.log(`PASS ${name}`);
  } catch (e) {
    failed++;
    console.log(`FAIL ${name} :: ${(e && e.message) || e}`);
  }
}

// ------------------------------------------------------------ where it is kept

test("each account keeps its own place in each lesson", () => {
  assert.equal(P.storageKey("491ea64fa362912a", "lesson:a1b2c3d4e5f6"), "lemma.progress.491ea64fa362912a.lesson:a1b2c3d4e5f6");
  assert.equal(P.storageKey(null, "gallery:galton-1886"), "lemma.progress.anon.gallery:galton-1886");
  assert.equal(P.storageKey("", "example"), "lemma.progress.anon.example");
  assert.notEqual(P.storageKey("a", "lesson:x"), P.storageKey("b", "lesson:x"));
});

test("a lesson's key says where it came from", () => {
  assert.equal(P.lessonKey({ id: "a1b2c3d4e5f6" }), "lesson:a1b2c3d4e5f6");
  assert.equal(P.lessonKey({ id: "galton-1886", example: true, gallery: { slug: "attention-2017" } }), "gallery:attention-2017");
  assert.equal(P.lessonKey({ id: "galton-1886", example: true }), "example");
  assert.equal(P.lessonKey({ id: "s-0123456789ab", shared: { id: "0123456789ab", token: "q7Kx2mP9vR4tW8yZ1aB3cD" } }), "shared:0123456789ab");
});

test("what is saved comes back, and clearing forgets it", () => {
  const s = memory(), k = P.storageKey("u1", "lesson:abc");
  assert.equal(P.load(s, k), null);
  P.save(s, k, state());
  assert.deepEqual(P.load(s, k), state());
  assert.deepEqual(s.keys(), [k]);
  P.clear(s, k);
  assert.equal(P.load(s, k), null);
  assert.deepEqual(s.keys(), []);
});

test("another account's place is not this account's", () => {
  const s = memory();
  P.save(s, P.storageKey("u1", "lesson:abc"), state());
  assert.equal(P.load(s, P.storageKey("u2", "lesson:abc")), null);
  assert.equal(P.load(s, P.storageKey(null, "lesson:abc")), null);
});

test("anything unreadable is nothing saved, never an error", () => {
  const s = memory(), k = P.storageKey("u1", "lesson:abc");
  for (const bad of ["{not json", "null", "42", "[]", '"text"', JSON.stringify({ v: 99, at: 1 }), JSON.stringify({ ...state(), concepts: "x" }), JSON.stringify({ ...state(), current: 7 })]) {
    s.setItem(k, bad);
    assert.equal(P.load(s, k), null, bad);
  }
});

test("storage that refuses is ignored quietly", () => {
  const k = P.storageKey("u1", "lesson:abc");
  assert.equal(P.load(refusing, k), null);
  assert.doesNotThrow(() => P.save(refusing, k, state()));
  assert.doesNotThrow(() => P.clear(refusing, k));
  assert.equal(P.load(null, k), null);
  assert.doesNotThrow(() => P.save(undefined, k, state()));
});

// ------------------------------------------------------------ screens, the same list the player shows

test("a concept's screens: its title, then each activity by id", () => {
  assert.deepEqual(P.screenIds(GALTON.concepts[0]), ["title", "watch", "walk", "explain", "goal_0", "goal_1", "predict", "reveal", "connect"]);
  assert.deepEqual(P.screenIds(GALTON.concepts[2]), ["title", "watch", "walk", "explain", "goal_0", "goal_1", "predict", "reveal", "check", "connect"]);
});

test("a concept from before activities lists its screens by kind", () => {
  const old = clone(GALTON.concepts[2]);
  delete old.activities;
  assert.deepEqual(P.screenIds(old), ["title", "watch", "walk", "explain", "goal:0", "goal:1", "predict", "reveal", "check", "connect"]);
  delete old.check;
  delete old.animation;
  assert.deepEqual(P.screenIds(old), ["title", "walk", "explain", "goal:0", "goal:1", "predict", "reveal", "connect"]);
});

// ------------------------------------------------------------ matching a saved place to the lesson as it is now

test("an unchanged lesson keeps the place exactly", () => {
  const { state: s, changed } = P.reconcile(state(), GALTON);
  assert.equal(changed, false);
  assert.deepEqual(s.current, { concept: REG, index: 1, screen: 4, screen_id: "goal_0" });
  assert.deepEqual(Object.keys(s.concepts).sort(), [MID, REG].sort());
});

test("a screen that moved is found by its id", () => {
  const lesson = clone(GALTON);
  const acts = lesson.concepts[1].activities;
  acts.splice(0, 0, acts.splice(3, 1)[0]);  // goal_0 is now the first activity: screen 1
  const { state: s, changed } = P.reconcile(state(), lesson);
  assert.equal(changed, false);
  assert.deepEqual(s.current, { concept: REG, index: 1, screen: 1, screen_id: "goal_0" });
});

test("a screen that is gone starts its concept again, and says the lesson changed", () => {
  const lesson = clone(GALTON);
  lesson.concepts[1].activities = lesson.concepts[1].activities.filter((a) => a.id !== "goal_0");
  const { state: s, changed } = P.reconcile(state(), lesson);
  assert.equal(changed, true);
  assert.deepEqual(s.current, { concept: REG, index: 1, screen: 0, screen_id: "title" });
});

test("a concept that moved keeps its place under its new number", () => {
  const lesson = clone(GALTON);
  lesson.concepts.reverse();
  const { state: s } = P.reconcile(state(), lesson);
  assert.deepEqual(s.current, { concept: REG, index: 1, screen: 4, screen_id: "goal_0" });
  const moved = clone(GALTON);
  moved.concepts.unshift(moved.concepts.splice(1, 1)[0]);
  assert.equal(P.reconcile(state(), moved).state.current.index, 0);
});

test("a concept that is gone is forgotten, and the place moves to the first unfinished concept", () => {
  const lesson = clone(GALTON);
  lesson.concepts = lesson.concepts.filter((c) => c.id !== REG);
  const { state: s, changed } = P.reconcile(state(), lesson);
  assert.equal(changed, true);
  assert.deepEqual(Object.keys(s.concepts), [MID]);
  assert.deepEqual(s.current, { concept: WHY, index: 1, screen: 0, screen_id: "title" });
  assert.equal(s.total, 2);
});

test("a finished concept that is gone no longer counts as finished", () => {
  const lesson = clone(GALTON);
  lesson.concepts = lesson.concepts.filter((c) => c.id !== MID);
  const { state: s, changed } = P.reconcile(state(), lesson);
  assert.equal(changed, false, "the place itself is still there");
  assert.deepEqual(Object.keys(s.concepts), [REG]);
  assert.equal(P.summary(s, lesson).finished, 0);
});

test("a concept still being built is waited for, not forgotten", () => {
  const building = clone(GALTON);
  building.concepts = building.concepts.slice(0, 1);
  building.plan = GALTON.concepts.map((c, i) => ({ id: c.id, title: c.title, state: i ? "building" : "ready" }));
  const { state: s, changed } = P.reconcile(state(), building);
  assert.equal(changed, false);
  assert.deepEqual(Object.keys(s.concepts).sort(), [MID, REG].sort());
  assert.deepEqual(s.current, { concept: REG, index: 1, screen: 4, screen_id: "goal_0" });
});

test("reconciling never changes what was passed in", () => {
  const before = state(), copy = clone(before), lesson = clone(GALTON);
  lesson.concepts = lesson.concepts.slice(0, 1);
  P.reconcile(before, lesson);
  assert.deepEqual(before, copy);
});

// ------------------------------------------------------------ what the intro, library and author are told

test("nothing saved: nothing to continue", () => {
  assert.equal(P.summary(null, GALTON).status, "none");
  assert.equal(P.brief(null).status, "none");
  const fresh = state({ primer: { done: false, page: 0 }, current: null, concepts: {} });
  assert.equal(P.summary(fresh, GALTON).status, "none");
});

test("part way through the idea in brief", () => {
  const s = state({ primer: { done: false, page: 2 }, current: null, concepts: {} });
  const sum = P.summary(s, GALTON);
  assert.equal(sum.status, "primer");
  assert.equal(sum.primerPage, 3);  // 1-based, as the card says "page 3 of 5"
  assert.equal(sum.primerPages, 5);
  assert.equal(sum.at, s.at);
});

test("part way through a concept", () => {
  const sum = P.summary(state(), GALTON);
  assert.equal(sum.status, "started");
  assert.equal(sum.concept, 2);
  assert.equal(sum.total, 3);
  assert.equal(sum.title, GALTON.concepts[1].title);
  assert.equal(sum.screen, 5);  // screen index 4 is the 5th of 9
  assert.equal(sum.screens, 9);
  assert.equal(sum.screenId, "goal_0");
  assert.equal(sum.finished, 1);
  assert.equal(sum.at, 1_700_000_000_000);
});

test("finished", () => {
  const done = state({ current: null, finished_at: 1_700_000_500_000 });
  for (const c of GALTON.concepts) done.concepts[c.id] = { finished: true, screen: 0, screen_id: "title", watched: true, goals: {}, check_done: false, check_first_try: null };
  const sum = P.summary(done, GALTON);
  assert.equal(sum.status, "finished");
  assert.equal(sum.finished, 3);
  assert.equal(sum.finishedAt, 1_700_000_500_000);
  assert.deepEqual(P.brief(done), { status: "finished", concept: 3, total: 3 });
});

test("the library's line needs no lesson, only what was saved", () => {
  assert.deepEqual(P.brief(state()), { status: "started", concept: 2, total: 3 });
  assert.deepEqual(P.brief(state({ primer: { done: false, page: 1 }, current: null, concepts: {} })), { status: "primer", concept: 0, total: 3 });
});

test("what a shared lesson's author is told: how far, never answers", () => {
  assert.deepEqual(P.report(state(), GALTON), { reached: REG, finished: [MID], completed: false });
  assert.deepEqual(P.report(null, GALTON), { reached: null, finished: [], completed: false });
  const done = state({ current: null, finished_at: 1 });
  for (const c of GALTON.concepts) done.concepts[c.id] = { ...done.concepts[MID], finished: true };
  assert.deepEqual(P.report(done, GALTON), { reached: WHY, finished: [MID, REG, WHY], completed: true });
  // the furthest concept reached, even after going back to an earlier one
  const back = state({ current: { concept: MID, index: 0, screen: 2, screen_id: "walk" } });
  assert.equal(P.report(back, GALTON).reached, REG);
  const sent = JSON.stringify(P.report(state(), GALTON));
  assert.ok(!sent.includes("goals") && !sent.includes("self"), "answers and goals stay in the browser");
});

console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
