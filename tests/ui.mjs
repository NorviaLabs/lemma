// The app in a real browser, driven by tests/test_ui.py: `node tests/ui.mjs '<json>'`, where the JSON gives the
// server's address, a session cookie, the browser and the flow to run, with the builds it sets up. Each flow prints a
// line per check, "PASS …" or "FAIL …", and the process fails if any check does.
//
// With "coverage" (a folder), it also saves the browser's coverage of the app's modules (app/*.js), player.js and ui.js there, for c8. The browser
// reports coverage only for scripts still loaded, so a snapshot is saved before every reload and at the end.
import fs from "node:fs";
import puppeteer from "puppeteer-core";

const cfg = JSON.parse(process.argv[2]);
const ids = cfg.ids || {};
let failed = 0;
const problems = [];

function check(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${ok ? "" : `\n      got:  ${JSON.stringify(got)}\n      want: ${JSON.stringify(want)}`}`);
}

const browser = await puppeteer.launch({
  executablePath: cfg.chrome, headless: true, args: ["--no-sandbox", "--disable-dev-shm-usage"],
  defaultViewport: { width: cfg.width || 1280, height: 900 },
});
const page = await browser.newPage();
page.setDefaultTimeout(15000);
page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error" && !/favicon/.test((m.location() || {}).url || "")) problems.push(`console: ${m.text()} (${(m.location() || {}).url || ""})`); });
page.on("dialog", (d) => d.dismiss());
const base = new URL(cfg.base);
if (cfg.cookie) await page.setCookie({ name: cfg.cookie.name, value: cfg.cookie.value, domain: base.hostname, path: "/" });
if (cfg.cred) {  // the learner's AI provider, as the browser keeps it
  await page.evaluateOnNewDocument((c) => localStorage.setItem("lemma.ai", JSON.stringify(c)), cfg.cred);
}

let snaps = 0;
if (cfg.coverage) await page.coverage.startJSCoverage({ resetOnNavigation: false, includeRawScriptCoverage: true });
async function snap() {
  if (!cfg.coverage) return;
  const entries = await page.coverage.stopJSCoverage();
  const result = entries.filter((e) => e.rawScriptCoverage && /\/static\/(app\/[a-z]+|player|ui)\.js/.test(e.url))
    .map((e) => ({ ...e.rawScriptCoverage, url: new URL(`../lemma/static/${new URL(e.url).pathname.split("/static/").pop()}`, import.meta.url).href }));
  fs.mkdirSync(cfg.coverage, { recursive: true });
  fs.writeFileSync(`${cfg.coverage}/${cfg.flow}-${process.pid}-${String(++snaps).padStart(3, "0")}.json`, JSON.stringify({ result }));
  await page.coverage.startJSCoverage({ resetOnNavigation: false, includeRawScriptCoverage: true });
}

// ---------------------------------------------------------------- helpers
const pause = (ms) => new Promise((r) => setTimeout(r, ms));
const text = (sel) => page.$eval(sel, (e) => e.textContent.trim()).catch(() => null);
const texts = (sel) => page.$$eval(sel, (es) => es.map((e) => e.textContent.trim()));
const count = (sel) => page.$$eval(sel, (es) => es.length);
const h1 = () => text("main h1");
async function until(fn, ms = 20000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    if (await fn().catch(() => false)) return true;
    await pause(150);
  }
  return false;
}
// Clicks the visible button (or link) labelled exactly `label` inside `scope`.
async function click(scope, label) {
  await page.evaluate((scope, label) => {
    const el = [...document.querySelectorAll(`${scope} button, ${scope} a`)].find((b) => b.textContent.trim() === label && !b.closest("[hidden]"));
    if (!el) throw new Error(`no "${label}" in ${scope}`);
    el.click();
  }, scope, label);
  await pause(200);
}
async function open(hash) {
  await snap();
  await page.goto(new URL(hash, cfg.base).href, { waitUntil: "networkidle0" });
  await snap();
  await page.reload({ waitUntil: "networkidle0" });  // a new hash alone doesn't load the page again
  await page.waitForSelector("main h1");
}
const row = (id) => `.lib-build:has(.lib-open[href$="${id}"])`;
const outlineOpen = () => until(async () => (await count(".outline-list")) > 0, 20000);
const MODEL_NOTE = "The 2 finished concepts were built with Claude (claude‑opus‑5‑5). The rest will use OpenAI (gpt‑6.1‑sol), your current model, and the lesson will name both.";

// ---------------------------------------------------------------- flows
const FLOWS = {
  // Library → Retry build asks in the row; Escape and Not now put it back; Continue keeps the finished concepts, and the
  // finished lesson names both models.
  async "library-continue"() {
    await open("#/library");
    check("the row says what's kept", (await text(`${row(ids.build)} .lib-meta`)).includes("2 of 3 concepts kept"), true);
    await click(row(ids.build), "Retry build");
    check("the row asks the choice", await texts(`${row(ids.build)}.is-choosing .lib-choice p`), [
      "Continue with your approved outline and the 2 finished concepts, or start over with a new outline?", MODEL_NOTE]);
    check("Continue has focus", await page.evaluate(() => document.activeElement.textContent), "Continue building");
    await page.keyboard.press("Escape");
    await pause(150);
    check("Escape puts the row back", [await count(".lib-choice"), await page.evaluate(() => document.activeElement.textContent.trim())], [0, "Retry build"]);
    await click(row(ids.build), "Retry build");
    await click(".lib-choice", "Not now");
    check("Not now puts the row back", await count(".lib-row.is-choosing"), 0);
    await click(row(ids.build), "Retry build");
    await click(".lib-choice", "Continue building");
    check("it finishes", await until(async () => (await h1()) === "Your lesson is ready", 30000), true);
    check("the finished concepts were kept", await texts(".bs-detail"), ["Plans chosen for 1 of 1 concepts", "Ready, kept from the earlier attempt",
      "Ready, kept from the earlier attempt", "Ready", "Saved to your library"]);
    await click(".actions", "Open lesson");
    await page.waitForSelector(".overview");
    check("the lesson names both models", (await text(".overview .muted.small")).match(/Made with.*$/)[0],
      "Made with Claude (claude-opus-5-5) and OpenAI (gpt-6.1-sol).");
  },

  // Library → Start over, with finished concepts, asks again in red before deleting them; then a new outline opens.
  async "library-start-over"() {
    await open("#/library");
    await click(row(ids.build), "Retry build");
    check("no model note when the same model built them", await count(".lib-choice .resume-model"), 0);
    await click(".lib-choice", "Start over");
    check("it asks before deleting", [await count(`${row(ids.build)}.is-asking`), await text(".lib-choice p")],
      [1, "Start over? The 2 finished concepts will be deleted. This can't be undone."]);
    check("Keep them has focus", await page.evaluate(() => document.activeElement.textContent), "Keep them");
    await click(".lib-choice", "Keep them");
    check("Keep them goes back to the choice", [await count(`${row(ids.build)}.is-choosing`), await count(`${row(ids.build)}.is-asking`)], [1, 0]);
    await click(".lib-choice", "Start over");
    await page.keyboard.press("Escape");
    await pause(150);
    check("Escape goes back to the choice, too", await count(`${row(ids.build)}.is-choosing`), 1);
    await click(".lib-choice", "Start over");
    await click(".lib-choice", "Delete and start over");
    check("a new outline opens for review", await outlineOpen(), true);
  },

  // The build page of a build that stopped with an error: its error and "Report this" stay, the choice follows, and
  // Start over asks before deleting.
  async "build-page-start-over"() {
    await open(`#/request/${ids.build}`);
    check("title", await h1(), "This build stopped");
    check("its error is still shown", await text(".error > p"), "The checks couldn't run just now, so the build stopped. Retry in a moment. (error 3f9a1c2e)");
    check("and can be reported", (await texts(".error button")).includes("Report this"), true);
    check("the choice says what's kept", await text(".resume-lead"), "The build stopped before your lesson was finished. Your approved outline and the 2 finished concepts are kept.");
    check("one primary on the page", await texts("main .primary:not([hidden])"), ["Continue building"]);
    check("the model note links to the account page", [await text(".resume .resume-model"), await page.$eval(".resume-model a", (a) => a.getAttribute("href"))],
      [`${MODEL_NOTE} Change model`, "#/settings"]);
    check("the step that never finished says so", await texts(".build-step.stopped .bs-detail"), ["Not built: the build stopped"]);
    check("the finished concepts can be started", await page.evaluate(() => [...document.querySelectorAll(".actions button")].find((b) => b.textContent === "Start the first concept").disabled), false);
    await click(".resume", "Start over");
    check("it asks before deleting", await text(".resume-opt.is-asking p"), "Start over? The 2 finished concepts will be deleted. This can't be undone.");
    await page.keyboard.press("Escape");
    await pause(150);
    check("Escape puts it back", [await count(".resume-opt.is-asking"), await page.evaluate(() => document.activeElement.textContent)], [0, "Start over"]);
    await click(".resume", "Start over");
    await click(".resume", "Delete and start over");
    check("a new outline opens for review", await outlineOpen(), true);
  },

  // Nothing finished yet: the choice still keeps the outline, and Start over has nothing to delete, so it doesn't ask.
  async "nothing-finished"() {
    await open(`#/request/${ids.build}`);
    check("what's kept", await text(".resume-lead"), "OpenLemma stopped before your lesson was finished. Your approved outline is kept. No concepts were finished yet.");
    check("what Continue does", await text(".resume-opt p"), "Builds the 3 concepts in the outline you approved, without reviewing it again.");
    check("no model note without finished concepts", await count(".resume-model"), 0);
    await click(".resume", "Start over");
    check("Start over doesn't ask", await count(".resume-opt.is-asking"), 0);
    check("a new outline opens for review", await outlineOpen(), true);
  },

  // Stopped before its outline was approved: no choice, today's Retry build.
  async "no-choice"() {
    await open("#/library");
    check("no kept count", (await text(`${row(ids.build)} .lib-meta`)).includes("kept"), false);
    await open(`#/request/${ids.build}`);
    check("no choice", await count(".resume"), 0);
    check("today's buttons", await texts(".actions button:not([hidden])"), ["Start the first concept", "Retry build"]);
    check("where it stopped", await text(".bp-count"), "Stopped before the outline was ready");
    check("the unfinished step", await texts(".build-step.stopped .bs-detail"), ["Not built: the server stopped"]);
    check("its message", await text(".error > p"), "The server stopped during this build. Retry to start a new attempt.");
    await click(".actions", "Retry build");
    check("it retries without asking: a new outline", await outlineOpen(), true);
  },

  // No AI provider connected yet: Continue goes through the connect step, then carries on without asking again.
  async "connect-carries-the-choice"() {
    await open(`#/request/${ids.build}`);
    await click(".resume", "Continue building");
    check("the connect step", await h1(), "Connect an AI provider");
    await page.click('input[name="provider"][value="openai"]');
    await page.type("#ai-key", "sk-test");
    await click("main", "Connect and continue");
    check("then it continues, keeping the finished concepts", await until(async () => (await h1()) === "Your lesson is ready", 30000), true);
    check("kept", (await texts(".bs-detail")).filter((t) => t === "Ready, kept from the earlier attempt").length, 2);
  },

  // A build that's running: the Library's cancel question, then, while learning, the build is cancelled and the alert
  // leads to the choice.
  async "cancel-while-learning"() {
    await open(`#/request/${ids.build}`);
    await outlineOpen();
    await page.setExtraHTTPHeaders({ "X-Test-Gate": "1" });  // this build's last concept waits until it's cancelled
    await page.evaluate(() => [...document.querySelectorAll("main button.primary")].find((b) => /^Build \d+ concepts?$/.test(b.textContent)).click());
    check("building", await until(async () => (await h1()) === "Building your lesson"), true);
    await page.setExtraHTTPHeaders({});
    check("the first concepts are ready to start", await until(() => page.evaluate(() => {
      const b = [...document.querySelectorAll(".actions button")].find((x) => x.textContent === "Start the first concept");
      return !!b && !b.disabled;
    }), 30000), true);
    await open("#/library");
    await click(row(ids.build), "Cancel");
    check("the cancel question", await text(`${row(ids.build)} .lib-ask p`), "Cancel this build? The concepts it has finished are kept, so you can continue it later.");
    await click(row(ids.build), "Keep building");
    await open(`#/request/${ids.build}`);
    await click(".actions", "Start the first concept");
    await page.waitForSelector(".overview");
    await page.evaluate((id) => fetch(`api/requests/${id}/cancel`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }), ids.build);
    check("the alert offers the choice", await until(async () => (await count(".error.floating .floating-acts")) > 0, 30000), true);
    check("what it says", await text(".error.floating p"), "You cancelled this build. The concepts it finished are kept. Continue it or start over from the build's page.");
    await click(".error.floating", "Continue or start over");
    check("to the build's page, with the choice", [await h1(), await count(".resume")], ["You cancelled this build", 1]);
    check("the concept it was building wasn't left out", await texts(".build-step.stopped .bs-detail"), ["Not built: you cancelled the build"]);
  },

  // The Library refreshes while builds run, but never under an open question; a change that arrived meanwhile is drawn
  // as soon as the question closes.
  async "library-refresh-under-choice"() {
    await open(`#/request/${ids.running}`);
    await outlineOpen();
    await page.setExtraHTTPHeaders({ "X-Test-Gate": "1" });
    await page.evaluate(() => [...document.querySelectorAll("main button.primary")].find((b) => /^Build \d+ concepts?$/.test(b.textContent)).click());
    check("building", await until(async () => (await h1()) === "Building your lesson"), true);
    await page.setExtraHTTPHeaders({});
    await open("#/library");
    check("the running build", await text(`${row(ids.running)} .lib-state`), "Building now");
    await click(row(ids.build), "Retry build");
    await page.evaluate((id) => fetch(`api/requests/${id}/cancel`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }), ids.running);
    await pause(9000);  // two of the Library's refreshes
    check("the open choice isn't redrawn away", [await count(`${row(ids.build)}.is-choosing`), await page.evaluate(() => document.activeElement.textContent)],
      [1, "Continue building"]);
    await click(".lib-choice", "Not now");
    check("once it closes, the change is drawn", await until(async () => (await text(`${row(ids.running)} .lib-state`)) === "Cancelled", 10000), true);
  },

  // A retry the server refuses says why, in place, and leaves the choice to try again.
  async "retry-refused"() {
    await open(`#/request/${ids.build}`);
    await click(".resume", "Continue building");
    check("the build page says why", await until(async () => (await text(".error > p")) === cfg.refusal, 5000), true);
    check("and the choice is still there to try again", [await count(".resume"), await page.$eval(".resume .primary", (b) => b.disabled)], [1, false]);
    await open("#/library");
    await click(row(ids.build), "Retry build");
    await click(".lib-choice", "Continue building");
    check("the Library row says why", await until(async () => (await text(`${row(ids.build)} .lib-msg span`)) === cfg.refusal, 5000), true);
    check("and the row is back to its buttons", [await count(".lib-choice"), (await texts(`${row(ids.build)} .lib-acts button`))[0]], [0, "Retry build"]);
  },

  // The credit line, for every kind of lesson: each model that built a concept, in order; lessons from before that
  // was recorded read as they always did; built-in lessons have none; and the downloaded file says the same.
  async "credit-lines"() {
    for (const [id, want] of Object.entries(cfg.expect)) {
      await open(`#/lesson/${id}`);
      await page.waitForSelector(".overview .muted.small");
      check(`credit: ${id}`, ((await text(".overview .muted.small")).match(/ Made with .*$/) || [""])[0], want);
    }
    await open("#/gallery/galton-1886");
    await page.waitForSelector(".overview .muted.small");
    check("credit: the gallery", (await text(".overview .muted.small")).includes("Made with"), false);
    const html = await page.evaluate(async (id) => {
      const lesson = await (await fetch(`api/lessons/${id}`)).json();
      return (await fetch("api/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lesson }) })).text();
    }, cfg.exported);
    const file = `${process.env.TMPDIR || "/tmp"}/lemma-ui-${process.pid}.html`;
    fs.writeFileSync(file, html);
    const offline = await browser.newPage();
    offline.on("pageerror", (e) => problems.push(`downloaded lesson: ${e.message}`));
    await offline.goto(`file://${file}`, { waitUntil: "networkidle0" });
    await offline.waitForSelector(".overview .muted.small");
    check("credit: the downloaded file", (await offline.$eval(".overview .muted.small", (e) => e.textContent)).match(/ Made with .*$/)[0], cfg.expect[cfg.exported]);
    fs.unlinkSync(file);
  },

  // A source that couldn't be read: the choice names it, Continue builds from the sources that were read, and
  // Start over tries it once more.
  async "unread-source"() {
    await open(`#/request/${ids.build}`);
    check("the card names it", await text(".resume-lead"),
      "OpenLemma stopped before your lesson was finished. Your approved outline and the 2 finished concepts are kept. 1 source couldn't be read: “Blocked”.");
    check("what Continue does", (await texts(".resume-opt > p"))[0], "Keeps your approved outline and the 2 finished concepts, then builds the 1 concept that's left, from the sources that were read.");
    check("what Start over does", (await texts(".resume-opt > p")).at(-1),
      "Tries the source that couldn't be read once more, then proposes a new outline from your sources for you to review. The 2 finished concepts are deleted.");
    check("the warning is still shown", await texts("main .note"), ["Excluded Blocked: The site refused the download."]);
    await open("#/library");
    await click(row(ids.build), "Retry build");
    check("the Library says so too", await text(".lib-choice p"),
      "Continue with your approved outline and the 2 finished concepts, or start over with a new outline? Starting over tries the source that couldn't be read once more.");
    await click(".lib-choice", "Not now");
    await open(`#/request/${ids.build}`);
    await click(".resume", "Start over");
    await click(".resume", "Delete and start over");
    check("a new outline opens for review", await outlineOpen(), true);
    check("with no warning left: the source was read", (await texts("main .note")).filter((t) => t.startsWith("Excluded")), []);
  },

  // On a phone: nothing overflows, and the choice's buttons take the card's width.
  async "phone"() {
    await open(`#/request/${ids.build}`);
    check("nothing wider than the screen", await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    check("the buttons take the card's width", await page.evaluate(() => {
      const card = document.querySelector(".resume").getBoundingClientRect().width;
      return [...document.querySelectorAll(".resume-opt > button")].every((b) => b.getBoundingClientRect().width > card * .8);
    }), true);
  },
};

// ---------------------------------------------------------------- continue where you left off, and sharing
// (tests/test_ui_progress_sharing.py). cfg.cookies holds a session per account by name, cfg.users their ids, and
// cfg.ids the lesson, its share token and share id. The place in a lesson lives in this browser only, under
// "lemma.progress.<account>.<lesson key>" (tests/progress.js has the format).

// Signs the browser in as `who` (a name in cfg.cookies), or out with null. The place in lessons stays in the browser.
async function as(who) {
  const jar = await page.cookies(cfg.base);
  if (jar.length) await page.deleteCookie(...jar);
  if (who) await page.setCookie({ name: cfg.cookies[who].name, value: cfg.cookies[who].value, domain: base.hostname, path: "/" });
}
const progressKey = (who, lessonKey) => `lemma.progress.${who ? cfg.users[who] : "anon"}.${lessonKey}`;
async function seed(key, value) {
  if (!page.url().startsWith(cfg.base)) await page.goto(cfg.base, { waitUntil: "networkidle0" });
  await page.evaluate((k, v) => localStorage.setItem(k, JSON.stringify(v)), key, value);
}
const stored = (key) => page.evaluate((k) => JSON.parse(localStorage.getItem(k) || "null"), key);
const activeVerb = () => text(".verb[aria-current=step] .verb-head");
const railTitle = () => text(".rail-head h2");
const primaries = () => texts("main .primary:not([hidden])");
const value = (sel) => page.$eval(sel, (e) => e.value).catch(() => null);
const checked = (sel) => page.$$eval(sel, (es) => es.map((e) => e.checked));
const focused = () => page.evaluate(() => document.activeElement.textContent.trim());
const overflows = () => page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
// The idea in brief, page by page, into the first concept's title screen.
async function readTheBrief() {
  await click(".overview .actions", "Read the idea in brief");
  for (let i = 0; i < 8 && !(await page.evaluate(() => document.body.classList.contains("lesson-mode"))); i++) {
    await page.click(".overview .actions .primary");
    await pause(150);
  }
}
// On to the next screen: past any narration, then the screen's primary button.
async function advance() {
  const bar = await texts(".action-bar button");
  if (bar.includes("Skip")) { await click(".action-bar", "Skip"); await pause(200); }
  if (bar.includes("Start the concept")) return click(".action-bar", "Start the concept");
  await page.click(".action-bar .primary:not(:disabled)");
  await pause(250);
}
const GALTON = { mid: "mid_parent", reg: "regression_line", why: "why_regression" };
const T1 = "One number for two parents", T2 = "Children are two-thirds as unusual";
const concept = (over = {}) => ({ finished: false, screen: 0, screen_id: "title", watched: false, goals: {}, check_done: false, check_first_try: null, ...over });
const libRow = (id) => `.lib-lesson:has(.lib-open[href$="${id}"])`;

Object.assign(FLOWS, {
  // A library lesson: read part way, leave, come back to the card, continue at the same screen; the library shows it;
  // Start from the beginning asks first, and clears the place.
  async "progress-continue"() {
    await as("ada");
    await open(`#/lesson/${ids.lesson}`);
    check("nothing saved: no card, the intro as before", [await count(".pickup"), await primaries()], [0, ["Read the idea in brief"]]);
    await readTheBrief();
    check("in the first concept", await railTitle(), `Concept 1 of 3: ${T1}`);
    await advance(); await advance(); await advance(); await advance();  // title → meet → how it works → understand → try
    check("on the first goal", (await activeVerb()).startsWith("Try it yourself"), true);
    const saved = await stored(progressKey("ada", `lesson:${ids.lesson}`));
    check("the place is saved in this browser", saved && [saved.current.concept, saved.current.screen, saved.current.screen_id, saved.primer.done],
      [GALTON.mid, 4, "goal_0", true]);
    await open(`#/lesson/${ids.lesson}`);
    check("the card says where you are", [await text(".pickup h3"), await text(".pickup-where")], ["Pick up where you left off", `Concept 1 of 3: ${T1}`]);
    check("and which screen", (await text(".pickup-sub")).startsWith("Screen 5 of 9 · Try it yourself · Last here"), true);
    check("Continue is the page's one primary", await primaries(), ["Continue"]);
    check("the card comes before the summary", await page.evaluate(() => {
      const card = document.querySelector(".pickup"), summary = document.querySelector(".overview .summary");
      return !!(card.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING);
    }), true);
    check("the concept list marks it", (await texts(".hall .h-state"))[0], "You're here: screen 5 of 9");
    check("the next concept is still locked", await page.$$eval(".hall li button", (bs) => bs.map((b) => b.disabled)), [false, true, true]);
    await click(".pickup", "Continue");
    check("Continue opens the same screen", [await railTitle(), (await activeVerb()).startsWith("Try it yourself")], [`Concept 1 of 3: ${T1}`, true]);
    await page.click('[aria-label="Back to the lesson overview"]');
    await pause(200);
    check("back at the intro, the card is still there", await count(".pickup"), 1);
    await open("#/library");
    check("the library row says how far", await text(`${libRow(ids.lesson)} .lib-progress`), "Concept 1 of 3");
    await open(`#/lesson/${ids.lesson}`);
    await click(".pickup", "Start from the beginning");
    check("it asks first", await text(".pickup-ask p"), "Start from the beginning? Your place in this lesson is cleared in this browser. This can't be undone.");
    check("Keep my place has focus", await focused(), "Keep my place");
    await page.keyboard.press("Escape");
    await pause(150);
    check("Escape keeps the place", [await count(".pickup-ask"), await focused()], [0, "Start from the beginning"]);
    await click(".pickup", "Start from the beginning");
    await click(".pickup-ask", "Keep my place");
    check("Keep my place keeps it", [await count(".pickup-ask"), await count(".pickup")], [0, 1]);
    await click(".pickup", "Start from the beginning");
    await click(".pickup-ask", "Clear and start again");
    check("cleared: the intro as at first", [await count(".pickup"), await primaries()], [0, ["Read the idea in brief"]]);
    check("and forgotten in this browser", await stored(progressKey("ada", `lesson:${ids.lesson}`)), null);
    await open(`#/lesson/${ids.lesson}`);
    check("still cleared after a reload", await count(".pickup"), 0);
    await open("#/library");
    check("the library row no longer shows progress", await count(`${libRow(ids.lesson)} .lib-progress`), 0);
  },

  // A finished lesson: the card says so; Review opens every concept; Start again asks, then clears.
  async "progress-finished"() {
    await as("ada");
    const concepts = Object.fromEntries(Object.values(GALTON).map((id) => [id, concept({ finished: true, watched: true })]));
    await seed(progressKey("ada", `lesson:${ids.lesson}`), { v: 1, at: Date.now() - 86400e3, total: 3, primer: { done: true, page: 4 }, current: null, concepts, finished_at: Date.now() - 86400e3 });
    await open(`#/lesson/${ids.lesson}`);
    check("the card says it's finished", await text(".pickup.finished h3"), "You finished this lesson");
    check("with every concept", (await text(".pickup-sub")).startsWith("All 3 concepts · Finished on "), true);
    check("its buttons", await texts(".pickup .actions button"), ["Review the concepts", "Start again"]);
    check("every concept is done and open", [await texts(".hall .h-state"), await page.$$eval(".hall li button", (bs) => bs.every((b) => !b.disabled))],
      [["Done", "Done", "Done"], true]);
    await open("#/library");
    check("the library says Completed", await text(`${libRow(ids.lesson)} .lib-progress`), "Completed");
    await open(`#/lesson/${ids.lesson}`);
    await click(".pickup", "Review the concepts");
    check("Review opens the first concept at its start", [await railTitle(), await texts(".action-bar button")], [`Concept 1 of 3: ${T1}`, ["Start the concept"]]);
    await page.click('[aria-label="Back to the lesson overview"]');
    await pause(200);
    await click(".pickup", "Start again");
    check("Start again asks, naming what is cleared", await text(".pickup-ask p"),
      "Start from the beginning? Your place and the 3 concepts you finished are cleared in this browser. This can't be undone.");
    await click(".pickup-ask", "Clear and start again");
    check("cleared", [await count(".pickup"), await stored(progressKey("ada", `lesson:${ids.lesson}`))], [0, null]);
  },

  // The lesson was edited: a screen that's gone starts its concept again, and the card says why.
  async "progress-changed"() {
    await as("ada");
    await seed(progressKey("ada", `lesson:${ids.lesson}`), {
      v: 1, at: Date.now() - 3 * 86400e3, total: 3, primer: { done: true, page: 4 },
      current: { concept: GALTON.reg, index: 1, screen: 6, screen_id: "an_activity_since_removed" },
      concepts: { [GALTON.mid]: concept({ finished: true }), [GALTON.reg]: concept({ screen: 6, screen_id: "an_activity_since_removed" }) }, finished_at: null });
    await open(`#/lesson/${ids.lesson}`);
    check("the card", [await text(".pickup-where"), await text(".pickup-changed")],
      [`Concept 2 of 3: ${T2}`, "This lesson has changed since you were last here, so you'll continue from the start of concept 2."]);
    await click(".pickup", "Continue");
    check("Continue opens concept 2 at its start", [await railTitle(), await texts(".action-bar button")], [`Concept 2 of 3: ${T2}`, ["Start the concept"]]);
    // A saved place for a concept that no longer exists at all goes to the first unfinished concept.
    await seed(progressKey("ada", `lesson:${ids.lesson}`), {
      v: 1, at: Date.now(), total: 4, primer: { done: true, page: 4 },
      current: { concept: "a_removed_concept", index: 3, screen: 2, screen_id: "walk" },
      concepts: { [GALTON.mid]: concept({ finished: true }), a_removed_concept: concept({ screen: 2, screen_id: "walk" }) }, finished_at: null });
    await open(`#/lesson/${ids.lesson}`);
    check("a removed concept: the first unfinished one", await text(".pickup-where"), `Concept 2 of 3: ${T2}`);
  },

  // Signed out, a gallery lesson keeps its place too, in the idea in brief; and another account never sees it.
  async "progress-gallery"() {
    await as(null);
    await open("#/gallery/galton-1886");
    await click(".overview .actions", "Read the idea in brief");
    await click(".overview .actions", "Next");
    check("on page 2", await h1(), "A clue from seeds");
    await open("#/gallery/galton-1886");
    check("the card names the page", await text(".pickup-where"), "The idea in brief, page 2 of 5: A clue from seeds");
    await click(".pickup", "Continue");
    check("Continue opens that page", await h1(), "A clue from seeds");
    await as("grace");
    await open("#/gallery/galton-1886");
    check("a signed-in account has its own place", await count(".pickup"), 0);
  },

  // The author shares from the library: the share page, the link, a setting saved straight away, the library's note.
  async "share-author"() {
    await as("ada");
    await open("#/library");
    await click(libRow(ids.lesson), "Share");
    check("the share page", [page.url().endsWith(`#/share/${ids.lesson}`), await h1()], [true, "Share this lesson"]);
    check("the choices start as the defaults", await checked(".share-opt input"), [true, false, false]);
    check("their names", await texts(".share-opt .po-name"), ["Show my name", "Let readers download it", "Also list it in the gallery"]);
    check("one primary: Share lesson", await primaries(), ["Share lesson"]);
    await click(".share-card", "Share lesson");
    check("shared", await until(async () => ((await text(".share-card .ai-state")) || "").startsWith("Shared."), 10000), true);  // after its checks run
    const link = await value("#share-link");
    check("the link", /#\/shared\/[A-Za-z0-9_-]{22,64}$/.test(link) && link.startsWith(cfg.base), true);
    check("no readers yet", await text(".share-readers .share-none"), "No one has started reading it yet.");
    await page.click(".share-opt:nth-child(2) input");
    check("a change is saved straight away", await until(async () => (await text(".share-saved")) === "Saved.", 5000), true);
    await click(".share-card", "Copy link");
    check("Copy link says it copied", await until(async () => (await texts(".share-card button")).includes("Copied"), 3000), true);
    await open("#/library");
    check("the library notes it", (await text(`${libRow(ids.lesson)} .lib-meta`)).includes("Shared by link · 0 readers"), true);
    await open(`#/lesson/${ids.lesson}`);
    check("the intro offers Share too", (await texts(".overview .actions button")).includes("Share"), true);
  },

  // Signed out, a shared link asks to sign in, naming the lesson, and comes back to it after.
  async "share-signed-out"() {
    await as(null);
    await open(`#/shared/${ids.token}`);
    check("sign in to read it", await h1(), "Sign in to read this lesson");
    check("the lesson is named", [await text(".signin-lesson .t"), await text(".signin-lead")],
      [ids.title, "Ada Lovelace shared a lesson with you. You'll go straight to it after signing in."]);
    check("what the author will see", (await texts(".signin-points li")).includes("Once you start, Ada Lovelace will see your name and how far you get."), true);
    check("where to come back to", await page.evaluate(() => JSON.parse(sessionStorage.getItem("lemma.held") || "{}").route), `#/shared/${ids.token}`);
  },

  // A reader: who shared it, what they see, no editing; the download only if allowed; progress reported and kept;
  // "Shared with you" in the library.
  async "share-reader"() {
    await as("grace");
    await open(`#/shared/${ids.token}`);
    check("the lesson", await h1(), ids.title);
    check("who shared it", await text(".sharedby"), "Shared by Ada Lovelace");
    check("what the author sees, and from when", await text(".seen"), "Once you start, Ada Lovelace can see your name and how far you get in this lesson. Your answers stay in your browser.");
    const buttons = await texts(".overview .actions button");
    check("no editing or sharing", [buttons.includes("Edit lesson"), buttons.includes("Share")], [false, false]);
    check("the download, as the author chose", buttons.includes("Download for offline use"), !!cfg.downloadable);
    await readTheBrief();
    await advance(); await advance();  // into concept 1: title → meet → how it works
    await pause(600);  // the report is sent as the concept opens
    await open(`#/shared/${ids.token}`);
    check("the place is kept for a shared lesson too", await text(".pickup-where"), `Concept 1 of 3: ${T1}`);
    check("under the share, in this browser", !!(await stored(progressKey("grace", `shared:${ids.share}`))), true);
    await open("#/library");
    check("Shared with you", await text(".lib-shared .lib-sec-head h2"), "Shared with you");
    check("the row", [await text(".lib-shared .lib-title"), (await text(".lib-shared .lib-meta")).includes("Shared by Ada Lovelace"), await text(".lib-shared .lib-progress")],
      [ids.title, true, "Concept 1 of 3"]);
    check("its actions", await texts(".lib-shared .lib-acts button"), cfg.downloadable ? ["Download", "Remove"] : ["Remove"]);
    await click(".lib-shared", "Remove");
    check("Remove takes it off the list", await count(".lib-shared .lib-row"), 0);
  },

  // The author sees the reader by name, with how far they got.
  async "share-readers"() {
    await as("ada");
    await open(`#/share/${ids.lesson}`);
    check("the tiles", await texts(".share-readers .share-tile dd"), ["1", "1", "0"]);
    check("the reader", [await texts(".share-reader-name"), await texts(".share-reader .lib-progress")], [["Grace Hopper"], ["Concept 1 of 3"]]);
  },

  // Stop sharing asks, then the link is dead for readers.
  async "share-stop"() {
    await as("ada");
    await open(`#/share/${ids.lesson}`);
    await click(".share-card", "Stop sharing");
    check("it asks", await text(".share-ask p"), "Stop sharing this lesson? The link stops working straight away. If you share it again, it gets a new link.");
    check("Keep sharing has focus", await focused(), "Keep sharing");
    await click(".share-ask", "Keep sharing");
    check("Keep sharing keeps it", await count(".share-ask"), 0);
    await click(".share-card", "Stop sharing");
    await click(".share-ask", "Stop sharing");
    check("back to not shared", await primaries(), ["Share lesson"]);
    await as("grace");
    await open(`#/shared/${ids.token}`);
    check("the old link is dead", await text(".shared-gone h1"), "This lesson is no longer shared");
    check("with a way on", await texts(".shared-gone .actions a"), ["Open the gallery", "Go to the home page"]);
  },

  // The gallery's community section, signed out; opening a card asks to sign in; a reader of a listed lesson is told
  // the author sees totals only.
  async "gallery-community"() {
    await as(null);
    await open("#/gallery");
    check("two sections", await texts(".gallery-page h2.gal-sec-title"), ["From OpenLemma", "From the community"]);
    check("the count", await text(".gal-count-line"), "19 from OpenLemma · 1 from the community");
    check("the built-in lessons are all there", await count(".gal-builtin .gal-item:not(.gal-skel)"), 19);
    check("the community card", [await text(".gal-community .gal-title"), await text(".gal-community .gal-by")], [ids.title, "Shared by Ada Lovelace"]);
    check("led by its own model", await count(".gal-community .gal-plate svg"), 1);
    await page.type("#gal-find", "galton");
    await pause(200);
    check("the search covers both sections", [await count(".gal-community .gal-item:not([hidden])"), await text(".gal-count-line")],
      [1, "2 of 20 lessons"]);
    await page.click(".gal-community .gal-title a");
    await page.waitForSelector("main h1");
    await pause(300);
    check("opening it asks to sign in", await h1(), "Sign in to read this lesson");
    await as("grace");
    await open(`#/shared/${ids.token}`);
    check("a listed lesson's note", await text(".seen"), "The author sees only how many readers reach each concept, not who. Your answers stay in your browser.");
  },

  // Many community lessons: the first row's models are drawn at once, the rest as they come into view, as the
  // built-in lessons are.
  async "community-lazy"() {
    await as(null);
    await open("#/gallery");
    check("all the community cards are there", await until(async () => (await count(".gal-community .gal-item")) === 8, 8000), true);
    check("only the first row's models are drawn at once", await count(".gal-community .gal-plate[data-drawn]"), 3);
    await page.evaluate(async () => {  // scrolled through, as someone reading down the page would
      for (let y = 0; y <= document.body.scrollHeight; y += 400) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 60)); }
    });
    check("the rest as they come into view", await until(async () => (await count(".gal-community .gal-plate[data-drawn]")) === 8, 5000), true);
  },

  // An admin reviews from the account page: the waiting lesson, previewed, then listed.
  async "gallery-review"() {
    await as("admin");
    await open("#/account");
    check("the account row", await text(".af-row.af-review dd"), "1 waiting");
    await open("#/gallery/review");
    check("the page", [await h1(), await text(".rv-count")], ["Gallery review", "1 waiting"]);
    check("the row", [await text(".rv-row .rv-title"), (await text(".rv-row .fbx-ctx")).includes("Ada Lovelace · ada@example.com")], [ids.title, true]);
    check("its actions", await texts(".rv-row .rv-acts button"), ["Preview", "List it", "Don't list"]);
    await click(".rv-row", "Preview");
    await page.waitForSelector(".overview h1");
    check("the preview is the lesson", await h1(), ids.title);
    check("with no note meant for its readers", await count(".seen"), 0);
    await click(".overview .actions", "Leave lesson");
    check("leaving goes back to the review", await until(async () => (await h1()) === "Gallery review", 5000), true);
    await click(".rv-row", "List it");
    check("it leaves the waiting list", await until(async () => (await count(".rv-row")) === 0, 5000), true);
    check("the count follows", await text(".rv-count"), "0 waiting");
    await as("ada");
    await open("#/gallery/review");
    check("not for anyone else", await text("main h1"), "Not found");
  },

  // A reader waiting for a lesson the server is still checking sees that it's opening, not the page they came from.
  async "shared-loading"() {
    await as("grace");
    await page.goto(new URL("#/library", cfg.base).href, { waitUntil: "networkidle0" });
    await page.evaluate((t) => { location.hash = `#/shared/${t}`; }, ids.token);
    check("it says the lesson is opening", await until(async () => (await text(".shared-loading")) === "Opening the lesson…", 3000), true);
    check("then the lesson opens", await until(async () => (await h1()) === ids.title, 10000), true);
  },

  // The editor: a lesson with a concept taught without a model saves from the form and from the JSON panel, and the
  // form only offers what each concept has. A lesson whose concepts all have models still saves as before.
  async "editor-model-free"() {
    await as("ada");
    for (const [id, title] of [[ids.free, ids.freeTitle], [ids.lesson, ids.title]]) {
      await open("#/library");
      await click(`.lib-lesson:has(.lib-open[href$="${id}"])`, "Edit");
      await page.waitForSelector("#f0");
      check(`${id}: the editor opens`, await h1(), "Edit lesson");
      if (id === ids.free) {
        const labels = await page.$$eval("fieldset", (fs) => fs.map((f) => [f.querySelector("legend").textContent, [...f.querySelectorAll("label")].map((l) => l.textContent)]));
        const free = labels.find(([legend]) => legend.startsWith(`Concept ${ids.freeIndex + 1}:`));
        check("a concept without a model has no model fields", ["Try-it prompt", "Teaching-model note", "Equation caption", "Use-it question"].filter((l) => free[1].includes(l)), []);
      }
      await page.$eval("#f0", (e) => { e.value = ""; });
      await page.type("#f0", `${title} (edited)`);
      await click(".sticky-actions", "Check and save");
      check(`${id}: the form saves`, await until(async () => (await text("main .ok")) === "Checked and saved to your library.", 8000), true);
      await page.click(".advanced summary");
      await until(async () => (await value("#json-edit")) !== "", 3000);  // the panel fills itself as it opens
      await page.$eval("#json-edit", (e, t) => { const l = JSON.parse(e.value); l.title = t; e.value = JSON.stringify(l, null, 2); }, `${title} (edited twice)`);
      await click(".sticky-actions", "Check and save");
      const saved = await until(async () => (await text("main .ok")) === "Checked and saved to your library." || (await count("main .error")) > 0, 8000);
      check(`${id}: the JSON panel saves`, [saved, await text("main .ok"), await text("main .error > p")], [true, "Checked and saved to your library.", null]);
    }
  },

  // A title with a very long word (any author's, shown to others now) wraps inside its column on every page it's on.
  async "long-title"() {
    await as("ada");
    const inside = (sel) => page.$eval(sel, (e) => e.scrollWidth <= e.clientWidth + 1 && e.getBoundingClientRect().right <= (e.parentElement.getBoundingClientRect().right + 1));
    await open(`#/lesson/${ids.long}`);
    check("the lesson's title stays in its column", await inside(".overview h1"), true);
    check("and clear of the concept list", await page.evaluate(() => document.querySelector(".overview h1").getBoundingClientRect().right <= document.querySelector(".hall").getBoundingClientRect().left), true);
    await open(`#/share/${ids.long}`);
    check("the share page's title stays in its card", await inside(".share-head .lead"), true);
    await open("#/library");
    check("the library row's title stays in its row", await inside(`.lib-lesson:has(.lib-open[href$="${ids.long}"]) .lib-title`), true);
    check("nothing wider than the page", await overflows(), false);
  },

  // Editing a listed lesson: saved, and back to review before it shows in the gallery again.
  async "edit-listed"() {
    await as("ada");
    await open("#/library");
    await click(libRow(ids.lesson), "Edit");
    await page.waitForSelector("#f0");
    await page.$eval("#f0", (e) => { e.value = ""; });
    await page.type("#f0", "A title the gallery hasn't seen");
    await click(".sticky-actions", "Check and save");
    check("saved, and it says so", await until(async () => (await text("main .ok")) === "Checked and saved to your library. It's waiting for review before it shows in the gallery again.", 10000), true);
    await open(`#/share/${ids.lesson}`);
    check("the share page says it's waiting", await text(".share-opt:nth-child(3) .share-status"), "Waiting for review");
    await as(null);
    await open("#/gallery");
    check("and the gallery doesn't show it meanwhile", await until(async () => (await count(".gal-community .gal-item")) === 0 && (await text(".gal-count-line") || "").endsWith("lessons"), 5000), true);
  },

  // A downloaded lesson whose source link is a disguised script: clicking it runs nothing, and the link isn't one.
  async "offline-link"() {
    await page.goto(`file://${cfg.file}`, { waitUntil: "load" });
    await page.waitForSelector(".overview h1");
    check("the disguised links are dropped", await page.$$eval("a", (as) => as.filter((a) => /script:/i.test(a.getAttribute("href") || "")).length), 0);
    const ran = await page.evaluate(() => {  // even forced onto a link, the offline file's policy refuses to run it
      const a = document.createElement("a");
      a.href = "java\tscript:window.__ran = 1";
      document.body.append(a);
      a.click();
      return new Promise((r) => setTimeout(() => r(window.__ran || 0), 300));
    });
    check("no script runs", ran, 0);
  },

  // Downloads start: from the library, from "Shared with you" and from a shared lesson's first page. (The app's own
  // blob: link for the file must not be taken for a lesson's link and dropped.)
  async "downloads"() {
    const watch = () => page.evaluate(() => {
      window.__downloads = [];
      const click = HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click = function () {
        if (this.hasAttribute("download")) window.__downloads.push([this.getAttribute("href") || "", this.getAttribute("download")]);
        return click.call(this);
      };
    });
    const started = async () => (await until(async () => (await page.evaluate(() => window.__downloads.length)) > 0, 8000))
      && page.evaluate(() => window.__downloads.at(-1));
    const isFile = (d) => !!d && d[0].startsWith("blob:") && d[1].endsWith(".html");
    await as("ada");
    await open("#/library");
    await watch();
    await click(libRow(ids.lesson), "Download");
    check("from the library", isFile(await started()), true);
    await as("grace");
    await open("#/library");
    await watch();
    await click(".lib-shared", "Download");
    check("from Shared with you", isFile(await started()), true);
    await open(`#/shared/${ids.token}`);
    await watch();
    await click(".overview .actions", "Download for offline use");
    check("from a shared lesson's first page", isFile(await started()), true);
  },

  // On a phone: the card and the share page fit, and the readers' rows stack.
  async "phone-progress-sharing"() {
    await as("ada");
    await seed(progressKey("ada", `lesson:${ids.lesson}`), { v: 1, at: Date.now(), total: 3, primer: { done: true, page: 4 },
      current: { concept: GALTON.reg, index: 1, screen: 4, screen_id: "goal_0" }, concepts: { [GALTON.mid]: concept({ finished: true }), [GALTON.reg]: concept({ screen: 4, screen_id: "goal_0" }) }, finished_at: null });
    await open(`#/lesson/${ids.lesson}`);
    check("the intro fits", await overflows(), false);
    check("the card is on the first screen", await page.$eval(".pickup", (e) => e.getBoundingClientRect().top < innerHeight), true);
    await open(`#/share/${ids.lesson}`);
    check("the share page fits", await overflows(), false);
    check("the concept count stays on one line", await page.$eval(".share-head .share-count", (e) => e.getClientRects().length).catch(() => 0), 1);
    await open("#/library");
    check("the library fits", await overflows(), false);
    check("each row's actions fit on one line", await page.$$eval(".lib-lesson .lib-acts", (rows) => rows.length > 0 && rows.every((a) =>
      new Set([...a.children].filter((b) => b.offsetParent).map((b) => Math.round(b.getBoundingClientRect().top))).size === 1)), true);
  },
});

try {
  if (!FLOWS[cfg.flow]) throw new Error(`no flow "${cfg.flow}"`);
  await FLOWS[cfg.flow]();
} catch (e) {
  failed++;
  console.log(`FAIL  ${e.stack || e}`);
} finally {
  await snap();
  // A flow may expect some, such as the browser's note of a request the server refused on purpose.
  check("no script errors", problems.filter((p) => !(cfg.expectErrors || []).some((e) => p.includes(e))), []);
  await browser.close();
}
process.exit(failed ? 1 : 0);
