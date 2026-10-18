"""The lesson format and the quality checks every lesson must pass before a learner sees it.

A lesson is plain JSON (see ``SCHEMA_GUIDE``). ``check_lesson`` returns a list of
problems; an empty list means the lesson may be shown. The checks cover:

* structure: every step of every concept is present and well formed;
* grounding: each concept's quote appears word for word in the paper;
* working models: every expression evaluates to a finite number across the
  controls' ranges, and every visual can be drawn;
* reachable goals: each goal is false at the start and true at its stated
  solution, which sits on the sliders' step grid;
* honest labelling: each model says that it is a simplified teaching model.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from itertools import product

from . import expr, kernels

VISUAL_TYPES = ("curves", "bars", "table", "agents", "network", "causal", "sampling", "geometry")
KERNEL_VISUAL = {name: spec["visual"] for name, spec in kernels.KERNELS.items()}
CHECK_KINDS = ("model", "choice", "truefalse", "numeric", "order")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
NUMBER_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
RESERVED = set(expr.FUNCTIONS) | set(expr.CONSTANTS) | {"x", "and", "or", "not"}
PALETTE_SIZE = 8


class Problems(list):
    def add(self, where: str, msg: str):
        self.append(f"{where}: {msg}")


# ---------------------------------------------------------------- grounding


def normalize_for_match(text: str) -> str:
    """Reduce text to lowercase letters and digits so PDF spacing, hyphenation,
    ligatures and curly quotes don't hide a genuine word-for-word quote."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("­", "")  # soft hyphen
    text = re.sub(r"-\s*\n\s*", "", text)  # word broken across a line
    return re.sub(r"[^0-9a-z]+", "", text.lower())


def quote_in_source(quote: str, source_norm: str) -> bool:
    q = normalize_for_match(quote)
    return bool(q) and q in source_norm


# ---------------------------------------------------------------- models


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _finite(v) -> bool:
    return _is_num(v) and math.isfinite(v)


def model_kernel(model: dict) -> str | None:
    vis = model.get("visual") or {}
    k = vis.get("kernel")
    return k if isinstance(k, str) and k in kernels.KERNELS else None


def defaults(model: dict) -> dict:
    return {c["id"]: float(c.get("default", 0)) for c in model.get("controls", []) if isinstance(c, dict) and "id" in c}


def compute(model: dict, values: dict) -> dict:
    """Evaluate a model's outputs (and simulation metrics) for the given control values.

    Mirrors ``compute`` in ``static/visuals.js``.
    """
    env = dict(defaults(model))
    env.update({k: float(v) for k, v in values.items()})
    kernel = model_kernel(model)
    ran = False

    def run_sim():
        params = {k: expr.evaluate(v, env) for k, v in (model["visual"].get("params") or {}).items()}
        for m, val in kernels.run(kernel, params).items():
            env["sim_" + m] = val

    for out in model.get("outputs", []):
        src = out["expr"]
        if kernel and not ran and any(n.startswith("sim_") for n in expr.names(src)):
            run_sim()
            ran = True
        env[out["id"]] = expr.evaluate(src, env)
    if kernel and not ran:
        run_sim()
    return env


def _sample_points(model: dict, limit: int = 60) -> list[dict]:
    """Control settings to test: defaults, each control at its extremes, and a grid."""
    ctrls = [c for c in model.get("controls", []) if isinstance(c, dict)]
    base = defaults(model)
    pts = [dict(base)]
    for c in ctrls:
        for v in (c["min"], c["max"]):
            p = dict(base)
            p[c["id"]] = v
            pts.append(p)
    grids = [[c["min"], (c["min"] + c["max"]) / 2, c["max"]] for c in ctrls]
    for combo in product(*grids):
        if len(pts) >= limit:
            break
        pts.append({c["id"]: v for c, v in zip(ctrls, combo)})
    return pts


def _check_controls(model, where, P: Problems) -> set[str]:
    ids = set()
    ctrls = model.get("controls")
    if not isinstance(ctrls, list) or not 1 <= len(ctrls) <= 4:
        P.add(where, "a model needs 1–4 controls")
        return ids
    for i, c in enumerate(ctrls):
        w = f"{where}.controls[{i}]"
        if not isinstance(c, dict):
            P.add(w, "must be an object")
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not ID_RE.match(cid) or cid in RESERVED or cid.startswith("sim_"):
            P.add(w, f"id {cid!r} must be lower_snake_case and not a reserved word")
            continue
        if cid in ids:
            P.add(w, f"duplicate id {cid!r}")
        ids.add(cid)
        if not isinstance(c.get("label"), str) or not c["label"].strip():
            P.add(w, "needs a label")
        kind = c.get("kind", "slider")
        if kind == "toggle":
            c.setdefault("min", 0)
            c.setdefault("max", 1)
            c.setdefault("step", 1)
            c.setdefault("default", 0)
            if c.get("min") != 0 or c.get("max") != 1 or c.get("step") != 1:
                P.add(w, "a toggle has min 0, max 1, step 1")
        elif kind != "slider":
            P.add(w, "kind must be 'slider' or 'toggle'")
        lo, hi, step, d = c.get("min"), c.get("max"), c.get("step"), c.get("default")
        if not all(_finite(v) for v in (lo, hi, step, d)):
            P.add(w, "min, max, step and default must be numbers")
            c.update({"min": 0, "max": 1, "step": 1, "default": 0})
            continue
        if not lo < hi:
            P.add(w, "min must be below max")
        if step <= 0 or step > hi - lo:
            P.add(w, "step must be positive and no larger than the range")
        elif (hi - lo) / step > 2000:
            P.add(w, "step is too fine (more than 2000 positions)")
        if not lo <= d <= hi:
            P.add(w, "default must be within min..max")
        elif step > 0 and not on_grid(d, lo, step):
            P.add(w, "default must sit on the step grid (min + k × step)")
    return ids


def on_grid(v, lo, step) -> bool:
    k = (v - lo) / step
    return abs(k - round(k)) < 1e-6


def _check_expr(src, known: set[str], where, P: Problems) -> bool:
    if _is_num(src):
        return True
    try:
        used = expr.names(src)
    except expr.ExprError as e:
        P.add(where, f"bad expression: {e}")
        return False
    unknown = used - known
    if unknown:
        P.add(where, f"expression {src!r} uses unknown names {sorted(unknown)}; available: {sorted(known)}")
        return False
    return True


