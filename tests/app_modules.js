// Run by tests/test_app_modules.py: node --experimental-vm-modules tests/app_modules.js. The app's ES modules
// (lemma/static/app/) are parsed and linked here without running them (they need a browser): every module parses,
// every import names a module that exists and a name that module exports, and main.js reaches every module.
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const dir = process.argv[2] || path.join(__dirname, "../lemma/static/app");
const files = fs.readdirSync(dir).filter((f) => f.endsWith(".js")).sort();
const modules = new Map();
let failed = 0;
function check(label, fn) {
  try { fn(); console.log(`PASS ${label}`); } catch (e) { failed++; console.log(`FAIL ${label} :: ${e.message}`); }
}
for (const f of files) {
  check(`${f} parses as a module`, () => {
    modules.set(f, new vm.SourceTextModule(fs.readFileSync(path.join(dir, f), "utf8"), { identifier: f }));
  });
}
const reached = new Set();
(async () => {
  const main = modules.get("main.js");
  try {
    await main.link((specifier, from) => {
      const name = path.posix.normalize(path.posix.join(path.posix.dirname(from.identifier), specifier));
      const m = modules.get(name);
      if (!m) throw new Error(`${from.identifier} imports ${specifier}, which isn't there`);
      reached.add(name);
      return m;
    });
    console.log("PASS every import names a module that exports it");
  } catch (e) {
    failed++;
    console.log(`FAIL every import names a module that exports it :: ${e.message}`);
  }
  reached.add("main.js");
  check("main.js reaches every module", () => {
    const missed = files.filter((f) => !reached.has(f));
    if (missed.length) throw new Error(`not imported: ${missed.join(", ")}`);
  });
  process.exit(failed ? 1 : 0);
})();
