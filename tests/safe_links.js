// Run by tests/test_security.py: node tests/safe_links.js '{"bad": [...], "good": [...]}'. The one rule for a lesson's
// links, LemmaUI.safeUrl (ui.js), keeps web, mail and in-page links and drops everything else however it's disguised;
// the one element builder, which the app's modules and the player share, uses it.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
require("../lemma/static/ui.js");
const { bad, good } = JSON.parse(process.argv[2]);
let failed = 0;
const safe = globalThis.LemmaUI && globalThis.LemmaUI.safeUrl;
function check(label, fn) {
  try { fn(); console.log(`PASS ${label}`); } catch (e) { failed++; console.log(`FAIL ${label} :: ${e.message}`); }
}
check("ui.js offers safeUrl", () => assert.equal(typeof safe, "function"));
for (const base of ["https://openlemma.org/", "file:///home/someone/lesson.html"]) {
  for (const u of bad) check(`${JSON.stringify(u)} is dropped (page at ${base})`, () => assert.equal(safe(u, base), null));
  for (const u of good.filter((g) => !(base.startsWith("file:") && /^(privacy|static\/)/.test(g)))) {
    check(`${JSON.stringify(u)} is kept (page at ${base})`, () => assert.equal(safe(u, base), u));
  }
}
const read = (file) => fs.readFileSync(path.join(__dirname, "../lemma/static", file), "utf8");
check("ui.js's element builder uses safeUrl for links and sources", () => {
  const src = read("ui.js");
  assert.match(src, /\(k === "href" \|\| k === "src"\)[^\n]*safeUrl\(/);
  assert.doesNotMatch(src, /javascript\|vbscript\|data\)/);
});
// The app's modules (static/app/) take h from shell.js, which takes it from ui.js; the player takes it from ui.js.
const appModules = fs.readdirSync(path.join(__dirname, "../lemma/static/app")).filter((f) => f.endsWith(".js")).map((f) => `app/${f}`);
check("the app is made of modules", () => assert.ok(appModules.includes("app/main.js") && appModules.includes("app/shell.js")));
for (const file of ["app/shell.js", "player.js"]) {
  check(`${file} takes ui.js's h`, () => assert.match(read(file), /const \{ h,[^}]*\} = (root\.)?LemmaUI;/));
}
for (const file of [...appModules, "player.js"]) {
  check(`${file} has no element builder or link rule of its own`, () => {
    const src = read(file);
    assert.doesNotMatch(src, /function h\(|function safeUrl\(|const ICONS\b/);
    assert.doesNotMatch(src, /javascript\|vbscript\|data\)/);
    if (file.startsWith("app/") && file !== "app/shell.js" && /\bh\(/.test(src)) assert.match(src, /import \{[^}]*\bh\b[^}]*\} from "\.\/shell\.js";/);
  });
}
process.exit(failed ? 1 : 0);