def _num_fields(visual: dict) -> list[tuple[str, object, bool]]:
    """(path, expression, uses_x) for every numeric field of a visual."""
    t = visual.get("type")
    out = []

    def add(path, v, uses_x=False):
        if v is not None:
            out.append((path, v, uses_x))

    def each(key):
        items = visual.get(key) or []
        return [(i, it) for i, it in enumerate(items) if isinstance(it, dict)]

    if t == "curves":
        for axis in ("x", "y"):
            a = visual.get(axis) or {}
            add(f"{axis}.min", a.get("min"))
            add(f"{axis}.max", a.get("max"))
        for i, s in each("series"):
            add(f"series[{i}].expr", s.get("expr"), True)
        for i, f in each("fills"):
            add(f"fills[{i}].from", f.get("from"))
            add(f"fills[{i}].to", f.get("to"))
        for i, m in each("markers"):
            add(f"markers[{i}].x", m.get("x"))
        for i, h in each("hlines"):
            add(f"hlines[{i}].y", h.get("y"))
        for i, p in each("points"):
            add(f"points[{i}].x", p.get("x"))
            add(f"points[{i}].y", p.get("y"))
    elif t == "bars":
        for i, b in each("bars"):
            add(f"bars[{i}].value", b.get("value"))
        add("min", visual.get("min"))
        add("max", visual.get("max"))
    elif t == "table":
        for r, row in each("rows"):
            for c, cell in enumerate(row.get("cells") or []):
                if isinstance(cell, dict):
                    add(f"rows[{r}].cells[{c}].value", cell.get("value"))
                    add(f"rows[{r}].cells[{c}].highlight", cell.get("highlight"))
                else:
                    add(f"rows[{r}].cells[{c}]", cell)
        add("scale_min", visual.get("scale_min"))
        add("scale_max", visual.get("scale_max"))
    elif t in ("agents", "network", "sampling"):
        for k, v in (visual.get("params") or {}).items():
            add(f"params.{k}", v)
    elif t == "causal":
        for i, e in each("edges"):
            add(f"edges[{i}].strength", e.get("strength"))
        for i, n in each("nodes"):
            add(f"nodes[{i}].value", n.get("value"))
    elif t == "geometry":
        for key in ("xmin", "xmax", "ymin", "ymax"):
            add(key, visual.get(key))
        for i, v in each("vectors"):
            for k in ("x", "y", "from_x", "from_y"):
                add(f"vectors[{i}].{k}", v.get(k))
        for i, p in each("points"):
            add(f"points[{i}].x", p.get("x"))
            add(f"points[{i}].y", p.get("y"))
        for i, s in each("segments"):
            for k in ("x1", "y1", "x2", "y2"):
                add(f"segments[{i}].{k}", s.get(k))
        for i, c in each("circles"):
            for k in ("x", "y", "r"):
                add(f"circles[{i}].{k}", c.get(k))
        for i, poly in each("polygons"):
            for j, pt in enumerate(poly.get("points") or []):
                if isinstance(pt, list) and len(pt) == 2:
                    add(f"polygons[{i}].points[{j}].x", pt[0])
                    add(f"polygons[{i}].points[{j}].y", pt[1])
    return out


def _check_visual_shape(vis, where, P: Problems):
    t = vis.get("type")
    if t not in VISUAL_TYPES:
        P.add(where, f"type must be one of {VISUAL_TYPES}")
        return
    if t in ("agents", "network", "sampling"):
        k = vis.get("kernel")
        if KERNEL_VISUAL.get(k) != t:
            ok = [n for n, v in KERNEL_VISUAL.items() if v == t]
            P.add(where, f"a {t} visual needs kernel one of {ok}")
            return
        params = vis.get("params") or {}
        if not isinstance(params, dict):
            P.add(where, "params must be an object")
            return
        extra = set(params) - set(kernels.KERNELS[k]["params"])
        if extra:
            P.add(where, f"kernel {k!r} has no parameters {sorted(extra)}")
    need = {
        "curves": ("x", "y", "series"),
        "bars": ("bars",),
        "table": ("columns", "rows"),
        "causal": ("nodes", "edges"),
        "geometry": ("xmin", "xmax", "ymin", "ymax"),
    }.get(t, ())
    for key in need:
        if key not in vis:
            P.add(where, f"a {t} visual needs '{key}'")
    if t == "curves":
        if not vis.get("series"):
            P.add(where, "needs at least one series")
        for i, f in enumerate(vis.get("fills") or []):
            if not (isinstance(f.get("series"), int) and 0 <= f["series"] < len(vis.get("series") or [])):
                P.add(f"{where}.fills[{i}]", "series must be the index of a series")
    if t == "table":
        ncol = len(vis.get("columns") or [])
        for r, row in enumerate(vis.get("rows") or []):
            if len(row.get("cells") or []) != ncol:
                P.add(f"{where}.rows[{r}]", f"needs {ncol} cells, one per column")
    if t == "causal":
        ids = {n.get("id") for n in vis.get("nodes") or [] if isinstance(n, dict)}
        for i, e in enumerate(vis.get("edges") or []):
            if e.get("from") not in ids or e.get("to") not in ids:
                P.add(f"{where}.edges[{i}]", "from and to must be node ids")
        for i, n in enumerate(vis.get("nodes") or []):
            if not all(_finite(n.get(k)) and 0 <= n.get(k) <= 100 for k in ("x", "y")):
                P.add(f"{where}.nodes[{i}]", "x and y must be numbers from 0 to 100")


