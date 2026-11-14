// A trace on the concept's own causal model, in a real browser, driven by tests/test_model_trace.py:
// `node tests/model_trace_ui.mjs '<json>'`, where the JSON gives the browser, the downloaded lesson (a file: URL) and
// the model's nodes, edges and traces. The lesson is opened from disk with every other request blocked, as a
// downloaded lesson is used offline. It prints "PASS <check>" or "FAIL <check> :: <why>" for each check.
import puppeteer from "puppeteer-core";

const cfg = JSON.parse(process.argv[2]);
const [loop, parts] = cfg.traces.filter((t) => t.on === "model");
const authored = cfg.traces.find((t) => !t.on);
const phone = cfg.flow === "phone";
let failed = 0;
const problems = [], requests = [];

async function check(label, fn) {
  try {
    const [got, want] = await fn();
    const ok = JSON.stringify(got) === JSON.stringify(want);
    if (!ok) failed++;
    console.log(ok ? `PASS ${label}` : `FAIL ${label} :: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
  } catch (e) {
    failed++;
    console.log(`FAIL ${label} :: ${String((e && e.message) || e).split("\n")[0]}`);
  }
}

const browser = await puppeteer.launch({ executablePath: cfg.chrome, headless: true, args: ["--no-sandbox", "--disable-dev-shm-usage"],
  defaultViewport: phone ? { width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true } : { width: 1280, height: 900 } });
try {
  await (async () => {
  const page = await browser.newPage();
  page.setDefaultTimeout(8000);
  page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") problems.push(`console: ${m.text()}`); });
  await page.setRequestInterception(true);
  page.on("request", (r) => {
    const url = r.url();
    if (url === cfg.file || url.startsWith("data:")) return r.continue();
    requests.push(url);
    r.abort();
  });

  // ---------------------------------------------------------------- helpers
  const pause = (ms) => new Promise((r) => setTimeout(r, ms));
  const labels = cfg.nodes.map((n) => n.label);
  const copy = ".stage .activity-lab";
  const node = (id) => `${copy} [data-node="${id}"]`;
  const edge = (from, to) => `${copy} .cedge[data-from="${from}"][data-to="${to}"]`;
  const attr = (sel, name) => page.$eval(sel, (e, name) => e.getAttribute(name), name);
  const classes = (sel) => page.$eval(sel, (e) => [...e.classList]);
  const count = (sel) => page.$$eval(sel, (es) => es.length);
  const texts = (sel) => page.$$eval(sel, (es) => es.map((e) => e.textContent.trim()));
  const status = () => page.$eval(`${copy} .activity-feedback`, (e) => e.textContent.trim());
  const pressed = () => page.$$eval(`${copy} [data-node][aria-pressed="true"]`, (es) => es.map((e) => e.getAttribute("data-node")));
  const pathOrder = () => page.$$eval(`${copy} [data-node]`, (es) => es
    .map((e) => [e.getAttribute("data-node"), Number((e.querySelector(".trace-order") || {}).textContent || 0)])
    .filter(([, k]) => k > 0).sort((a, b) => a[1] - b[1]).map(([id]) => id));
  async function press(scope, label) {
    await page.evaluate((scope, label) => {
      const b = [...document.querySelectorAll(`${scope} button`)].find((x) => x.textContent.trim() === label);
      if (!b) throw new Error(`no "${label}" button in ${scope}`);
      b.click();
    }, scope, label);
    await pause(120);
  }
  const onward = () => press(".action-bar", (cfg.onward || "Continue"));
  async function to(label) { await press(".action-bar", label); }
  // Keyboard focus on a node of the picture (page.focus only takes HTML elements); says whether it took it.
  const focusOn = (sel) => page.$eval(sel, (e) => { e.focus(); return document.activeElement === e; });
  const prompt = () => page.$eval(`${copy} .activity-prompt`, (e) => e.textContent.trim()).catch(() => null);
  const scrollNote = () => page.$$eval(`${copy} .trace-scroll-note`, (ns) => ns.filter((n) => n.getClientRects().length).map((n) => n.textContent.trim()));
  const focused = (sel) => page.$eval(sel, (e) => document.activeElement === e);
  // The focus ring of a node, as drawn: whether it shows, its colour and its dashes.
  const ring = (sel) => page.$eval(sel, (g) => {
    const r = g.querySelector(".trace-focus-ring");
    if (!r) return { shown: false, stroke: null, dashed: false };
    const cs = getComputedStyle(r);
    return { shown: cs.visibility === "visible" && cs.display !== "none", stroke: cs.stroke, dashed: cs.strokeDasharray !== "none" };
  });
  const pickedStroke = (sel) => page.$eval(sel, (g) => getComputedStyle(g.querySelector("rect.cnode, circle:not(.trace-focus-ring)")).stroke);

  // ---------------------------------------------------------------- the downloaded lesson, offline
  await page.goto(cfg.file, { waitUntil: "load" });
  await page.waitForSelector("main h1");
  await press("main", "Start the first concept");
  await to("Start the concept");  // the concept's title screen
  await onward();  // the explanation
  await page.waitForSelector(`${copy} svg`).catch(() => {});
  let hadCopy = false;

  if (phone) {  // a phone, 390 px wide: the copy stays readable and tappable, and only the copy scrolls sideways
    await check("2a phone: node labels are at least 11 px", async () => {
      const px = await page.$eval(`${copy} svg.viz`, (s) => (14 * s.getBoundingClientRect().width) / s.viewBox.baseVal.width);
      return [px >= 11, true];
    });
    await check("2a phone: every node is at least 24 by 24 px to tap", async () => {
      const sizes = await page.$$eval(`${copy} [data-node] rect.cnode`, (rs) => rs.map((r) => { const b = r.getBoundingClientRect(); return b.width >= 24 && b.height >= 24; }));
      return [sizes, cfg.nodes.map(() => true)];
    });
    await check("2b phone: the page doesn't scroll sideways", async () => [await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true]);
    await check("2b phone: focusing the right-most node brings it into view", async () => {
      const right = [...cfg.nodes].sort((a, b) => b.x - a.x)[0].id;
      await focusOn(node(right));
      await pause(300);
      return [await page.$eval(node(right), (g) => { const b = g.querySelector("rect.cnode").getBoundingClientRect(); return b.left >= 0 && b.right <= innerWidth; }), true];
    });
    await check("2b phone: a note says the model scrolls sideways", async () => [await scrollNote(), ["Swipe sideways to see the whole model."]]);
    await check("2c phone: no tap highlight on the nodes", async () => [await page.$eval(node("temp"), (g) => getComputedStyle(g).webkitTapHighlightColor), "rgba(0, 0, 0, 0)"]);
    await check("2 phone: tapping picks a node", async () => {
      await page.$eval(`${copy}`, (e) => e.scrollIntoView());
      await page.tap(`${node("temp")} rect`);
      await pause(150);
      return [await attr(node("temp"), "aria-pressed"), "true"];
    });
    await check("2 phone: no page errors", async () => [problems, []]);
    return;
  }

  await check("2d desktop: no note about scrolling", async () => [await scrollNote(), []]);
  await check("2d desktop: the copy fits its box, with nothing to scroll", async () => [await page.$eval(`${copy} svg.viz`, (s) => {
    let box = s.parentElement;
    while (box && !box.classList.contains("activity-lab") && getComputedStyle(box).overflowX === "visible") box = box.parentElement;
    return !box || box.classList.contains("activity-lab") || box.scrollWidth <= box.clientWidth;
  }), true]);

  // The path trace, drawn in the model's defaults.
  await check("41 the copy is inside the activity", async () => [await count(`${copy} svg [data-node]`), cfg.nodes.length]);
  hadCopy = (await count(`${copy} svg [data-node]`)) === cfg.nodes.length;
  await check("41 the live model panel is not on the stage", async () => [[hadCopy, await count(".stage .model-panel")], [true, 0]]);
  await check("42 the copy shows the model's labels", async () => [await texts(`${copy} [data-node] .cnode-label`), labels]);
  await check("42 the copy shows the model's values", async () => [await count(`${copy} [data-node] .cnode-value`), cfg.nodes.filter((n) => n.value !== undefined).length]);
  await check("42 the copy shows the model's arrows", async () => [await page.$$eval(`${copy} .cedge`, (es) => es.map((e) => [e.getAttribute("data-from"), e.getAttribute("data-to"), !!e.getAttribute("marker-end")])),
    cfg.edges.map((e) => [e.from, e.to, true])]);
  await check("42 the copy keeps the model's legend", async () => [(await texts(`${copy} .legend .legend-item`)).some((t) => t.startsWith("Positive effect")), true]);
  await check("42 the copy is a group named by the prompt", async () => [[await attr(`${copy} svg.viz`, "role"), await attr(`${copy} svg.viz`, "aria-label")], ["group", loop.prompt]]);
  await check("27 the copy is drawn in the model's defaults", async () => [(await classes(edge("temp", "ice"))).includes("neg"), true]);

  await check("30 Enter picks a node and stays on the screen", async () => {
    const focused = await focusOn(node("temp"));
    await page.keyboard.press("Enter");
    await pause(150);
    return [[focused, await attr(node("temp"), "aria-pressed"), await prompt()], [true, "true", loop.prompt]];
  });
  await check("30 Space picks a node", async () => {
    const focused = await focusOn(node("ice"));
    await page.keyboard.press("Space");
    await pause(150);
    return [[focused, await attr(node("ice"), "aria-pressed"), await prompt()], [true, "true", loop.prompt]];
  });
  await check("1c focus stays on a node picked by keyboard", async () => [await focused(node("ice")), true]);
  await check("1a a focused picked node shows its focus ring, and a picked node without focus doesn't", async () =>
    [[(await ring(node("ice"))).shown, (await ring(node("temp"))).shown], [true, false]]);
  await check("1b the focus ring is dashed, and not the picked colour", async () => {
    const r = await ring(node("ice"));
    return [[r.dashed, r.stroke !== null && r.stroke !== (await pickedStroke(node("temp")))], [true, true]];
  });
  await check("31 a picked node is pressed and says its place", async () => [await attr(node("ice"), "aria-label"), "Ice cover, selected 2"]);
  await check("32 a picked node shows its place in the path", async () => [await pathOrder(), ["temp", "ice"]]);
  await check("35 a wrong path is not yet", async () => {
    await press(copy, "Check");
    return [await status(), "Not yet. Follow the links from the start, one step at a time."];
  });
  await check("37 Clear empties the picks", async () => {
    await press(copy, "Clear");
    return [[await pressed(), await status()], [[], ""]];
  });
  await check("7a clicking the part of a label past its box picks the node", async () => {
    const long = [...cfg.nodes].sort((a, b) => b.label.length - a.label.length)[0].id;
    const at = await page.$eval(node(long), (g) => { const r = g.querySelector("rect.cnode").getBoundingClientRect(), t = g.querySelector(".cnode-label").getBoundingClientRect(); return { over: t.right - r.right, x: t.right - 2, y: t.top + t.height / 2 }; });
    await page.mouse.click(at.x, at.y);
    await pause(120);
    return [[at.over > 4, await attr(node(long), "aria-pressed")], [true, "true"]];
  });
  await check("7b clicking empty space next to a node picks nothing", async () => {
    await press(copy, "Clear");
    const at = await page.$eval(`${copy} svg.viz`, (s) => { const b = s.getBoundingClientRect(); return { x: b.left + 4, y: b.top + 4 }; });
    await page.mouse.click(at.x, at.y);
    await pause(120);
    return [await pressed(), []];
  });
  await check("29 clicking picks nodes in order", async () => {
    for (const id of loop.answer) { await page.click(`${node(id)} rect`); await pause(60); }
    return [await pathOrder(), loop.answer];
  });
  await check("33 links along the picked path are highlighted", async () => {
    const steps = loop.answer.slice(1).map((to, i) => [loop.answer[i], to]);
    const on = [];
    for (const [a, b] of steps) on.push((await classes(edge(a, b))).includes("picked"));
    return [[...on, (await classes(edge("push", "temp"))).includes("picked")], [...steps.map(() => true), false]];
  });
  let completed = false;  // the trace was completed, in the downloaded file with no network
  await check("35 the right path completes with the explanation", async () => {
    await press(copy, "Check");
    completed = (await status()) === loop.explanation;
    return [await status(), loop.explanation];
  });
  await check("36 Show me picks the answer and completes", async () => {
    await press(copy, "Clear");
    await press(copy, "Show me");
    return [[await pathOrder(), await status()], [loop.answer, loop.explanation]];
  });

  // The set trace, drawn in the block's values (the ice held fixed).
  await onward();
  await page.waitForFunction((p) => document.querySelector(".stage .activity-lab .activity-prompt")?.textContent.trim() === p, {}, parts.prompt).catch(() => {});
  hadCopy = hadCopy && (await count(`${copy} svg [data-node]`)) === cfg.nodes.length;
  await check("27 the copy is drawn in the block's values", async () => [[await prompt(), (await classes(edge("temp", "ice"))).includes("zero")], [parts.prompt, true]]);
  await check("34 the right set in any order completes", async () => {
    for (const id of [...parts.answer].reverse()) { await page.click(`${node(id)} rect`); await pause(60); }
    await press(copy, "Check");
    return [[await pressed(), await status()], [cfg.nodes.map((n) => n.id).filter((id) => parts.answer.includes(id)), parts.explanation]];
  });

  // A trace on its own, authored diagram: picking by keyboard keeps focus, and focus shows on a picked node.
  await onward();
  await page.waitForSelector(".stage .trace-diagram").catch(() => {});
  const authoredNode = (i) => `.stage .trace-diagram .trace-node:nth-of-type(${i + 1})`;
  await check("10 an authored trace keeps focus on a node picked by keyboard", async () => {
    const took = await focusOn(authoredNode(0));
    await page.keyboard.press("Enter");
    await pause(150);
    return [[took, await page.evaluate(() => { const a = document.activeElement; return a.classList.contains("trace-node") && a.getAttribute("aria-pressed"); })], [true, "true"]];
  });
  await check("1d an authored trace shows the focus ring on a focused picked node", async () => {
    await page.keyboard.press("Tab");  // on to the second node, then pick it too
    await page.keyboard.press("Enter");
    await pause(150);
    const label = await page.evaluate(() => document.activeElement.getAttribute("aria-label"));
    return [[label, (await ring(authoredNode(1))).shown, (await ring(authoredNode(0))).shown], [`${authored.nodes[1].label}, selected 2`, true, false]];
  });

  // A goal on the live model: the copies are gone, and the live causal model draws as it always has.
  await onward();
  await pause(300);
  await check("44 leaving the screen removes the copy", async () => [[hadCopy, await count("[data-node][role=button]"), await count(".activity-lab")], [true, 0, 0]]);
  await check("43 the live causal model draws as before", async () => {
    const live = ".stage .model-panel svg.viz";
    return [[await attr(live, "role"), await texts(`${live} .cnode-label`), await count(`${live} .cedge`), await count(`${live} [role=button]`), await count(`${live} [tabindex]`)],
      ["img", labels, cfg.edges.length, 0, 0]];
  });

  await check("46 the trace works offline, with no network requests", async () => [[completed, requests], [true, []]]);
  await check("46 no page errors", async () => [problems, []]);
  })();
} finally {
  await browser.close();
}
process.exitCode = failed ? 1 : 0;
