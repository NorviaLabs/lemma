// Prints kernel metrics and expression results as JSON for comparison with Python.
require("../lemma/static/expr.js");
require("../lemma/static/kernels.js");
const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
const out = { kernels: cases.kernels.map(([k, p]) => LemmaKernels.run(k, p).metrics),
  exprs: cases.exprs.map(([e, env]) => { try { return LemmaExpr.evaluate(e, env); } catch (err) { return "ERR"; } }) };
process.stdout.write(JSON.stringify(out));