def check_model(model, where, P: Problems) -> tuple[set[str], set[str]]:
    """Returns (control ids, all names usable in goal expressions)."""
    if not isinstance(model, dict):
        P.add(where, "model must be an object")
        return set(), set()
    if not isinstance(model.get("note"), str) or len(model["note"].strip()) < 10:
        P.add(where, "needs a 'note' saying this is a simplified teaching model and whether its numbers are illustrative")
    ctrl_ids = _check_controls(model, where, P)
    vis = model.get("visual")
    if not isinstance(vis, dict):
        P.add(where, "needs a visual")
        return ctrl_ids, set(ctrl_ids)
    _check_visual_shape(vis, f"{where}.visual", P)
    kernel = model_kernel(model)
    sim_names = {"sim_" + m for m in kernels.KERNELS[kernel]["metrics"]} if kernel else set()

    known = set(ctrl_ids)
    outputs = model.get("outputs") or []
    if not isinstance(outputs, list) or len(outputs) > 6:
        P.add(where, "outputs must be a list of at most 6")
        outputs = []
    model["outputs"] = outputs
    ok = True
    for i, o in enumerate(outputs):
        w = f"{where}.outputs[{i}]"
        if not isinstance(o, dict):
            P.add(w, "must be an object")
            ok = False
            continue
        oid = o.get("id")
        if not isinstance(oid, str) or not ID_RE.match(oid) or oid in RESERVED or oid in known or oid.startswith("sim_"):
            P.add(w, f"id {oid!r} must be unique lower_snake_case and not reserved")
            ok = False
            continue
        if not isinstance(o.get("label"), str):
            P.add(w, "needs a label")
        if "expr" not in o or not _check_expr(o["expr"], known | sim_names, w, P):
            ok = False
        known.add(oid)

    vis_known = known | sim_names
    fields = _num_fields(vis)
    for path, src, uses_x in fields:
        if not _check_expr(src, vis_known | ({"x"} if uses_x else set()), f"{where}.visual.{path}", P):
            ok = False
    if not ok or P_has(P, where):
        return ctrl_ids, vis_known

    # Every expression must give a finite number across the controls' ranges.
    for pt in _sample_points(model):
        try:
            env = compute(model, pt)
        except expr.ExprError as e:
            P.add(where, f"model fails at {pt}: {e}")
            return ctrl_ids, vis_known
        for o in outputs:
            if not math.isfinite(env[o["id"]]):
                P.add(where, f"output {o['id']!r} is not a finite number when controls are {_fmt(pt)}")
                return ctrl_ids, vis_known
        for path, src, uses_x in fields:
            if uses_x:
                continue
            v = expr.evaluate(src, env)
            if not math.isfinite(v):
                P.add(where, f"visual.{path} is not a finite number when controls are {_fmt(pt)}")
                return ctrl_ids, vis_known
        if vis.get("type") == "curves":
            x0 = expr.evaluate(vis["x"]["min"], env)
            x1 = expr.evaluate(vis["x"]["max"], env)
            if not x0 < x1:
                P.add(where, "visual x.min must be below x.max")
                return ctrl_ids, vis_known
            for i, s in enumerate(vis["series"]):
                good = 0
                for k in range(41):
                    e2 = dict(env)
                    e2["x"] = x0 + (x1 - x0) * k / 40
                    if math.isfinite(expr.evaluate(s["expr"], e2)):
                        good += 1
                if good < 30:
                    P.add(where, f"series[{i}] is undefined over most of the x range when controls are {_fmt(pt)}")
                    return ctrl_ids, vis_known
    return ctrl_ids, vis_known


def P_has(P: Problems, where: str) -> bool:
    return any(p.startswith(where) for p in P)


def _fmt(pt: dict) -> str:
    return ", ".join(f"{k}={v:g}" for k, v in pt.items())


def _control_map(model) -> dict:
    return {c["id"]: c for c in model.get("controls", []) if isinstance(c, dict) and "id" in c}


def _pinned(model, when: str, sol: dict, cid: str, c: dict) -> bool:
    """Whether the goal fixes this control at exactly its solution value, so the value is part of the
    task (such as "set up the paper's case: power 0.6") rather than the answer to find."""
    v, step = sol[cid], c.get("step")
    neighbours = [v + d for d in (-step, step) if _finite(step) and step > 0 and c["min"] <= v + d <= c["max"]]
    try:
        return bool(neighbours) and not any(expr.evaluate(when, compute(model, {**sol, cid: n})) for n in neighbours)
    except expr.ExprError:
        return False


def _check_not_given_away(model, goal, where, P: Problems):
    """A goal and its hints say what to achieve and where to look, never the slider value that achieves it:
    finding that value is the practice, and Show me is there for a learner who is stuck. A value the goal
    itself fixes, such as the paper's own setting to start from, may be stated."""
    sol = goal.get("solution")
    if not isinstance(sol, dict):
        return
    sliders = {c["id"]: c for c in model.get("controls", []) if isinstance(c, dict) and c.get("kind", "slider") == "slider" and "id" in c}
    told = [goal.get("text") or ""] + [h for h in goal.get("hints") or [] if isinstance(h, str)]
    for cid, v in sol.items():
        c = sliders.get(cid)
        if c is None or not isinstance(v, (int, float)) or isinstance(v, bool) or v == c.get("default"):
            continue
        if isinstance(goal.get("when"), str) and _pinned(model, goal["when"], sol, cid, c):
            continue
        for i, text in enumerate(told):
            if any(abs(float(n) - v) < 1e-9 for n in NUMBER_RE.findall(str(text))):
                said = "its text" if i == 0 else f"hint {i}"
                P.add(where, f"{said} gives away the solution {cid} = {v:g}: say what to look for and leave the value for the learner to find")
                break


def _check_state_target(model, item, known, where, P: Problems, must_be_false_at=()):
    """A goal or model-check: `when` must be false at defaults and true at `solution`."""
    when = item.get("when")
    if not isinstance(when, str) or not _check_expr(when, known, f"{where}.when", P):
        if not isinstance(when, str):
            P.add(where, "needs a 'when' condition")
        return
    sol = item.get("solution")
    ctrls = _control_map(model)
    if not isinstance(sol, dict) or not sol:
        P.add(where, "needs a 'solution': control values that satisfy 'when'")
        return
    for cid, v in sol.items():
        c = ctrls.get(cid)
        if not c:
            P.add(where, f"solution sets unknown control {cid!r}")
            return
        if not _finite(v) or not c["min"] <= v <= c["max"]:
            P.add(where, f"solution {cid}={v} is outside {c['min']}..{c['max']}")
            return
        if not on_grid(v, c["min"], c["step"]):
            P.add(where, f"solution {cid}={v} is not reachable with step {c['step']} from {c['min']}")
            return
    try:
        at_default = expr.evaluate(when, compute(model, {}))
        at_solution = expr.evaluate(when, compute(model, sol))
    except expr.ExprError as e:
        P.add(where, f"cannot evaluate: {e}")
        return
    if at_default:
        P.add(where, f"'{when}' is already true before the learner does anything")
    if not at_solution:
        env = compute(model, sol)
        shown = {k: round(v, 4) for k, v in env.items() if k in expr.names(when)}
        P.add(where, f"'{when}' is false at its own solution {sol} (values there: {shown})")
    for label, state in must_be_false_at:
        try:
            if expr.evaluate(when, compute(model, state)):
                P.add(where, f"'{when}' is already true at {label}, so it checks nothing new")
        except expr.ExprError:
            pass


def _mentions(text: str, term: str) -> bool:
    return bool(re.search(r"(?<![\w-])" + re.escape(term.lower()) + r"(?![\w-])", text.lower()))


