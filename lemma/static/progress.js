/* Where a learner is in a lesson, kept in this browser only (localStorage), one entry per account and lesson.
   The player saves it as the learner moves (hooks.progress), and the app reads it back for the lesson's intro and the
   library. Nothing here talks to the server; for a shared lesson, the app sends its author report(), which says how
   far the reader got and never what they answered. A downloaded lesson is mounted without any of this.

   The saved state:
     { v: 1, at: <ms>, total: <concepts>, primer: { done, page },
       current: { concept, index, screen, screen_id } | null,
       concepts: { <id>: { finished, screen, screen_id, watched, goals, check_done, check_first_try } },
       finished_at: <ms> | null } */
(function (root) {
  "use strict";
  const PREFIX = "lemma.progress.";
  const VERSION = 1;

  const storageKey = (account, lessonKey) => `${PREFIX}${account || "anon"}.${lessonKey}`;

  // Where a lesson came from: a shared one by its share, the gallery's by slug, the example, or a library lesson
  // (and a build read while it builds, which keeps its id once saved) by id.
  function lessonKey(lesson) {
    if (lesson.shared && lesson.shared.id) return `shared:${lesson.shared.id}`;
    if (lesson.gallery && lesson.gallery.slug) return `gallery:${lesson.gallery.slug}`;
    if (lesson.example) return "example";
    return `lesson:${lesson.id}`;
  }

  const isObject = (x) => !!x && typeof x === "object" && !Array.isArray(x);
  function valid(s) {
    if (!isObject(s) || s.v !== VERSION || !isObject(s.concepts)) return false;
    if (s.primer !== undefined && !isObject(s.primer)) return false;
    if (s.current !== null && s.current !== undefined) {
      const c = s.current;
      if (!isObject(c) || typeof c.concept !== "string" || !Number.isInteger(c.screen)) return false;
    }
    return Object.values(s.concepts).every(isObject);
  }

  function load(storage, key) {
    try {
      if (!storage) return null;
      const raw = storage.getItem(key);
      if (raw === null || raw === undefined) return null;
      const s = JSON.parse(raw);
      return valid(s) ? s : null;
    } catch (e) {
      return null;  // unreadable, or storage refused: nothing saved
    }
  }
  function save(storage, key, state) {
    try { if (storage) storage.setItem(key, JSON.stringify(state)); } catch (e) { /* storage full or refused: kept for this visit only */ }
  }
  function clear(storage, key) {
    try { if (storage) storage.removeItem(key); } catch (e) { /* nothing to forget */ }
  }

  // A concept's screens, as the player shows them: its title, then each activity by id; a concept from before
  // activities lists its screens by kind, in the fixed order the player used for them.
  function screenIds(c) {
    if (Array.isArray(c.activities)) return ["title", ...c.activities.map((a) => a.id)];
    const has = (a) => !!(a && (a.steps || []).length);
    const ids = ["title"];
    if (has(c.animation)) ids.push("watch");
    if (has(c.understand && c.understand.walkthrough)) ids.push("walk");
    ids.push("explain");
    ((c.explore && c.explore.goals) || []).forEach((_, i) => ids.push(`goal:${i}`));
    ids.push("predict", "reveal");
    if (c.check) ids.push("check");
    ids.push("connect");
    return ids;
  }

  const clone = (x) => JSON.parse(JSON.stringify(x));
  const built = (lesson) => lesson.concepts || [];
  // The concepts in the order the learner meets them, including any still being built.
  const order = (lesson) => (Array.isArray(lesson.plan) ? lesson.plan.filter((p) => p.state !== "omitted").map((p) => p.id) : built(lesson).map((c) => c.id));
  const pending = (lesson) => (Array.isArray(lesson.plan) ? lesson.plan.filter((p) => p.state === "waiting" || p.state === "building").map((p) => p.id) : []);
  const isFinished = (s, id) => !!(s.concepts[id] && s.concepts[id].finished);

  // The saved place matched to the lesson as it is now. `changed` says the place itself had to move because what
  // the learner was on is gone; a concept that only moved keeps its place under its new number.
  function reconcile(state, lesson) {
    const s = clone(state);
    const concepts = built(lesson), ids = order(lesson), waiting = pending(lesson);
    const known = new Set([...concepts.map((c) => c.id), ...waiting]);
    let changed = false;
    for (const id of Object.keys(s.concepts)) if (!known.has(id)) delete s.concepts[id];
    s.total = ids.length;
    s.primer = isObject(s.primer) ? s.primer : { done: false, page: 0 };
    if (s.current) {
      const cid = s.current.concept, c = concepts.find((x) => x.id === cid);
      if (c) {
        const screens = screenIds(c);
        let i = screens[s.current.screen] === s.current.screen_id ? s.current.screen : screens.indexOf(s.current.screen_id);
        if (i < 0) { i = 0; changed = true; }
        s.current = { concept: cid, index: ids.indexOf(cid), screen: i, screen_id: screens[i] };
        if (s.concepts[cid]) Object.assign(s.concepts[cid], { screen: i, screen_id: screens[i] });
      } else if (waiting.includes(cid)) {
        s.current = { ...s.current, index: ids.indexOf(cid) };
      } else {
        changed = true;
        const next = concepts.find((x) => !isFinished(s, x.id));
        s.current = next ? { concept: next.id, index: ids.indexOf(next.id), screen: 0, screen_id: "title" } : null;
      }
    }
    return { state: s, changed };
  }

  const finishedIn = (s, lesson) => built(lesson).filter((c) => isFinished(s, c.id)).length;
  const allFinished = (s, lesson) => built(lesson).length > 0 && pending(lesson).length === 0 && built(lesson).every((c) => isFinished(s, c.id));

  // What the lesson's intro says: nothing to continue, a page of the idea in brief, a screen of a concept, or done.
  function summary(state, lesson) {
    if (!state) return { status: "none" };
    const ids = order(lesson), total = ids.length, finished = finishedIn(state, lesson), at = state.at || null;
    if (state.finished_at || allFinished(state, lesson)) return { status: "finished", total, finished, finishedAt: state.finished_at || at, at };
    const cur = state.current;
    if (cur) {
      const c = built(lesson).find((x) => x.id === cur.concept);
      const planned = (lesson.plan || []).find((p) => p.id === cur.concept);
      const screens = c ? screenIds(c) : null;
      return { status: "started", concept: ids.indexOf(cur.concept) + 1, total, title: (c || planned || {}).title || "", screen: cur.screen + 1,
        screens: screens ? screens.length : null, screenId: cur.screen_id, finished, at };
    }
    const primer = state.primer || {}, pages = Array.isArray(lesson.primer) ? lesson.primer.length : 0;
    if (primer.done) {  // read the idea in brief, but no concept opened yet: the first concept not finished
      const next = built(lesson).find((c) => !isFinished(state, c.id));
      if (next) return { status: "started", concept: ids.indexOf(next.id) + 1, total, title: next.title, screen: 1, screens: screenIds(next).length, screenId: "title", finished, at };
      return { status: "none" };
    }
    if (pages && primer.page > 0) return { status: "primer", primerPage: Math.min(primer.page, pages - 1) + 1, primerPages: pages, total, finished, at };
    return { status: "none" };
  }

  // The library's line: from what was saved alone, without the lesson.
  function brief(state) {
    if (!state) return { status: "none", concept: 0, total: 0 };
    const total = state.total || 0;
    if (state.finished_at) return { status: "finished", concept: total, total };
    if (state.current) return { status: "started", concept: (state.current.index || 0) + 1, total };
    if (state.primer && !state.primer.done && state.primer.page > 0) return { status: "primer", concept: 0, total };
    return { status: "none", concept: 0, total };
  }

  // What a shared lesson's author is told: the furthest concept reached, those finished, and whether it's done.
  function report(state, lesson) {
    const ids = built(lesson).map((c) => c.id);
    if (!state) return { reached: null, finished: [], completed: false };
    const finished = ids.filter((id) => isFinished(state, id));
    const seen = ids.map((id, i) => ((state.concepts[id] || (state.current && state.current.concept === id)) ? i : -1));
    const furthest = Math.max(-1, ...seen);
    return { reached: furthest >= 0 ? ids[furthest] : null, finished, completed: !!state.finished_at || (ids.length > 0 && finished.length === ids.length) };
  }

  root.LemmaProgress = { VERSION, storageKey, lessonKey, load, save, clear, screenIds, reconcile, summary, brief, report };
})(typeof window !== "undefined" ? window : globalThis);
