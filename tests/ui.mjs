// The app in a real browser, driven by tests/test_ui.py: `node tests/ui.mjs '<json>'`, where the JSON gives the
// server's address, a session cookie, the browser and the flow to run, with the builds it sets up. Each flow prints a
// line per check, "PASS …" or "FAIL …", and the process fails if any check does.
//
// With "coverage" (a folder), it also saves the browser's coverage of app.js and player.js there, for c8. The browser
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
await page.setCookie({ name: cfg.cookie.name, value: cfg.cookie.value, domain: base.hostname, path: "/" });
if (cfg.cred) {  // the learner's AI provider, as the browser keeps it
  await page.evaluateOnNewDocument((c) => localStorage.setItem("lemma.ai", JSON.stringify(c)), cfg.cred);
}

let snaps = 0;
if (cfg.coverage) await page.coverage.startJSCoverage({ resetOnNavigation: false, includeRawScriptCoverage: true });
async function snap() {
  if (!cfg.coverage) return;
  const entries = await page.coverage.stopJSCoverage();
  const result = entries.filter((e) => e.rawScriptCoverage && /\/static\/(app|player)\.js/.test(e.url))
    .map((e) => ({ ...e.rawScriptCoverage, url: new URL(`../lemma/static/${e.url.split("/").pop().split("?")[0]}`, import.meta.url).href }));
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