def _check_terms(c: dict, where: str, P: Problems):
    """Show it before naming it: a technical term stays out of the tour and the model's labels,
    and is first used once the walkthrough has shown what it means."""
    terms = c.get("terms", [])
    w = f"{where}.terms"
    if not isinstance(terms, list) or len(terms) > 4:
        P.add(w, "must be a list of at most 4 terms")
        return
    early = [st.get("say", "") for st in ((c.get("animation") or {}).get("steps") or []) if isinstance(st, dict)]
    m = c.get("model") or {}
    early += [m.get("title", "")] + [k.get("label", "") for k in (m.get("controls") or []) + (m.get("outputs") or []) if isinstance(k, dict)]
    u = c.get("understand") or {}
    later = [st.get("say", "") for st in ((u.get("walkthrough") or {}).get("steps") or []) if isinstance(st, dict)] + [u.get("explanation", "")]
    early_text = " \n ".join(x for x in early if isinstance(x, str))
    later_text = " \n ".join(x for x in later if isinstance(x, str))
    for i, t in enumerate(terms):
        tw = f"{w}[{i}]"
        term = _text(t, "term", tw, P, 60)
        _text(t, "means", tw, P, 200)
        if not term:
            continue
        if _mentions(early_text, term):
            P.add(tw, f"'{term}' is used before it is explained; say it in plain words in the tour and the model's labels, and name it from the walkthrough on")
        if not _mentions(later_text, term):
            P.add(tw, f"'{term}' never appears in the walkthrough or explanation, where it should be introduced")


def check_primer(primer, source_norm: str | None, where: str = "lesson.primer") -> Problems:
    """The paper in brief: 3–6 short pages read before the first concept, at least two quoting the paper."""
    P = Problems()
    if not isinstance(primer, list) or not 3 <= len(primer) <= 6:
        P.add(where, "needs 3–6 pages, each with 'heading' and 'body' (the question, what was done, what was found, why it matters)")
        return P
    quoted = 0
    for i, pg in enumerate(primer):
        pw = f"{where}[{i}]"
        if not isinstance(pg, dict):
            P.add(pw, "must be an object")
            continue
        _text(pg, "heading", pw, P, 60)
        _text(pg, "body", pw, P, 900)
        q = _text(pg, "quote", pw, P, 700, required=False)
        if q:
            quoted += 1
            if len(q.split()) < 6:
                P.add(pw, "quote is too short (at least 6 words)")
            if source_norm is not None and not quote_in_source(q, source_norm):
                P.add(pw, f"quote does not appear word for word in the paper: {q[:120]!r}")
    if quoted < 2:
        P.add(where, "at least two pages must quote the paper word for word")
    return P


def check_builds_on(c: dict, base: dict, where: str = "concept") -> Problems:
    """A concept that builds on an earlier one reuses its model: same picture, same controls, at most one new control."""
    P = Problems()
    m, bm = (c.get("model") or {}), (base.get("model") or {})
    if (m.get("visual") or {}).get("type") != (bm.get("visual") or {}).get("type"):
        P.add(f"{where}.model", f"builds on '{base.get('id')}', so it must keep its visual type '{(bm.get('visual') or {}).get('type')}'")
    ctrls = {k.get("id"): k for k in m.get("controls") or [] if isinstance(k, dict)}
    for k in bm.get("controls") or []:
        mine = ctrls.get(k.get("id"))
        if not mine:
            P.add(f"{where}.model", f"builds on '{base.get('id')}', so it must keep its control '{k.get('id')}'")
        elif any(mine.get(f) != k.get(f) for f in ("kind", "min", "max", "step", "label")):
            P.add(f"{where}.model", f"control '{k.get('id')}' must keep the same label and range as in '{base.get('id')}'")
    if len(ctrls) - len(bm.get("controls") or []) > 1:
        P.add(f"{where}.model", "add at most one new control to the model it builds on")
    return P


MARKABLE = ("series", "points", "markers", "hlines", "bars", "nodes")


def _mark_ids(vis) -> set:
    """Parts of the picture a narration step can point at: any series, point, marker, line, bar or node with an id."""
    if not isinstance(vis, dict):
        return set()
    return {m["id"] for key in MARKABLE for m in vis.get(key) or [] if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]}


def _check_narration(block, where, model, focusable, P: Problems, purpose: str):
    """A narrated animation: 2–8 steps, each saying one thing and optionally moving controls and pointing at a part."""
    steps = block.get("steps") if isinstance(block, dict) else None
    if not isinstance(steps, list) or not 2 <= len(steps) <= 8:
        P.add(where, f"needs {purpose}: 2–8 steps, each with 'say' and optionally 'set' and 'focus'")
        return
    ctrls = _control_map(model)
    for i, st in enumerate(steps):
        sw = f"{where}.steps[{i}]"
        if not isinstance(st, dict):
            P.add(sw, "must be an object")
            continue
        _text(st, "say", sw, P, 240)
        for cid, v in (st.get("set") or {}).items():
            cc = ctrls.get(cid)
            if not cc or not _finite(v) or not cc["min"] <= v <= cc["max"]:
                P.add(sw, f"sets {cid}={v}, which is not a control value in range")
        f = st.get("focus")
        if f is None:
            continue
        fs = f if isinstance(f, list) else [f]
        if not 1 <= len(fs) <= 4 or not all(isinstance(x, str) for x in fs):
            P.add(sw, "focus must name one part, or list 1–4 parts")
        for x in fs:
            if isinstance(x, str) and x not in focusable:
                P.add(sw, f"focus {x!r} is not a control, output or marked part of the picture")


def _text(obj, key, where, P: Problems, max_len=None, required=True):
    v = obj.get(key) if isinstance(obj, dict) else None
    if not isinstance(v, str) or not v.strip():
        if required:
            P.add(where, f"needs '{key}' text")
        return ""
    if max_len and len(v) > max_len:
        P.add(where, f"'{key}' is too long ({len(v)} characters, limit {max_len})")
    return v


