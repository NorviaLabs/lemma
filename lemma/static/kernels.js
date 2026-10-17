/* Seeded simulations — browser twin of lemma/kernels.py. Same draws, same order, same arithmetic.
   Each kernel returns { metrics, frames, ...extra } where frames drive the animation. */
(function (root) {
  "use strict";

  function Rng(seed) {
    let a = seed >>> 0;
    const r = function () {
      a |= 0;
      a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    r.int = (n) => Math.floor(r() * n);
    r.normal = () => {
      const u1 = 1 - r();
      const u2 = r();
      return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
    };
    return r;
  }

  const P = (d, lo, hi, int) => [d, lo, hi, !!int];
  const SPECS = {
    schelling: { visual: "agents", params: { size: P(20, 8, 40, 1), density: P(0.9, 0.3, 0.98), share_a: P(0.5, 0.05, 0.95), tolerance: P(0.3, 0, 1), steps: P(40, 1, 200, 1), seed: P(1, 0, 1e9, 1) } },
    sir: { visual: "agents", params: { size: P(30, 10, 60, 1), transmission: P(0.3, 0, 1), recovery: P(0.2, 0.01, 1), vaccinated: P(0, 0, 0.95), initial: P(3, 1, 50, 1), steps: P(100, 1, 400, 1), seed: P(1, 0, 1e9, 1) } },
    opinion: { visual: "agents", params: { agents: P(100, 10, 300, 1), confidence: P(0.2, 0.01, 1), convergence: P(0.5, 0.05, 0.5), rounds: P(40, 1, 200, 1), rule: P(0, 0, 1, 1), seed: P(1, 0, 1e9, 1) } },
    network: { visual: "network", params: { nodes: P(60, 10, 200, 1), degree: P(4, 2, 12, 1), rewire: P(0.1, 0, 1), rule: P(0, 0, 1, 1), threshold: P(0.3, 0, 1), transmission: P(0.3, 0, 1), seeds: P(3, 1, 50, 1), steps: P(30, 1, 200, 1), seed: P(1, 0, 1e9, 1) } },
    mean: { visual: "sampling", params: { mu: P(0, -1e6, 1e6), sd: P(1, 1e-9, 1e6), n: P(10, 1, 500, 1), samples: P(200, 10, 1000, 1), seed: P(1, 0, 1e9, 1) } },
    two_group: { visual: "sampling", params: { mu1: P(0, -1e6, 1e6), mu2: P(0.5, -1e6, 1e6), sd: P(1, 1e-9, 1e6), n: P(20, 2, 500, 1), alpha: P(0.05, 0.001, 0.5), samples: P(200, 10, 1000, 1), seed: P(1, 0, 1e9, 1) } },
    regression: { visual: "sampling", params: { r: P(0.5, -0.99, 0.99), mean: P(0, -1e6, 1e6), sd: P(1, 1e-9, 1e6), people: P(300, 20, 1000, 1), select: P(0.1, 0.01, 0.5), seed: P(1, 0, 1e9, 1) } },
  };

  function resolveParams(kernel, raw) {
    const spec = SPECS[kernel].params, out = {};
    for (const [name, [d, lo, hi, isInt]] of Object.entries(spec)) {
      let v = raw && name in raw ? Number(raw[name]) : d;
      if (!Number.isFinite(v)) v = d;
      v = Math.min(Math.max(v, lo), hi);
      if (isInt) v = Math.floor(v + 0.5);
      out[name] = v;
    }
    return out;
  }

  const mod = (a, n) => ((a % n) + n) % n;

  function schelling(p) {
    const rng = Rng(p.seed), n = p.size, cells = n * n;
    const grid = new Array(cells).fill(0);
    for (let i = 0; i < cells; i++) if (rng() < p.density) grid[i] = rng() < p.share_a ? 1 : 2;
    const neigh = (i) => {
      const r = Math.floor(i / n), c = i % n;
      let same = 0, occ = 0;
      for (let dr = -1; dr <= 1; dr++)
        for (let dc = -1; dc <= 1; dc++) {
          if (!dr && !dc) continue;
          const g = grid[mod(r + dr, n) * n + mod(c + dc, n)];
          if (g) { occ++; if (g === grid[i]) same++; }
        }
      return [same, occ];
    };
    const unhappy = (i) => { const [s, o] = neigh(i); return o > 0 && s / o < p.tolerance; };
    const frames = [grid.slice()];
    let rounds = 0;
    for (let step = 0; step < p.steps; step++) {
      const movers = [];
      for (let i = 0; i < cells; i++) if (grid[i] && unhappy(i)) movers.push(i);
      if (!movers.length) break;
      const empty = [];
      for (let i = 0; i < cells; i++) if (!grid[i]) empty.push(i);
      if (!empty.length) break;
      rounds++;
      for (const i of movers) {
        const k = rng.int(empty.length), j = empty[k];
        grid[j] = grid[i]; grid[i] = 0; empty[k] = i;
      }
      frames.push(grid.slice());
    }
    let sum = 0, cnt = 0, unh = 0, agents = 0;
    for (let i = 0; i < cells; i++) {
      if (!grid[i]) continue;
      agents++;
      const [s, o] = neigh(i);
      if (o) { sum += s / o; cnt++; if (s / o < p.tolerance) unh++; }
    }
    return { metrics: { segregation: cnt ? sum / cnt : 0, unhappy: agents ? unh / agents : 0, rounds }, frames, size: n, palette: ["empty", "a", "b"] };
  }

  function sir(p) {
    const rng = Rng(p.seed), n = p.size, cells = n * n;
    let st = new Array(cells).fill(0);
    for (let i = 0; i < cells; i++) if (rng() < p.vaccinated) st[i] = 3;
    let placed = 0, tries = 0;
    while (placed < p.initial && tries < cells * 4) {
      tries++;
      const i = rng.int(cells);
      if (st[i] === 0) { st[i] = 1; placed++; }
    }
    let infected = placed, peak = infected / cells, rounds = 0;
    const q = 1 - p.transmission;
    const frames = [st.slice()], curve = [infected / cells];
    for (let step = 0; step < p.steps; step++) {
      if (infected === 0) break;
      rounds++;
      const nxt = st.slice();
      for (let i = 0; i < cells; i++) {
        const s = st[i];
        if (s === 0) {
          const r = Math.floor(i / n), c = i % n;
          let k = 0;
          for (const j of [mod(r - 1, n) * n + c, mod(r + 1, n) * n + c, r * n + mod(c - 1, n), r * n + mod(c + 1, n)]) if (st[j] === 1) k++;
          if (k) {
            let stay = 1;
            for (let t = 0; t < k; t++) stay *= q;
            if (rng() < 1 - stay) nxt[i] = 1;
          }
        } else if (s === 1) {
          if (rng() < p.recovery) nxt[i] = 2;
        }
      }
      st = nxt;
      infected = 0;
      for (const s of st) if (s === 1) infected++;
      peak = Math.max(peak, infected / cells);
      frames.push(st.slice());
      curve.push(infected / cells);
    }
    let ever = 0;
    for (const s of st) if (s === 1 || s === 2) ever++;
    return { metrics: { peak_infected: peak, final_infected: ever / cells, rounds }, frames, curve, size: n, palette: ["susceptible", "infected", "recovered", "vaccinated"] };
  }

  function clusters(xs) {
    const s = xs.slice().sort((a, b) => a - b);
    let c = 1;
    for (let i = 1; i < s.length; i++) if (s[i] - s[i - 1] > 0.1) c++;
    return [c, s[s.length - 1] - s[0]];
  }

  // One Hegselmann–Krause round: each agent moves to the mean of all opinions within eps of its own.
  function everyoneAverages(x, eps) {
    const order = x.map((_, i) => i).sort((a, b) => x[a] - x[b] || a - b);
    const s = order.map((i) => x[i]);
    const pre = [0];
    for (const v of s) pre.push(pre[pre.length - 1] + v);
    const out = x.slice();
    let lo = 0, hi = 0;
    for (let k = 0; k < s.length; k++) {
      const v = s[k];
      while (s[lo] < v - eps) lo++;
      while (hi + 1 < s.length && s[hi + 1] <= v + eps) hi++;
      out[order[k]] = (pre[hi + 1] - pre[lo]) / (hi - lo + 1);
    }
    return out;
  }

  function opinion(p) {
    const rng = Rng(p.seed), n = p.agents;
    let x = [];
    for (let i = 0; i < n; i++) x.push(rng());
    const frames = [x.slice()];
    if (p.rule === 1) {
      for (let round = 0; round < p.rounds; round++) {
        x = everyoneAverages(x, p.confidence);
        frames.push(x.slice());
      }
      const [c, spread] = clusters(x);
      return { metrics: { clusters: c, spread }, frames };
    }
    for (let round = 0; round < p.rounds; round++) {
      for (let t = 0; t < n; t++) {
        const i = rng.int(n), j = rng.int(n);
        if (i !== j && Math.abs(x[i] - x[j]) < p.confidence) {
          const xi = x[i], xj = x[j];
          x[i] = xi + p.convergence * (xj - xi);
          x[j] = xj + p.convergence * (xi - xj);
        }
      }
      frames.push(x.slice());
    }
    const [c, spread] = clusters(x);
    return { metrics: { clusters: c, spread }, frames };
  }

  function networkGraph(p) {
    const rng = Rng(p.seed), n = p.nodes, half = Math.max(1, Math.floor(p.degree / 2));
    const adj = Array.from({ length: n }, () => new Set());
    for (let i = 0; i < n; i++)
      for (let j = 1; j <= half; j++) {
        let t = (i + j) % n;
        if (rng() < p.rewire) {
          for (let k = 0; k < 10; k++) {
            t = rng.int(n);
            if (t !== i && !adj[i].has(t)) break;
          }
        }
        if (t !== i) { adj[i].add(t); adj[t].add(i); }
      }
    return [adj.map((s) => [...s].sort((a, b) => a - b)), rng];
  }

  function network(p) {
    const [adj, rng] = networkGraph(p), n = p.nodes;
    const on = new Array(n).fill(false);
    for (let i = 0; i < Math.min(p.seeds, n); i++) on[i] = true;
    let fresh = [];
    for (let i = 0; i < n; i++) if (on[i]) fresh.push(i);
    const frames = [on.slice()];
    let rounds = 0;
    for (let step = 0; step < p.steps; step++) {
      const nw = [];
      if (p.rule === 0) {
        for (let i = 0; i < n; i++) {
          if (!on[i] && adj[i].length) {
            let k = 0;
            for (const j of adj[i]) if (on[j]) k++;
            if (k / adj[i].length >= p.threshold && k > 0) nw.push(i);
          }
        }
      } else {
        for (const i of fresh) for (const j of adj[i]) if (!on[j] && !nw.includes(j) && rng() < p.transmission) nw.push(j);
      }
      if (!nw.length) break;
      rounds++;
      for (const i of nw) on[i] = true;
      fresh = nw;
      frames.push(on.slice());
    }
    let a = 0;
    for (const v of on) if (v) a++;
    return { metrics: { adopted: a / n, rounds }, frames, adj };
  }

  function mean(p) {
    const rng = Rng(p.seed), means = [];
    for (let s = 0; s < p.samples; s++) {
      let t = 0;
      for (let i = 0; i < p.n; i++) t += p.mu + p.sd * rng.normal();
      means.push(t / p.n);
    }
    let m = 0;
    for (const x of means) m += x;
    m /= means.length;
    let v = 0;
    for (const x of means) v += (x - m) * (x - m);
    v /= means.length - 1;
    return { metrics: { mean_of_means: m, sd_of_means: Math.sqrt(v) }, values: means, kind: "mean" };
  }

  function twoGroup(p) {
    const rng = Rng(p.seed), n = p.n, se = p.sd * Math.sqrt(2 / n);
    const pvals = [], diffs = [], sigDiffs = [];
    let sig = 0;
    for (let s = 0; s < p.samples; s++) {
      let a = 0, b = 0;
      for (let i = 0; i < n; i++) a += p.mu1 + p.sd * rng.normal();
      for (let i = 0; i < n; i++) b += p.mu2 + p.sd * rng.normal();
      const diff = b / n - a / n, z = diff / se;
      const pv = 2 * (1 - root.LemmaExpr.normcdf(Math.abs(z)));
      pvals.push(pv); diffs.push(diff);
      if (pv < p.alpha) { sig++; sigDiffs.push(diff); }
    }
    const avg = (xs) => { let t = 0; for (const x of xs) t += x; return t / xs.length; };
    return {
      metrics: { share_significant: sig / p.samples, mean_diff: avg(diffs), mean_sig_diff: sigDiffs.length ? avg(sigDiffs) : 0 },
      values: pvals, diffs, alpha: p.alpha, kind: "two_group",
    };
  }

  function regression(p) {
    const rng = Rng(p.seed), r = p.r, k = Math.sqrt(1 - r * r), pairs = [];
    for (let i = 0; i < p.people; i++) {
      const z1 = rng.normal(), z2 = rng.normal();
      pairs.push([z1, r * z1 + k * z2]);
    }
    const order = pairs.map((_, i) => i).sort((i, j) => pairs[j][0] - pairs[i][0] || i - j);
    const m = Math.max(1, Math.floor(p.people * p.select + 0.5));
    const chosen = order.slice(0, m);
    let f = 0, s = 0;
    for (const i of chosen) f += pairs[i][0];
    for (const i of chosen) s += pairs[i][1];
    f /= m; s /= m;
    return { metrics: { first_selected: f, second_selected: s, retained: f ? s / f : 0 }, pairs, chosen: new Set(chosen), kind: "regression", mean: p.mean, sd: p.sd };
  }

  const RUN = { schelling, sir, opinion, network, mean, two_group: twoGroup, regression };

  const memo = new Map();
  function run(kernel, raw) {
    const p = resolveParams(kernel, raw);
    const key = kernel + JSON.stringify(p);
    if (memo.has(key)) return memo.get(key);
    const out = RUN[kernel](p);
    out.params = p;
    out.kernel = kernel;
    if (memo.size > 60) memo.delete(memo.keys().next().value);
    memo.set(key, out);
    return out;
  }

  root.LemmaKernels = { Rng, SPECS, resolveParams, run, networkGraph };
})(typeof window !== "undefined" ? window : globalThis);
