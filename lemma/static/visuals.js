/* Live models: evaluate a model and draw its visual. Mirrors lemma/lesson.py `compute`. */
(function (root) {
  "use strict";
  const E = root.LemmaExpr, K = root.LemmaKernels;
  const SVGNS = "http://www.w3.org/2000/svg";
  const reduceMotion = () => !!(root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches);

  /* ------------------------------------------------------------ evaluation */

  function defaults(model) {
    const d = {};
    for (const c of model.controls || []) d[c.id] = Number(c.default ?? 0);
    return d;
  }

  function evalNum(src, env) {
    if (src === undefined || src === null) return NaN;
    return typeof src === "number" ? src : E.evaluate(String(src), env);
  }

  function compute(model, values, opts = {}) {
    const env = Object.assign(defaults(model), values || {});
    const vis = model.visual || {};
    const kernel = vis.kernel && K.SPECS[vis.kernel] ? vis.kernel : null;
    let sim = null;
    const runSim = () => {
      const params = {};
      for (const [k, v] of Object.entries(vis.params || {})) params[k] = evalNum(v, env);
      sim = K.run(kernel, params);
      for (const [m, v] of Object.entries(sim.metrics)) env["sim_" + m] = v;
    };
    for (const o of model.outputs || []) {
      if (kernel && !sim && [...E.names(o.expr)].some((n) => n.startsWith("sim_"))) runSim();
      env[o.id] = E.evaluate(String(o.expr), env);
    }
    if (kernel && !sim && !opts.skipSim) runSim();
    return { env, sim };
  }

  function holds(model, when, values) {
    try { return !!E.evaluate(when, compute(model, values).env); } catch (e) { return false; }
  }

  /* ------------------------------------------------------------ formatting */

  function fmt(v, decimals = 2, scale = 1, unit = "") {
    if (!Number.isFinite(v)) return "—";
    const x = v * (scale ?? 1);
    let s = x.toFixed(decimals ?? 2);
    if (/^-0(\.0*)?$/.test(s)) s = s.slice(1);
    const u = unit && /^[A-Za-z(]/.test(unit) ? " " + unit : unit || "";  // "2 sd", but "40%" and "68 in" as given
    return s.replace("-", "−") + u;
  }

  function niceTicks(lo, hi, n = 5) {
    if (!(hi > lo)) return [lo];
    const span = hi - lo, raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || 10 * mag;
    const out = [];
    for (let t = Math.ceil(lo / step) * step; t <= hi + step * 1e-9; t += step) out.push(+t.toFixed(10));
    return out;
  }
  const tickLabel = (t) => (Math.abs(t) >= 1e4 || (Math.abs(t) < 1e-3 && t !== 0) ? t.toExponential(1) : String(+t.toFixed(4))).replace("-", "−");

  /* ------------------------------------------------------------ svg helpers */

  function el(tag, attrs = {}, parent) {
    const n = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null) continue;
      if (k === "text") n.textContent = v;
      else if (k === "style") n.setAttribute("style", v);
      else n.setAttribute(k, v);
    }
    if (parent) parent.appendChild(n);
    return n;
  }
  const col = (i) => `var(--model-${((i ?? 0) % 8 + 8) % 8})`;
  function svgRoot(container, w, h, label) {
    const s = el("svg", { viewBox: `0 0 ${w} ${h}`, class: "viz", role: "img", "aria-label": label || "Model visual" });
    container.replaceChildren(s);
    return s;
  }
  function cssColor(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
  }

  function axes(svg, box, xs, ys, xlabel, ylabel) {
    const g = el("g", { class: "axes" }, svg);
    for (const t of ys.ticks) {
      const y = ys(t);
      el("line", { x1: box.x, x2: box.x + box.w, y1: y, y2: y, class: "grid" }, g);
      el("text", { x: box.x - 8, y: y + 4, "text-anchor": "end", class: "tick", text: tickLabel(t) }, g);
    }
    for (const t of xs.ticks) {
      const x = xs(t);
      el("line", { x1: x, x2: x, y1: box.y, y2: box.y + box.h, class: "grid" }, g);
      el("text", { x, y: box.y + box.h + 18, "text-anchor": "middle", class: "tick", text: tickLabel(t) }, g);
    }
    el("rect", { x: box.x, y: box.y, width: box.w, height: box.h, class: "frame" }, g);
    if (xlabel) el("text", { x: box.x + box.w / 2, y: box.y + box.h + 40, "text-anchor": "middle", class: "axis-label", text: xlabel }, g);
    if (ylabel) el("text", { x: 16, y: box.y + box.h / 2, "text-anchor": "middle", class: "axis-label", transform: `rotate(-90 16 ${box.y + box.h / 2})`, text: ylabel }, g);
  }
  function scale(lo, hi, a, b) {
    const f = (v) => a + ((v - lo) / (hi - lo)) * (b - a);
    f.ticks = niceTicks(lo, hi, 6);
    return f;
  }
  const noAxis = () => Object.assign(() => 0, { ticks: [] });
  let clipSeq = 0;

  /* ------------------------------------------------------------ renderers */

  const R = {};

  R.curves = function (ctx) {
    const { vis, env, svgIn } = ctx;
    const W = ctx.W, H = 380, box = { x: 64, y: 16, w: W - 84, h: H - 76 };
    const svg = svgIn(W, H);
    const x0 = evalNum(vis.x.min, env), x1 = evalNum(vis.x.max, env);
    const y0 = evalNum(vis.y.min, env), y1 = evalNum(vis.y.max, env);
    const xs = scale(x0, x1, box.x, box.x + box.w), ys = scale(y0, y1, box.y + box.h, box.y);
    axes(svg, box, xs, ys, vis.x.label, vis.y.label);
    const clipId = "clip" + ++clipSeq;
    el("rect", { x: box.x, y: box.y, width: box.w, height: box.h }, el("clipPath", { id: clipId }, el("defs", {}, svg)));
    const plot = el("g", { "clip-path": `url(#${clipId})` }, svg);
    const series = vis.series || [];
    const sample = (s, a, b, n = 160) => {
      const pts = [];
      for (let i = 0; i <= n; i++) {
        const x = a + ((b - a) * i) / n;
        let y;
        try { y = E.evaluate(String(s.expr), Object.assign({}, env, { x })); } catch (e) { y = NaN; }
        pts.push([x, y]);
      }
      return pts;
    };
    for (const f of vis.fills || []) {
      const s = series[f.series];
      if (!s) continue;
      let a = Math.max(evalNum(f.from, env), x0), b = Math.min(evalNum(f.to, env), x1);
      if (!(b > a)) continue;
      const pts = sample(s, a, b, 100).filter((p) => Number.isFinite(p[1]));
      if (!pts.length) continue;
      const base = ys(y0 <= 0 && 0 <= y1 ? 0 : y0);
      let d = `M${xs(pts[0][0])},${base}`;
      for (const [x, y] of pts) d += `L${xs(x)},${ys(y)}`;
      d += `L${xs(pts[pts.length - 1][0])},${base}Z`;
      el("path", { d, class: "fill", style: `fill:${col(f.color ?? s.color)}` }, plot);
    }
    for (const h of vis.hlines || []) {
      const y = ys(evalNum(h.y, env));
      el("line", { x1: box.x, x2: box.x + box.w, y1: y, y2: y, class: "refline" }, plot);
      if (h.label) el("text", { x: box.x + box.w - 6, y: y - 6, "text-anchor": "end", class: "ref-label", text: h.label }, plot);
    }
    series.forEach((s, i) => {
      const pts = sample(s, x0, x1);
      let d = "", pen = false;
      for (const [x, y] of pts) {
        if (!Number.isFinite(y)) { pen = false; continue; }
        const Y = Math.max(-1e4, Math.min(1e4, ys(y)));
        d += (pen ? "L" : "M") + xs(x).toFixed(2) + "," + Y.toFixed(2);
        pen = true;
      }
      el("path", { d, class: "series" + (s.dashed ? " dashed" : ""), style: `stroke:${col(s.color ?? i)}`, "data-series": i }, plot);
    });
    (vis.markers || []).forEach((m, i) => {
      const x = xs(evalNum(m.x, env));
      el("line", { x1: x, x2: x, y1: box.y, y2: box.y + box.h, class: "marker", style: `stroke:${col(m.color ?? 3)}` }, plot);
      // Stagger labels so markers that sit close together stay readable; flip to the left near the right edge.
      const right = x > box.x + box.w * 0.7;
      if (m.label) el("text", { x: right ? x - 5 : x + 5, y: box.y + 14 + (i % 3) * 15, "text-anchor": right ? "end" : "start", class: "marker-label", style: `fill:${col(m.color ?? 3)}`, text: m.label }, plot);
    });
    for (const p of vis.points || []) {
      const x = xs(evalNum(p.x, env)), y = ys(evalNum(p.y, env));
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      el("circle", { cx: x, cy: y, r: 9, class: "point", style: `fill:${col(p.color ?? 0)}` }, plot);
      if (p.label) el("text", { x: x + 9, y: y - 9, class: "point-label", text: p.label }, plot);
    }
    ctx.legend(series.map((s, i) => ({ label: s.label, color: s.color ?? i, dashed: s.dashed })).concat((vis.fills || []).filter((f) => f.label).map((f) => ({ label: f.label, color: f.color ?? series[f.series]?.color, area: true }))));
  };

  R.bars = function (ctx) {
    const { vis, env, svgIn } = ctx;
    const bars = vis.bars || [];
    const W = ctx.W, H = 340, box = { x: 64, y: 20, w: W - 84, h: H - 80 };
    const svg = svgIn(W, H);
    const vals = bars.map((b) => evalNum(b.value, env));
    const lo = vis.min !== undefined ? evalNum(vis.min, env) : Math.min(0, ...vals);
    const hi = vis.max !== undefined ? evalNum(vis.max, env) : Math.max(...vals) * 1.15 || 1;
    const ys = scale(lo, hi, box.y + box.h, box.y);
    axes(svg, box, noAxis(), ys, null, vis.unit ? `Value (${vis.unit.trim()})` : null);
    const slot = box.w / Math.max(1, bars.length), bw = Math.min(110, slot * 0.6);
    bars.forEach((b, i) => {
      const v = vals[i], cx = box.x + slot * (i + 0.5);
      const vy = ys(Math.max(lo, Math.min(hi, v))), base = ys(Math.max(lo, Math.min(hi, 0 >= lo && 0 <= hi ? 0 : lo)));
      el("rect", { x: cx - bw / 2, y: Math.min(vy, base), width: bw, height: Math.abs(base - vy), class: "bar", style: `fill:${col(b.color ?? i)}` }, svg);
      el("text", { x: cx, y: Math.min(vy, base) - 8, "text-anchor": "middle", class: "bar-value", text: fmt(v, vis.decimals ?? 1, 1, vis.unit || "") }, svg);
      el("text", { x: cx, y: box.y + box.h + 22, "text-anchor": "middle", class: "bar-label", text: b.label }, svg);
    });
  };

  R.table = function (ctx) {
    const { vis, env, container } = ctx;
    const t = document.createElement("table");
    t.className = "viz-table";
    const head = t.createTHead().insertRow();
    head.appendChild(document.createElement("th"));
    for (const c of vis.columns || []) { const th = document.createElement("th"); th.scope = "col"; th.textContent = c; head.appendChild(th); }
    const body = t.createTBody();
    const cells = [];
    for (const row of vis.rows || []) {
      const tr = body.insertRow();
      const th = document.createElement("th"); th.scope = "row"; th.textContent = row.label; tr.appendChild(th);
      for (const cell of row.cells || []) {
        const spec = typeof cell === "object" && cell !== null ? cell : { value: cell };
        const v = evalNum(spec.value, env), hl = spec.highlight !== undefined ? !!evalNum(spec.highlight, env) : false;
        const td = tr.insertCell();
        td.textContent = fmt(v, vis.decimals ?? 1, 1, vis.unit || "") + (hl ? " ★" : "");
        if (hl) td.classList.add("hl");
        cells.push([td, v]);
      }
    }
    const kind = vis.scale || "sequential";
    if (kind !== "none" && cells.length) {
      const finite = cells.map((c) => c[1]).filter(Number.isFinite);
      const lo = vis.scale_min !== undefined ? evalNum(vis.scale_min, env) : Math.min(...finite);
      const hi = vis.scale_max !== undefined ? evalNum(vis.scale_max, env) : Math.max(...finite);
      for (const [td, v] of cells) {
        if (!Number.isFinite(v) || !(hi > lo)) continue;
        const f = Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
        if (kind === "diverging") {
          const d = f * 2 - 1;
          td.style.background = `color-mix(in srgb, ${d < 0 ? "var(--model-1)" : "var(--model-0)"} ${Math.round(Math.abs(d) * 55)}%, var(--surface))`;
        } else {
          td.style.background = `color-mix(in srgb, var(--model-0) ${Math.round(f * 60)}%, var(--surface))`;
        }
      }
    }
    container.replaceChildren(h_scroll(t));
  };
  function h_scroll(node) { const d = document.createElement("div"); d.className = "table-scroll"; d.append(node); return d; }

  /* simulations animate their frames */
  function frameIndex(ctx, total) {
    if (total <= 1 || ctx.transient) return total - 1;
    return ctx.anim(total);
  }

  R.agents = function (ctx) {
    const { sim, container } = ctx;
    if (!sim) { container.textContent = "…"; return; }
    if (sim.kernel === "opinion") return opinionPlot(ctx);
    const n = sim.size;
    let cv = container.querySelector("canvas");
    if (!cv) { cv = document.createElement("canvas"); cv.className = "viz-canvas"; cv.width = 480; cv.height = 480; cv.setAttribute("role", "img"); container.replaceChildren(cv); }
    const names = sim.kernel === "schelling" ? ["--stage-2", "--model-0", "--model-3"] : ["--model-7", "--model-1", "--model-0", "--model-2"];
    const colors = names.map(cssColor);
    const labels = sim.kernel === "schelling" ? ["Empty", "Group A", "Group B"] : ["Susceptible", "Infected", "Recovered", "Vaccinated"];
    const draw = (fi) => {
      const g = cv.getContext("2d"), frame = sim.frames[fi], s = cv.width / n;
      g.clearRect(0, 0, cv.width, cv.height);
      for (let i = 0; i < frame.length; i++) {
        const r = Math.floor(i / n), c = i % n, v = frame[i];
        g.fillStyle = colors[v];
        if (sim.kernel === "schelling" && v === 2) {
          // squares for B, circles for A: shape as well as colour
          g.fillRect(c * s + 1, r * s + 1, s - 2, s - 2);
        } else if (sim.kernel === "schelling" && v === 1) {
          g.beginPath(); g.arc(c * s + s / 2, r * s + s / 2, s / 2 - 1, 0, 2 * Math.PI); g.fill();
        } else {
          g.fillRect(c * s + 0.5, r * s + 0.5, s - 1, s - 1);
          if (v === 1 && sim.kernel === "sir") { g.fillStyle = cssColor("--stage"); g.fillRect(c * s + s / 2 - 1, r * s + s / 2 - 1, 2, 2); }
        }
      }
      cv.setAttribute("aria-label", `${labels.join(", ")} grid, round ${fi} of ${sim.frames.length - 1}`);
      ctx.status(`Round ${fi} of ${sim.frames.length - 1}`);
    };
    ctx.frames(sim.frames.length, draw);
    ctx.legend(labels.map((l, i) => ({ label: l, swatch: names[i], shape: sim.kernel === "schelling" ? ["none", "circle", "square"][i] : "square" })).filter((x) => x.shape !== "none"));
  };

  function opinionPlot(ctx) {
    const { sim, svgIn } = ctx;
    const W = ctx.W, H = 360, box = { x: 56, y: 16, w: W - 76, h: H - 70 };
    const T = sim.frames.length - 1;
    const draw = (fi) => {
      const svg = svgIn(W, H);
      const xs = scale(0, Math.max(1, T), box.x, box.x + box.w), ys = scale(0, 1, box.y + box.h, box.y);
      axes(svg, box, xs, ys, "Round", "Opinion");
      const n = sim.frames[0].length;
      for (let a = 0; a < n; a++) {
        let d = "";
        for (let t = 0; t <= fi; t++) d += (t ? "L" : "M") + xs(t).toFixed(1) + "," + ys(sim.frames[t][a]).toFixed(1);
        el("path", { d, class: "trace", style: `stroke:${col(sim.frames[0][a] < 0.5 ? 0 : 3)}` }, svg);
      }
      ctx.status(`Round ${fi} of ${T}`);
    };
    ctx.frames(sim.frames.length, draw);
  }

  R.network = function (ctx) {
    const { sim, svgIn } = ctx;
    if (!sim) return;
    const W = 480, H = 480, cx = W / 2, cy = H / 2, rad = 200, n = sim.adj.length;
    const pos = sim.adj.map((_, i) => [cx + rad * Math.cos((2 * Math.PI * i) / n - Math.PI / 2), cy + rad * Math.sin((2 * Math.PI * i) / n - Math.PI / 2)]);
    const draw = (fi) => {
      const svg = svgIn(W, H), on = sim.frames[fi];
      const g = el("g", {}, svg);
      sim.adj.forEach((nb, i) => nb.forEach((j) => {
        if (j > i) el("line", { x1: pos[i][0], y1: pos[i][1], x2: pos[j][0], y2: pos[j][1], class: "edge" + (on[i] && on[j] ? " lit" : "") }, g);
      }));
      pos.forEach(([x, y], i) => el("circle", { cx: x, cy: y, r: n > 120 ? 4 : 7, class: "node" + (on[i] ? " on" : "") }, g));
      ctx.status(`Round ${fi} of ${sim.frames.length - 1}`);
    };
    ctx.frames(sim.frames.length, draw);
    ctx.legend([{ label: "Adopted", swatch: "--model-1", shape: "circle" }, { label: "Not yet", swatch: "--stage", shape: "ring" }]);
  };

  R.causal = function (ctx) {
    const { vis, env, svgIn } = ctx;
    const W = 640, H = 400, svg = svgIn(W, H);
    const P = (n) => [30 + (n.x / 100) * (W - 60), 30 + (n.y / 100) * (H - 60)];
    const nodes = new Map((vis.nodes || []).map((n) => [n.id, n]));
    const defs = el("defs", {}, svg);
    for (const [k, c] of [["pos", "var(--model-0)"], ["neg", "var(--model-1)"], ["zero", "var(--model-7)"]]) {
      const m = el("marker", { id: "arr-" + k + clipSeq, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto-start-reverse" }, defs);
      el("path", { d: "M0,0L10,5L0,10z", style: `fill:${c}` }, m);
    }
    const id = clipSeq;
    for (const e of vis.edges || []) {
      const a = nodes.get(e.from), b = nodes.get(e.to);
      if (!a || !b) continue;
      const s = evalNum(e.strength, env);
      const [x1, y1] = P(a), [x2, y2] = P(b);
      const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
      const off = 46;
      const sx = x1 + (dx / len) * off, sy = y1 + (dy / len) * 26, ex = x2 - (dx / len) * off, ey = y2 - (dy / len) * 26;
      const kind = Math.abs(s) < 1e-9 ? "zero" : s > 0 ? "pos" : "neg";
      el("line", { x1: sx, y1: sy, x2: ex, y2: ey, class: "cedge " + kind, "stroke-width": 1.5 + Math.min(1, Math.abs(s)) * 7, "marker-end": `url(#arr-${kind}${id})` }, svg);
      el("text", { x: (sx + ex) / 2 + (dy / len) * 14, y: (sy + ey) / 2 - (dx / len) * 14 + 4, "text-anchor": "middle", class: "edge-label", text: `${e.label ? e.label + " = " : ""}${fmt(s, 2)}` }, svg);
    }
    for (const n of vis.nodes || []) {
      const [x, y] = P(n);
      el("rect", { x: x - 60, y: y - 24, width: 120, height: 48, rx: 10, class: "cnode" }, svg);
      el("text", { x, y: n.value !== undefined ? y - 3 : y + 5, "text-anchor": "middle", class: "cnode-label", text: n.label }, svg);
      if (n.value !== undefined) el("text", { x, y: y + 15, "text-anchor": "middle", class: "cnode-value", text: fmt(evalNum(n.value, env), 2) }, svg);
    }
    ctx.legend([{ label: "Positive effect", swatch: "--model-0", shape: "line" }, { label: "Negative effect (dashed)", swatch: "--model-1", shape: "dash" }]);
  };

  R.sampling = function (ctx) {
    const { sim, svgIn } = ctx;
    if (!sim) return;
    const W = ctx.W, H = 380, box = { x: 60, y: 16, w: W - 80, h: H - 74 };
    if (sim.kind === "regression") {
      const pts = sim.pairs, lim = 3.5;
      const draw = (fi) => {
        const svg = svgIn(W, H);
        const xs = scale(-lim, lim, box.x, box.x + box.w), ys = scale(-lim, lim, box.y + box.h, box.y);
        axes(svg, box, xs, ys, "First measurement (sd from the mean)", "Second measurement (sd)");
        el("line", { x1: xs(-lim), y1: ys(-lim), x2: xs(lim), y2: ys(lim), class: "refline" }, svg);
        const shown = Math.ceil((pts.length * (fi + 1)) / 30);
        for (let i = 0; i < shown; i++) {
          const [a, b] = pts[i];
          if (Math.abs(a) > lim || Math.abs(b) > lim) continue;
          el("circle", { cx: xs(a), cy: ys(b), r: sim.chosen.has(i) ? 3.6 : 2.2, class: sim.chosen.has(i) ? "dot sel" : "dot" }, svg);
        }
        if (fi === 29) {
          const m = sim.metrics;
          el("line", { x1: xs(m.first_selected), y1: ys(-lim), x2: xs(m.first_selected), y2: ys(lim), class: "marker", style: "stroke:var(--model-1)" }, svg);
          el("line", { x1: xs(-lim), y1: ys(m.second_selected), x2: xs(lim), y2: ys(m.second_selected), class: "marker", style: "stroke:var(--model-1)" }, svg);
          el("circle", { cx: xs(m.first_selected), cy: ys(m.second_selected), r: 9, class: "point", style: "fill:var(--model-1)" }, svg);
          const nearRight = xs(m.first_selected) > box.x + box.w * 0.6;
          el("text", { x: xs(m.first_selected) + (nearRight ? -14 : 14), y: ys(m.second_selected) + 26, "text-anchor": nearRight ? "end" : "start", class: "point-label", text: "Selected group's average" }, svg);
        }
      };
      ctx.frames(30, draw);
      ctx.legend([{ label: "Person", swatch: "--model-7", shape: "circle" }, { label: "Selected (top on 1st)", swatch: "--model-1", shape: "circle" }, { label: "Line: 2nd = 1st", swatch: "--mute", shape: "dash" }]);
      return;
    }
    const vals = sim.values;
    let lo, hi, xlabel, threshold = null;
    if (sim.kind === "two_group") { lo = 0; hi = 1; xlabel = "p-value of each simulated study"; threshold = sim.alpha; }
    else {
      const p = sim.params, se = p.sd / Math.sqrt(p.n);
      lo = p.mu - 4 * Math.max(se, p.sd / Math.sqrt(500)); hi = p.mu + 4 * Math.max(se, p.sd / Math.sqrt(500));
      lo = Math.min(lo, Math.min(...vals)); hi = Math.max(hi, Math.max(...vals));
      xlabel = "Mean of each sample";
    }
    const bins = 40, bw = (hi - lo) / bins;
    const draw = (fi) => {
      const svg = svgIn(W, H);
      const xs = scale(lo, hi, box.x, box.x + box.w);
      const shown = Math.ceil((vals.length * (fi + 1)) / 30);
      const counts = new Array(bins).fill(0);
      const maxCount = Math.max(8, Math.ceil(vals.length / 6));
      const r = Math.max(1.5, Math.min(5, box.h / maxCount / 2));
      axes(svg, box, xs, noAxis(), xlabel, "Studies");
      for (let i = 0; i < shown; i++) {
        const v = vals[i];
        const b = Math.max(0, Math.min(bins - 1, Math.floor((v - lo) / bw)));
        const k = counts[b]++;
        const y = box.y + box.h - r - k * r * 2;
        if (y < box.y) continue;
        const sig = threshold !== null && v < threshold;
        el("circle", { cx: xs(lo + (b + 0.5) * bw), cy: y, r: r * 0.9, class: "dot" + (sig ? " sel" : "") }, svg);
      }
      if (threshold !== null) {
        const x = xs(threshold);
        el("line", { x1: x, x2: x, y1: box.y, y2: box.y + box.h, class: "marker", style: "stroke:var(--model-1)" }, svg);
        el("text", { x: x + 6, y: box.y + 14, class: "marker-label", style: "fill:var(--model-1)", text: `α = ${threshold}` }, svg);
      } else {
        const x = xs(sim.params.mu);
        el("line", { x1: x, x2: x, y1: box.y, y2: box.y + box.h, class: "refline" }, svg);
        el("text", { x: x + 6, y: box.y + 14, class: "ref-label", text: "Population mean" }, svg);
      }
      ctx.status(`${shown} of ${vals.length} samples`);
    };
    ctx.frames(30, draw);
    ctx.legend(threshold !== null ? [{ label: "Significant (p < α)", swatch: "--model-1", shape: "circle" }, { label: "Not significant", swatch: "--model-7", shape: "circle" }] : [{ label: "One sample's mean", swatch: "--model-7", shape: "circle" }]);
  };

  R.geometry = function (ctx) {
    const { vis, env, svgIn } = ctx;
    const x0 = evalNum(vis.xmin, env), x1 = evalNum(vis.xmax, env), y0 = evalNum(vis.ymin, env), y1 = evalNum(vis.ymax, env);
    const W = 520, H = Math.max(260, Math.min(560, (W * (y1 - y0)) / (x1 - x0))), box = { x: 40, y: 12, w: W - 52, h: H - 44 };
    const svg = svgIn(W, H);
    const xs = scale(x0, x1, box.x, box.x + box.w), ys = scale(y0, y1, box.y + box.h, box.y);
    axes(svg, box, xs, ys);
    if (x0 < 0 && x1 > 0) el("line", { x1: xs(0), x2: xs(0), y1: box.y, y2: box.y + box.h, class: "axis0" }, svg);
    if (y0 < 0 && y1 > 0) el("line", { x1: box.x, x2: box.x + box.w, y1: ys(0), y2: ys(0), class: "axis0" }, svg);
    const defs = el("defs", {}, svg), mid = ++clipSeq;
    for (let i = 0; i < 8; i++) {
      const m = el("marker", { id: `g${mid}-${i}`, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, defs);
      el("path", { d: "M0,0L10,5L0,10z", style: `fill:${col(i)}` }, m);
    }
    for (const p of vis.polygons || []) {
      const pts = (p.points || []).map(([a, b]) => `${xs(evalNum(a, env))},${ys(evalNum(b, env))}`).join(" ");
      el("polygon", { points: pts, class: "poly", style: `fill:${col(p.color ?? 2)};stroke:${col(p.color ?? 2)}` }, svg);
    }
    for (const c of vis.circles || []) {
      const r = Math.abs(xs(evalNum(c.r, env)) - xs(0));
      el("circle", { cx: xs(evalNum(c.x, env)), cy: ys(evalNum(c.y, env)), r, class: "gcircle", style: `stroke:${col(c.color ?? 4)}` }, svg);
    }
    for (const s of vis.segments || []) {
      el("line", { x1: xs(evalNum(s.x1, env)), y1: ys(evalNum(s.y1, env)), x2: xs(evalNum(s.x2, env)), y2: ys(evalNum(s.y2, env)), class: "segment", style: `stroke:${col(s.color ?? 7)}` }, svg);
    }
    (vis.vectors || []).forEach((v, i) => {
      const c = v.color ?? i;
      const fx = evalNum(v.from_x ?? 0, env), fy = evalNum(v.from_y ?? 0, env);
      const tx = fx + evalNum(v.x, env), ty = fy + evalNum(v.y, env);
      el("line", { x1: xs(fx), y1: ys(fy), x2: xs(tx), y2: ys(ty), class: "vector", style: `stroke:${col(c)}`, "marker-end": `url(#g${mid}-${((c % 8) + 8) % 8})` }, svg);
      if (v.label) el("text", { x: xs(tx) + 8, y: ys(ty) - 8, class: "point-label", style: `fill:${col(c)}`, text: v.label }, svg);
    });
    for (const p of vis.points || []) {
      el("circle", { cx: xs(evalNum(p.x, env)), cy: ys(evalNum(p.y, env)), r: 5, class: "point", style: `fill:${col(p.color ?? 0)}` }, svg);
      if (p.label) el("text", { x: xs(evalNum(p.x, env)) + 8, y: ys(evalNum(p.y, env)) - 8, class: "point-label", text: p.label }, svg);
    }
  };

  /* ------------------------------------------------------------ view */

  // Trails: faint copies of earlier states stay behind as the model moves, so a learner sees the
  // whole relationship rather than one state at a time. Only for pictures whose marks move smoothly.
  const TRAIL_TYPES = new Set(["curves", "bars", "geometry"]);
  const TRAIL_MARKS = "path.series:not(.dashed), circle.point, rect.bar, line.vector, polygon.poly, line.segment";
  const TRAIL_MAX = 8, TRAIL_GAP_MS = 260;
  const trailPref = () => { try { return localStorage.getItem("lemma-trails") !== "0"; } catch (e) { return true; } };

  class ModelView {
    constructor(container, model) {
      this.model = model;
      this.root = container;
      container.classList.add("model-view");
      container.innerHTML = '<div class="viz-wrap"></div><div class="viz-status" aria-live="off"></div><div class="legend"></div>';
      this.vizEl = container.querySelector(".viz-wrap");
      this.statusEl = container.querySelector(".viz-status");
      this.legendEl = container.querySelector(".legend");
      this.simKey = null;
      this.frameTimer = null;
      this.onSettle = null;
      this.ghosts = [];
      this.trailsOn = trailPref();
      this.watchSize();
    }

    update(values, opts = {}) {
      const vis = this.model.visual || {};
      let res;
      try {
        res = compute(this.model, values, { skipSim: !!opts.transient });
      } catch (e) {
        this.vizEl.textContent = "This model couldn't be evaluated: " + e.message;
        return null;
      }
      const sim = res.sim || (opts.transient ? this.lastSim : null);
      if (res.sim) this.lastSim = res.sim;
      const key = res.sim ? JSON.stringify(res.sim.params) : null;
      const fresh = key !== null && key !== this.simKey && !opts.resized;
      if (key !== null) this.simKey = key;
      const legendItems = [];
      const self = this;
      if (opts.resized) this.ghosts = [];
      else this.snapTrail(vis, values);
      this.lastValues = values;
      this.W = this.chartWidth();
      const ctx = {
        vis, env: res.env, sim, container: this.vizEl, transient: !!opts.transient, W: this.W,
        svgIn: (w, h) => svgRoot(this.vizEl, w, h, this.model.title),
        legend: (items) => legendItems.push(...items),
        status: (s) => { this.statusEl.textContent = s; },
        frames(total, draw) {
          clearInterval(self.frameTimer);
          if (!fresh || ctx.transient || reduceMotion() || total <= 1) {
            draw(total - 1);
            if (!ctx.transient && !opts.resized && self.onSettle) self.onSettle();
            return;
          }
          let i = 0;
          const per = Math.max(16, Math.min(90, 1800 / total));
          draw(0);
          self.settling = true;
          self.frameTimer = setInterval(() => {
            i++;
            if (i >= total) { clearInterval(self.frameTimer); self.settling = false; if (self.onSettle) self.onSettle(); return; }
            draw(i);
          }, per);
        },
      };
      const r = R[vis.type];
      if (!r) this.vizEl.textContent = "Unknown visual type";
      else r(ctx);
      if (!vis.kernel && !opts.transient && !opts.resized && this.onSettle) this.onSettle();
      this.drawTrail();
      this.renderLegend(legendItems);
      return res.env;
    }

    get trails() { return TRAIL_TYPES.has((this.model.visual || {}).type); }

    setTrails(on) {
      this.trailsOn = on;
      try { localStorage.setItem("lemma-trails", on ? "1" : "0"); } catch (e) { /* storage unavailable */ }
      this.clearTrail();
    }

    clearTrail() {
      this.ghosts = [];
      this.vizEl.querySelectorAll("g.trail").forEach((g) => g.remove());
    }

    // Before redrawing, keep a copy of the marks as they are now, at most every TRAIL_GAP_MS.
    snapTrail(vis, values) {
      if (!this.trailsOn || !this.trails || reduceMotion() || !this.lastValues) return;
      const now = performance.now();
      if (now - (this.trailAt || 0) < TRAIL_GAP_MS || JSON.stringify(values) === JSON.stringify(this.lastValues)) return;
      const svg = this.vizEl.querySelector("svg.viz");
      if (!svg) return;
      const nodes = [...svg.querySelectorAll(TRAIL_MARKS)].filter((n) => !n.closest("g.trail")).map((n) => {
        const c = n.cloneNode(false);
        c.classList.add("ghost");
        c.removeAttribute("marker-end");
        if (n.tagName === "rect" || n.tagName === "polygon") {
          const fill = (n.getAttribute("style") || "").match(/fill:([^;]+)/);
          c.setAttribute("style", `fill:none;stroke:${fill ? fill[1] : "var(--ink)"}`);
        }
        return c;
      });
      if (!nodes.length) return;
      this.trailAt = now;
      this.ghosts.push(nodes);
      if (this.ghosts.length > TRAIL_MAX) this.ghosts.shift();
    }

    // Put the copies under the live marks, older ones fainter.
    drawTrail() {
      if (!this.ghosts.length) return;
      const svg = this.vizEl.querySelector("svg.viz");
      const live = svg && svg.querySelector(TRAIL_MARKS);
      if (!live) return;
      const n = this.ghosts.length;
      this.ghosts.forEach((nodes, i) => {
        const g = document.createElementNS(SVGNS, "g");
        g.setAttribute("class", "trail");
        g.setAttribute("aria-hidden", "true");
        g.setAttribute("opacity", (0.1 + (0.32 * (i + 1)) / n).toFixed(2));
        g.append(...nodes);
        live.parentNode.insertBefore(g, live);
      });
    }

    /* Charts are drawn in a coordinate space as wide as their box (360–640), so text stays a
       readable size on phones instead of shrinking with a fixed 640-wide drawing. */
    chartWidth() {
      const cw = this.vizEl.clientWidth;
      return cw ? Math.round(Math.max(360, Math.min(640, cw))) : 640;
    }

    watchSize() {
      if (this.resizeObs || typeof ResizeObserver === "undefined") return;
      this.resizeObs = new ResizeObserver(() => {
        const w = this.chartWidth();
        if (this.lastValues && Math.abs(w - (this.W || 0)) > 24) this.update(this.lastValues, { resized: true });
      });
      this.resizeObs.observe(this.vizEl);
    }

    renderLegend(items) {
      this.legendEl.replaceChildren(...items.filter((i) => i.label).map((i) => {
        const s = document.createElement("span");
        s.className = "legend-item";
        const sw = document.createElement("span");
        sw.className = "swatch " + (i.shape || (i.dashed ? "dash" : i.area ? "area" : "line"));
        sw.style.setProperty("--sw", i.swatch ? `var(${i.swatch})` : col(i.color));
        s.append(sw, document.createTextNode(i.label));
        return s;
      }));
    }

    get busy() { return !!this.settling; }
    destroy() { clearInterval(this.frameTimer); if (this.resizeObs) this.resizeObs.disconnect(); }
  }

  root.LemmaModel = { compute, holds, defaults, fmt, ModelView, evalNum, reduceMotion, TRAIL_TYPES };
})(typeof window !== "undefined" ? window : globalThis);