def check_activities(c: dict, where: str, P: Problems):
    activities = c.get("activities")
    if not isinstance(activities, list) or not 2 <= len(activities) <= 24:
        P.add(where, "activities needs 2–24 teaching and response blocks")
        return
    seen, taught, engaged = set(), False, False
    native = {"watch": "animation", "walk": "understand", "goal": "explore", "predict": "predict", "reveal": "predict", "check": "check", "connect": "connect"}
    for i, a in enumerate(activities):
        w = f"{where}.activities[{i}]"
        if not isinstance(a, dict):
            P.add(w, "must be an object")
            continue
        aid = a.get("id")
        if not isinstance(aid, str) or not ID_RE.fullmatch(aid) or aid in seen:
            P.add(w, "id must be unique lower_snake_case")
        else:
            seen.add(aid)
        kind = a.get("kind")
        if "title" in a:
            _text(a, "title", w, P, 160)
        if kind == "explain":
            if "text" in a:
                _text(a, "text", w, P, 2000)
            taught = True
        elif isinstance(kind, str) and kind in native:
            if not c.get("model") or not c.get(native[kind]):
                P.add(w, f"{kind} needs its model and content")
            if kind == "watch" and not (c.get("animation") or {}).get("steps"):
                P.add(w, "watch needs narration steps")
            if kind == "walk" and not (c.get("understand") or {}).get("walkthrough", {}).get("steps"):
                P.add(w, "walk needs walkthrough steps")
            if kind == "predict" and (i + 1 >= len(activities) or not isinstance(activities[i + 1], dict) or activities[i + 1].get("kind") != "reveal"):
                P.add(w, "predict must be immediately followed by reveal")
            if kind == "reveal" and (i == 0 or not isinstance(activities[i - 1], dict) or activities[i - 1].get("kind") != "predict"):
                P.add(w, "reveal must immediately follow predict")
            if kind in ("watch", "walk"):
                taught = True
            if kind in ("goal", "predict", "check"):
                engaged = True
                if not taught:
                    P.add(w, "teach before practice")
            if kind == "goal":
                explore = c.get("explore")
                goals = explore.get("goals") if isinstance(explore, dict) else []
                goals = goals if isinstance(goals, list) else []
                if type(a.get("i")) is not int or not 0 <= a["i"] < len(goals):
                    P.add(w, "i must identify an existing goal")
        elif kind in ("sort", "construction", "inheritance"):
            engaged = True
            if not taught:
                P.add(w, "teach before practice")
            _text(a, "title", w, P, 160)
            _text(a, "prompt", w, P, 1000)
            if kind == "inheritance" and a.get("parent", "Aa") not in ("AA", "Aa", "aa"):
                P.add(w, "parent must be AA, Aa or aa")
            if kind == "sort":
                _text(a, "takeaway", w, P, 700)
                groups = a.get("groups")
                group_ids = set()
                if not isinstance(groups, list) or not 2 <= len(groups) <= 4:
                    P.add(w, "sort needs 2–4 groups")
                else:
                    for g in groups:
                        if not isinstance(g, dict) or not isinstance(g.get("id"), str) or not ID_RE.fullmatch(g["id"]) or g["id"] in group_ids:
                            P.add(w, "groups need unique lower_snake_case ids")
                            continue
                        group_ids.add(g["id"])
                        _text(g, "label", w, P, 160)
                cards = a.get("cards")
                if not isinstance(cards, list) or not 2 <= len(cards) <= 8:
                    P.add(w, "sort needs 2–8 cards")
                else:
                    card_ids = set()
                    for card in cards:
                        if not isinstance(card, dict):
                            P.add(w, "cards must be objects")
                            continue
                        cid = card.get("id")
                        if not isinstance(cid, str) or not ID_RE.fullmatch(cid) or cid in card_ids:
                            P.add(w, "cards need unique lower_snake_case ids")
                        else:
                            card_ids.add(cid)
                        _text(card, "text", w, P, 700)
                        _text(card, "feedback", w, P, 1200)
                        if not isinstance(card.get("group"), str) or card["group"] not in group_ids:
                            P.add(w, "card must reference an existing group")
        elif kind == "choice":
            engaged = True
            mode = a.get("mode")
            if not isinstance(mode, str) or mode not in ("determinate", "interpretive", "opening"):
                P.add(w, "mode must be determinate, interpretive or opening")
            if not taught and mode != "opening":
                P.add(w, "teach before practice")
            _text(a, "question", w, P, 1000)
            options = a.get("options")
            if not isinstance(options, list) or not 2 <= len(options) <= 6:
                P.add(w, "needs 2–6 options")
                continue
            for j, o in enumerate(options):
                ow = f"{w}.options[{j}]"
                if not isinstance(o, dict):
                    P.add(ow, "must be an object")
                    continue
                _text(o, "text", ow, P, 700)
                _text(o, "feedback", ow, P, 1200)
            if mode == "determinate" and (type(a.get("answer")) is not int or not 0 <= a["answer"] < len(options)):
                P.add(w, "answer must identify the supported option")
            if mode in ("interpretive", "opening") and "answer" in a:
                P.add(w, "unscored activities must not have an answer key")
        else:
            P.add(w, "unsupported activity kind")
    if not taught or not engaged:
        P.add(where, "activities must include teaching and meaningful engagement")


