/* Lemma expression language — browser twin of lemma/expr.py. Keep the two in step. */
(function (root) {
  "use strict";

  class ExprError extends Error {}
  const MAX_NESTING = 24; // keep in step with expr.py

  const TOKEN = /\s*(?:(\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)|([A-Za-z_][A-Za-z0-9_]*)|(<=|>=|==|!=|&&|\|\||[-+*/%^()<>!?:,]))/y;
  const KEYWORDS = { and: "&&", or: "||", not: "!" };

  function tokenize(src) {
    if (typeof src !== "string") throw new ExprError("expression must be a string");
    src = src.trim();
    const toks = [];
    let pos = 0;
    while (pos < src.length) {
      TOKEN.lastIndex = pos;
      const m = TOKEN.exec(src);
      if (!m || TOKEN.lastIndex === pos) throw new ExprError(`unexpected character '${src[pos]}' in '${src}'`);
      if (m[1] !== undefined) toks.push(["num", m[1]]);
      else if (m[2] !== undefined) toks.push(KEYWORDS[m[2]] ? ["op", KEYWORDS[m[2]]] : ["name", m[2]]);
      else toks.push(["op", m[3]]);
      pos = TOKEN.lastIndex;
    }
    toks.push(["end", ""]);
    return toks;
  }

  function erf(x) {
    const s = x >= 0 ? 1 : -1;
    x = Math.abs(x);
    const t = 1 / (1 + 0.3275911 * x);
    const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
    return s * y;
  }
  function normcdf(x, mu = 0, sd = 1) {
    if (sd <= 0) return NaN;
    return 0.5 * (1 + erf((x - mu) / (sd * Math.sqrt(2))));
  }
  function normpdf(x, mu = 0, sd = 1) {
    if (sd <= 0) return NaN;
    const z = (x - mu) / sd;
    return Math.exp(-0.5 * z * z) / (sd * Math.sqrt(2 * Math.PI));
  }
  function norminv(p, mu = 0, sd = 1) {
    if (p <= 0) return -Infinity;
    if (p >= 1) return Infinity;
    const a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.38357751867269e2, -3.066479806614716e1, 2.506628277459239];
    const b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1];
    const c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    const d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416];
    const plow = 0.02425;
    let z, q, r;
    if (p < plow) {
      q = Math.sqrt(-2 * Math.log(p));
      z = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
    } else if (p <= 1 - plow) {
      q = p - 0.5;
      r = q * q;
      z = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
    } else {
      q = Math.sqrt(-2 * Math.log(1 - p));
      z = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
    }
    return mu + sd * z;
  }
  function binom(n, k) {
    n = Math.round(n); k = Math.round(k);
    if (k < 0 || k > n || n < 0) return 0;
    let r = 1;
    for (let i = 1; i <= k; i++) r = (r * (n - k + i)) / i;
    return Math.round(r);
  }

  const FUNCTIONS = {
    abs: [Math.abs, 1, 1], sqrt: [Math.sqrt, 1, 1], exp: [Math.exp, 1, 1],
    log: [Math.log, 1, 1], ln: [Math.log, 1, 1], log10: [(x) => Math.log(x) / Math.log(10), 1, 1],
    pow: [Math.pow, 2, 2], min: [Math.min, 1, 16], max: [Math.max, 1, 16],
    floor: [Math.floor, 1, 1], ceil: [Math.ceil, 1, 1],
    round: [(x, dg = 0) => { const f = Math.pow(10, Math.trunc(dg)); return Math.floor(x * f + 0.5) / f; }, 1, 2],
    clamp: [(x, lo, hi) => Math.min(Math.max(x, lo), hi), 3, 3],
    sin: [Math.sin, 1, 1], cos: [Math.cos, 1, 1], tan: [Math.tan, 1, 1], atan: [Math.atan, 1, 1], atan2: [Math.atan2, 2, 2],
    erf: [erf, 1, 1], normpdf: [normpdf, 1, 3], normcdf: [normcdf, 1, 3], norminv: [norminv, 1, 3],
    binom: [binom, 2, 2], logistic: [(x) => (x < -700 ? 0 : 1 / (1 + Math.exp(-x))), 1, 1],
    sign: [(x) => (x > 0) - (x < 0), 1, 1],
  };
  const CONSTANTS = { pi: Math.PI, e: Math.E, true: 1, false: 0 };

  function Parser(src) {
    this.src = src;
    this.toks = tokenize(src);
    this.i = 0;
    this.depth = 0;
  }
  Parser.prototype = {
    peek() { return this.toks[this.i]; },
    take() { return this.toks[this.i++]; },
    accept(...ops) {
      const [k, v] = this.peek();
      if (k === "op" && ops.includes(v)) { this.i++; return v; }
      return null;
    },
    expect(op) { if (!this.accept(op)) throw new ExprError(`expected '${op}' in '${this.src}'`); },
    open() {
      if (++this.depth > MAX_NESTING) throw new ExprError(`brackets nest more than ${MAX_NESTING} deep; write it more simply, as several outputs that build on each other`);
    },
    parse() {
      const n = this.ternary();
      if (this.peek()[0] !== "end") throw new ExprError(`unexpected '${this.peek()[1]}' in '${this.src}'`);
      return n;
    },
    ternary() {
      const c = this.or();
      if (this.accept("?")) { const a = this.ternary(); this.expect(":"); return ["?", c, a, this.ternary()]; }
      return c;
    },
    or() { let n = this.and(); while (this.accept("||")) n = ["||", n, this.and()]; return n; },
    and() { let n = this.cmp(); while (this.accept("&&")) n = ["&&", n, this.cmp()]; return n; },
    cmp() {
      const n = this.add();
      const op = this.accept("<", "<=", ">", ">=", "==", "!=");
      return op ? [op, n, this.add()] : n;
    },
    add() { let n = this.mul(), op; while ((op = this.accept("+", "-"))) n = [op, n, this.mul()]; return n; },
    mul() { let n = this.unary(), op; while ((op = this.accept("*", "/", "%"))) n = [op, n, this.unary()]; return n; },
    unary() { const op = this.accept("-", "+", "!"); return op ? ["u" + op, this.unary()] : this.power(); },
    power() { const b = this.atom(); return this.accept("^") ? ["^", b, this.unary()] : b; },
    atom() {
      const [k, v] = this.take();
      if (k === "num") return ["num", parseFloat(v)];
      if (k === "name") {
        if (this.accept("(")) {
          this.open();
          const args = [];
          if (!this.accept(")")) {
            args.push(this.ternary());
            while (this.accept(",")) args.push(this.ternary());
            this.expect(")");
          }
          this.depth--;
          const f = FUNCTIONS[v];
          if (!f) throw new ExprError(`unknown function '${v}'`);
          if (args.length < f[1] || args.length > f[2]) throw new ExprError(`${v}() takes ${f[1]}–${f[2]} arguments, got ${args.length}`);
          return ["call", v, args];
        }
        if (v in CONSTANTS) return ["num", CONSTANTS[v]];
        return ["name", v];
      }
      if (k === "op" && v === "(") { this.open(); const n = this.ternary(); this.expect(")"); this.depth--; return n; }
      throw new ExprError(`unexpected '${v || "end of expression"}' in '${this.src}'`);
    },
  };

  const cache = new Map();
  function parse(src) {
    if (typeof src === "number") return ["num", src];
    let n = cache.get(src);
    if (!n) { n = new Parser(src).parse(); if (cache.size < 5000) cache.set(src, n); }
    return n;
  }

  function names(src) {
    const out = new Set();
    (function walk(n) {
      if (n[0] === "name") out.add(n[1]);
      else if (n[0] === "call") n[2].forEach(walk);
      else if (n[0] !== "num") n.slice(1).forEach(walk);
    })(parse(src));
    return out;
  }

  const close = (a, b) => Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b));

  function ev(n, env) {
    switch (n[0]) {
      case "num": return n[1];
      case "name": {
        if (!(n[1] in env)) throw new ExprError(`unknown name '${n[1]}'`);
        return +env[n[1]];
      }
      case "call": return FUNCTIONS[n[1]][0](...n[2].map((a) => ev(a, env)));
      case "?": return ev(n[1], env) ? ev(n[2], env) : ev(n[3], env);
      case "u-": return -ev(n[1], env);
      case "u+": return ev(n[1], env);
      case "u!": return ev(n[1], env) ? 0 : 1;
      case "&&": return ev(n[1], env) && ev(n[2], env) ? 1 : 0;
      case "||": return ev(n[1], env) || ev(n[2], env) ? 1 : 0;
    }
    const a = ev(n[1], env), b = ev(n[2], env);
    switch (n[0]) {
      case "+": return a + b;
      case "-": return a - b;
      case "*": return a * b;
      case "/": return a / b;
      case "%": return a % b;
      case "^": return Math.pow(a, b);
      case "<": return a < b ? 1 : 0;
      case "<=": return a <= b ? 1 : 0;
      case ">": return a > b ? 1 : 0;
      case ">=": return a >= b ? 1 : 0;
      case "==": return close(a, b) ? 1 : 0;
      case "!=": return close(a, b) ? 0 : 1;
    }
    throw new ExprError("bad node " + n[0]);
  }

  function evaluate(src, env) { return ev(parse(src), env); }

  root.LemmaExpr = { ExprError, parse, evaluate, names, FUNCTIONS, CONSTANTS, MAX_NESTING, normcdf };
})(typeof window !== "undefined" ? window : globalThis);