def check_concept(c: dict, source_norm: str | None, where: str = "concept") -> Problems:
    P = Problems()
    if not isinstance(c, dict):
        P.add(where, "must be an object")
        return P
    if not isinstance(c.get("id"), str) or not ID_RE.match(c["id"]):
        P.add(where, "id must be lower_snake_case")
    _text(c, "title", where, P, 80)
    _text(c, "idea", where, P, 240)
    _text(c, "recap", where, P, 200)

    if "activities" in c:
        check_activities(c, where, P)
        if "model" not in c:
            u = c.get("understand")
            if not isinstance(u, dict):
                P.add(where, "understand must contain the explanation and source quote")
                return P
            _text(u, "explanation", f"{where}.understand", P, 1400)
            quote = _text(u, "quote", f"{where}.understand", P, 700)
            if quote and (len(quote.split()) < 6 or source_norm is not None and not quote_in_source(quote, source_norm)):
                P.add(where, "quote must contain at least 6 words and appear word for word in the source")
            _text(u, "quote_where", f"{where}.understand", P, 300)
            _check_terms(c, where, P)
            return P

    pr = c.get("predict") or {}
    w = f"{where}.predict"
    _text(pr, "question", w, P, 300)
    opts = pr.get("options")
    if not isinstance(opts, list) or not 2 <= len(opts) <= 5 or not all(isinstance(o, str) and o.strip() for o in opts):
        P.add(w, "needs 2–5 option strings")
    elif not (isinstance(pr.get("answer"), int) and 0 <= pr["answer"] < len(opts)):
        P.add(w, "answer must be the index of the correct option")
    else:
        why = pr.get("why")
        if not isinstance(why, list) or len(why) != len(opts) or not all(isinstance(x, str) and x.strip() for x in why):
            P.add(w, "needs 'why': one short line per option, in the same order, saying why someone would pick it and what the model shows")
        elif any(len(x) > 260 for x in why):
            P.add(w, "each 'why' line must be at most 260 characters")

    model = c.get("model")
    ctrl_ids, known = check_model(model, f"{where}.model", P)
    model_ok = not P_has(P, f"{where}.model")

    ex = c.get("explore") or {}
    w = f"{where}.explore"
    _text(ex, "prompt", w, P, 400)
    goals = ex.get("goals")
    goal_states = []
    if not isinstance(goals, list) or not 1 <= len(goals) <= 2:
        P.add(w, "needs one or two goals")
        goals = []
    for i, g in enumerate(goals):
        gw = f"{w}.goals[{i}]"
        _text(g, "text", gw, P, 200)
        hints = g.get("hints")
        if not isinstance(hints, list) or not 2 <= len(hints) <= 3 or not all(isinstance(x, str) and x.strip() for x in hints):
            P.add(gw, "needs 'hints': 2–3 lines that get more specific, from a nudge to a partial answer")
        elif any(len(x) > 240 for x in hints):
            P.add(gw, "each hint must be at most 240 characters")
        if model_ok:
            _check_state_target(model, g, known, gw, P)
            _check_not_given_away(model, g, gw, P)
        if isinstance(g.get("solution"), dict):
            goal_states.append((f"goal {i + 1}'s solution", g["solution"]))

    focusable = set(ctrl_ids) | {o.get("id") for o in (model or {}).get("outputs", []) if isinstance(o, dict)} | _mark_ids((model or {}).get("visual"))
    if model_ok:
        _check_narration(c.get("animation"), f"{where}.animation", model, focusable, P, "a narrated tour that introduces the model before anything is asked")

    u = c.get("understand") or {}
    w = f"{where}.understand"
    fb = u.get("feedback") or {}
    _text(fb, "correct", f"{w}.feedback", P, 400)
    _text(fb, "incorrect", f"{w}.feedback", P, 400)
    _text(u, "explanation", w, P, 1400)
    if model_ok:
        _check_narration(u.get("walkthrough"), f"{w}.walkthrough", model, focusable, P, "a narrated walkthrough that moves the model through the mechanism")
    quote = _text(u, "quote", w, P, 700)
    if quote:
        words = len(quote.split())
        if words < 6:
            P.add(w, "quote is too short to ground the idea (at least 6 words)")
        if source_norm is not None and not quote_in_source(quote, source_norm):
            P.add(w, f"quote does not appear word for word in the paper: {quote[:120]!r}")

    _check_terms(c, where, P)

    # Checks are for hard concepts only; an easy concept teaches without a quiz.
    ck = c.get("check")
    w = f"{where}.check"
    if ck is None:
        ck = {"kind": "none"}
    kind = ck.get("kind")
    if kind != "none":
        if kind not in CHECK_KINDS:
            P.add(w, f"kind must be one of {CHECK_KINDS}")
        _text(ck, "hint", w, P, 300)
        _text(ck, "misconception", w, P, 400)
    if kind == "model":
        _text(ck, "task", w, P, 300)
        if model_ok:
            _check_state_target(model, ck, known, w, P, must_be_false_at=goal_states)
    elif kind == "choice":
        _text(ck, "question", w, P, 300)
        opts = ck.get("options")
        if not isinstance(opts, list) or not 2 <= len(opts) <= 6:
            P.add(w, "needs 2–6 options")
        else:
            for i, o in enumerate(opts):
                if not isinstance(o, dict) or not isinstance(o.get("text"), str) or not isinstance(o.get("correct"), bool):
                    P.add(f"{w}.options[{i}]", "needs text and correct (true/false)")
            n_ok = sum(1 for o in opts if isinstance(o, dict) and o.get("correct") is True)
            if n_ok == 0:
                P.add(w, "at least one option must be correct")
            if not ck.get("multi") and n_ok > 1:
                P.add(w, "only one option may be correct unless multi is true")
    elif kind == "truefalse":
        _text(ck, "statement", w, P, 300)
        if not isinstance(ck.get("answer"), bool):
            P.add(w, "answer must be true or false")
    elif kind == "numeric":
        _text(ck, "question", w, P, 300)
        if not _finite(ck.get("answer")) or not _finite(ck.get("tolerance")) or ck["tolerance"] < 0:
            P.add(w, "needs a numeric answer and a non-negative tolerance")
    elif kind == "order":
        _text(ck, "prompt", w, P, 300)
        items = ck.get("items")
        if not isinstance(items, list) or not 3 <= len(items) <= 6 or not all(isinstance(i, str) and i.strip() for i in items):
            P.add(w, "needs 3–6 items, listed in the correct order")
        elif len(set(items)) != len(items):
            P.add(w, "items must be distinct")

    cn = c.get("connect") or {}
    w = f"{where}.connect"
    parts = cn.get("equation")
    if not isinstance(parts, list) or not parts:
        P.add(w, "needs an equation: a list of parts")
    else:
        names = set(ctrl_ids) | {o.get("id") for o in (model or {}).get("outputs", []) if isinstance(o, dict)}
        linked = 0
        for i, part in enumerate(parts):
            if not isinstance(part, dict) or not isinstance(part.get("text"), str) or not part["text"]:
                P.add(f"{w}.equation[{i}]", "each part needs text")
                continue
            link = part.get("link")
            if link is not None:
                if link not in names:
                    P.add(f"{w}.equation[{i}]", f"link {link!r} is not a control or output of the model")
                else:
                    linked += 1
        if not linked:
            P.add(w, "at least one part of the equation must link to a control or output")
    _text(cn, "caption", w, P, 500)
    return P


def source_map(source_text: str | None) -> dict:
    """Decode a persisted source bundle; plain-text legacy sources remain supported."""
    if not source_text or not source_text.lstrip().startswith('{"lemma_sources":'):
        return {}
    try:
        sources = json.loads(source_text)["lemma_sources"]
        return {s["id"]: s for s in sources}
    except (ValueError, KeyError, TypeError):
        return {}


def source_document(source_text: str) -> str:
    sources = source_map(source_text)
    return "\n\n".join(f"SOURCE {sid}: {s['title']}\n{s['text']}" for sid, s in sources.items()) if sources else source_text


def check_attribution(block: dict, sources: dict, where: str) -> list[str]:
    problems = []
    refs = block.get("source_ids")
    if not isinstance(refs, list) or not refs or any(not isinstance(r, str) or r not in sources for r in refs):
        problems.append(f"{where}: source_ids must identify the supporting sources")
    if isinstance(block.get("quote"), str) and block["quote"]:
        sid = block.get("source_id")
        if not isinstance(sid, str) or sid not in sources:
            problems.append(f"{where}: quote needs a valid source_id")
        elif not quote_in_source(block["quote"], normalize_for_match(sources[sid]["text"])):
            problems.append(f"{where}: quote does not appear in its identified source")
        elif isinstance(refs, list) and sid not in refs:
            problems.append(f"{where}: quote source must be included in source_ids")
    return problems


def check_lesson(lesson: dict, source_text: str | None) -> Problems:
    """All quality checks. ``source_text=None`` skips grounding (e.g. for an offline copy)."""
    P = Problems()
    if not isinstance(lesson, dict):
        P.add("lesson", "must be an object")
        return P
    _text(lesson, "title", "lesson", P, 200)
    src = lesson.get("source") or {}
    _text(src, "title", "lesson.source", P, 400)
    intro = lesson.get("intro") or {}
    _text(intro, "summary", "lesson.intro", P, 1500)
    bg = intro.get("background", [])
    if not isinstance(bg, list) or not all(isinstance(b, str) for b in bg):
        P.add("lesson.intro", "background must be a list of strings")
    sources = source_map(source_text)
    norm = normalize_for_match(source_document(source_text)) if source_text is not None else None
    if sources:
        expected = [{k: v for k, v in s.items() if k != "text"} for s in sources.values()]
        if lesson.get("sources") != expected:
            P.add("lesson.sources", "must match the original source metadata")
    if lesson.get("primer") is not None:
        P.extend(check_primer(lesson["primer"], norm))
        if sources:
            for i, page in enumerate(lesson["primer"]):
                if isinstance(page, dict):
                    P.extend(check_attribution(page, sources, f"primer[{i}]"))
    concepts = lesson.get("concepts")
    if not isinstance(concepts, list) or not 1 <= len(concepts) <= 8:
        P.add("lesson", "needs 1–8 concepts")
        return P
    n_checks = sum(1 for c in concepts if isinstance(c, dict) and c.get("check"))
    if n_checks > 2:
        P.add("lesson", f"{n_checks} concepts have a check; keep checks for the one or two hardest concepts")
    aha = intro.get("aha")
    if aha is not None and (not isinstance(aha, str) or not aha.strip() or len(aha) > 300):
        P.add("lesson.intro", "aha must be one sentence of at most 300 characters")
    seen: dict = {}
    for i, c in enumerate(concepts):
        P.extend(check_concept(c, norm, f"concepts[{i}]"))
        if sources and isinstance(c, dict) and isinstance(c.get("understand"), dict):
            P.extend(check_attribution(c["understand"], sources, f"concepts[{i}].understand"))
        cid = c.get("id") if isinstance(c, dict) else None
        if cid in seen:
            P.add(f"concepts[{i}]", f"duplicate concept id {cid!r}")
        if isinstance(c, dict) and c.get("builds_on") is not None:
            base = seen.get(c["builds_on"])
            if base is None:
                P.add(f"concepts[{i}]", f"builds_on {c['builds_on']!r} must name an earlier concept in the lesson")
            else:
                P.extend(check_builds_on(c, base, f"concepts[{i}]"))
        seen[cid] = c
    return P


# ---------------------------------------------------------------- guide for the generator

SCHEMA_GUIDE = r"""
A CONCEPT is one JSON object. The learner meets it in this order: the tour, the walkthrough, the explanation and
quote (all teaching), then the goals (hands-on practice), then the predict question (applying the idea to a new case),
then the check (hard concepts only), then the equation.

{
  "id": "lower_snake_case",
  "title": "Short title (≤ 80 chars)",
  "idea": "The one mechanism this concept teaches, in one plain sentence",
  "role": "prerequisite" | "core" | "contribution",
  "predict": {
    "question": "Asked AFTER the idea is taught and practised: apply it to a new case or variation, not a repeat of the explanation",
    "options": ["2–5 short options"],
    "answer": 0,                                 // index of the correct option
    "why": ["One line per option, same order: why someone would pick it and what the idea says instead (or, for the answer, why it holds)"]
  },
  "terms": [                                     // 0–4 technical terms this concept introduces. Show it before naming it:
    {"term": "effect size", "means": "How far apart two groups are, in units of their spread"}
  ],                                             // a term must NOT appear in the tour or the model's title and labels; name it from the walkthrough on
  "model": {
    "title": "What the model shows",
    "note": "Teaching model: <how it is simplified>. Numbers are illustrative, not the paper's data.",
    "controls": [                                // 1–4 controls
      {"id": "d", "label": "Effect size d", "kind": "slider", "min": 0, "max": 2, "step": 0.1, "default": 0.2, "unit": "", "color": 0},
      {"id": "show_null", "label": "Show the null", "kind": "toggle", "default": 0}
    ],
    "outputs": [                                 // 0–6 key numbers, evaluated in order
      {"id": "overlap", "label": "Overlap", "expr": "2 * normcdf(-d / 2)", "unit": "%", "scale": 100, "decimals": 0}
    ],
    "visual": { ...one of the VISUAL TYPES below... }
  },
  "animation": {                                 // REQUIRED tour, 3–6 steps, played first.
    "steps": [                                   // The learner knows nothing yet: introduce the picture first
      {"say": "This curve shows ...", "focus": "treated", "ms": 2200},          // focus points at a control, an output, or a part
                                                                               // of the picture with an "id"; or a list of up to 4
      {"say": "This slider sets d, the gap between the groups. Watch what it does.", "set": {"d": 0.8}, "focus": "d", "ms": 2400}
    ]
  },
  "explore": {
    "prompt": "What to try, phrased as play: practise the idea just taught",
    "goals": [                                   // 1–2 goals
      {"text": "Make the groups overlap less than 50%",
       "when": "overlap < 0.5",                  // expression over controls, outputs and sim_ metrics
       "solution": {"d": 1.4},                   // control values that satisfy it (others keep defaults)
       "hints": ["Which slider moves the groups apart?",              // 2–3 hints, each more specific than the last,
                 "Push d past 1 and watch the overlap box.",           // offered one at a time before Show me;
                 "The overlap crosses 50% somewhere between 1 and 2."]} // the last narrows it down but never states the solution's value
    ]
  },
  "understand": {
    "feedback": {"correct": "Why the right answer to the predict question is right", "incorrect": "What the learner probably assumed and why the idea says otherwise"},
    "walkthrough": {                             // REQUIRED: the idea taught on the model, 3–8 steps, played right after the tour
      "steps": [{"say": "Start with the groups on top of each other: overlap is 100%.", "set": {"d": 0}, "focus": "overlap", "ms": 2400}]
    },
    "explanation": "3–6 short sentences teaching the idea in plain words, building on the walkthrough the learner just watched: what happens, why, and what the paper did to show it. Keep scientific caveats.",
    "quote": "An exact, contiguous passage copied from the paper (6–80 words)",
    "quote_where": "Where it appears, e.g. 'Section 2' or 'Abstract'"
  },
  "check": { ...one CHECK FORMAT below... },     // ONLY for a concept marked hard; omit the key otherwise
  "connect": {
    "equation": [                                // the paper's (or the model's) equation, split into parts
      {"text": "overlap = 2Φ(−"}, {"text": "d", "link": "d"}, {"text": "/2)"}
    ],
    "caption": "How each coloured part maps to the model and to the paper's notation"
  },
  "recap": "One-line takeaway"
}

Equation text is plain Unicode (Φ, σ, μ, −, ×, ², √, ≈). Use _{...} for subscripts and ^{...} for superscripts, e.g. "μ_{1}" or "x^{2}".
A part with "link" is coloured and tied to that control or output.

EXPRESSIONS are strings in a small language: numbers, names, + - * / % ^ (power), comparisons < <= > >= == !=,
&& || ! (or and/or/not), cond ? a : b, and functions abs sqrt exp log ln log10 pow min max floor ceil round(x, digits)
clamp(x, lo, hi) sin cos tan atan atan2 erf normpdf(x, mu, sd) normcdf(x, mu, sd) norminv(p, mu, sd) binom(n, k)
logistic sign. Constants pi, e, true, false. Booleans are 1/0. Names are control ids, earlier output ids, and for
simulation visuals sim_<metric>. Inside a curves series the variable x is the horizontal coordinate.
== compares with a tiny tolerance; prefer ranges (abs(a - b) < 0.05) or inequalities in goals.

OUTPUT display: value × scale (default 1), shown with `decimals` (default 2) and `unit`.

VISUAL TYPES (every numeric field may be a number or an expression):

curves — how one quantity changes with another
  {"type": "curves", "x": {"label": "...", "min": -4, "max": 6}, "y": {"label": "...", "min": 0, "max": 0.45},
   "series": [{"id": "treated", "label": "Treated", "expr": "normpdf(x, d, 1)", "color": 0, "dashed": false}],   // "id" optional: lets a step point at it
   "fills": [{"series": 1, "from": "cutoff", "to": 6, "label": "Power", "color": 1}],   // shade under a series
   "markers": [{"x": "cutoff", "label": "Cut-off", "color": 3}],                         // vertical lines
   "hlines": [{"y": 0.5, "label": "..."}], "points": [{"x": "a", "y": "b", "label": "..."}]}   // markers, hlines and points take an "id" too

bars — quantities side by side
  {"type": "bars", "bars": [{"id": "treated_bar", "label": "Treated", "value": "mu1", "color": 1}], "min": 0, "max": 100, "unit": "%", "decimals": 0}

table — a grid that recolours as inputs change
  {"type": "table", "columns": ["Cooperate", "Defect"],
   "rows": [{"label": "Cooperate", "cells": ["r", {"value": "s", "highlight": "s > r"}]}],
   "decimals": 1, "scale": "sequential" | "diverging" | "none", "scale_min": 0, "scale_max": 10}

agents — many individuals following simple rules (kernel: schelling | sir | opinion)
  {"type": "agents", "kernel": "schelling", "params": {"tolerance": "tol", "density": 0.9}}

network — connected individuals (kernel: network)
  {"type": "network", "kernel": "network", "params": {"threshold": "t", "rewire": 0.1}}

causal — causes and effects with adjustable strengths
  {"type": "causal", "nodes": [{"id": "z", "label": "Wealth", "x": 50, "y": 15, "value": "..."}],   // x,y in 0–100
   "edges": [{"from": "z", "to": "t", "strength": "a", "label": "a"}]}                              // strength −1..1 drawn as thickness/sign

sampling — repeated random samples building up (kernel: mean | two_group | regression)
  {"type": "sampling", "kernel": "two_group", "params": {"mu2": "d", "n": "n"}}

geometry — shapes, vectors and transformations
  {"type": "geometry", "xmin": -5, "xmax": 5, "ymin": -5, "ymax": 5,
   "vectors": [{"x": "a", "y": "b", "from_x": 0, "from_y": 0, "label": "v", "color": 0}],
   "points": [...], "segments": [{"x1":..,"y1":..,"x2":..,"y2":.., "label": ".."}],
   "circles": [{"x":..,"y":..,"r":..}], "polygons": [{"points": [[0,0],["a",0],["a","b"]], "label": "..", "color": 2}]}

Colours are palette indices 0–7 (a colour-blind-safe palette). Give each control and output a "color" that matches
the part of the visual it drives, so the learner can see which slider moves what; equation terms take the same colour.

SIMULATION KERNELS (deterministic for a given seed; params not given take defaults; values are clamped to range):
{kernels}

CHECK FORMATS (only for hard concepts; every check has "hint" and "misconception" — the mistaken belief behind wrong answers):
  {"kind": "model", "task": "Put the model in a state where ...", "when": "<expression>", "solution": {...}, "hint": "...", "misconception": "..."}
      — preferred where possible. The model is reset to its defaults for the check, and `when` must be false
        there and at each explore goal's solution.
  {"kind": "choice", "question": "...", "options": [{"text": "...", "correct": true, "why": "..."}], "multi": false, ...}
      — multi: true for "select all that apply"
  {"kind": "truefalse", "statement": "...", "answer": true, "why": "...", ...}
  {"kind": "numeric", "question": "...", "answer": 0.8, "tolerance": 0.05, "unit": "", ...}
  {"kind": "order", "prompt": "Put these steps in order", "items": ["first", "second", "third"], ...}   // items in the correct order
"""


def kernel_docs() -> str:
    lines = []
    for name, spec in kernels.KERNELS.items():
        ps = ", ".join(f"{p} (default {d:g}, {lo:g}–{hi:g}{', integer' if i else ''})" for p, (d, lo, hi, i) in spec["params"].items() if p != "seed")
        ms = "; ".join(f"sim_{m}: {d}" for m, d in spec["metrics"].items())
        lines.append(f"  {name} [{spec['visual']}] — {spec['about']}\n    params: {ps}, seed\n    metrics: {ms}")
    return "\n".join(lines)


def schema_guide() -> str:
    return SCHEMA_GUIDE.replace("{kernels}", kernel_docs())
