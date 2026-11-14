// Run with node tests/model_trace.js (tests/test_model_trace.py runs it). A trace on the concept's own causal model
// (`"on": "model"`), exercised through activities.js's real handlers on a stand-in page. The player draws the copy of
// the model: env.renderDiagram(box, values) puts it in `box` and returns { nodes: { id: { el, label, x, y } },
// edges: [{ from, to, el }] }, or fails. Each case prints "PASS <name>" or "FAIL <name> :: <why>", and runs on its own.
const assert = require("node:assert/strict");

class Node {
  constructor(tag) { this.tagName = tag; this.children = []; this.attrs = {}; this.events = {}; this.value = ""; this.dataset = {}; this.textContent = ""; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  hasAttribute(k) { return k in this.attrs; }
  addEventListener(k, v) { this.events[k] = v; }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(n) { this.children.push(n); return n; }
  replaceChildren(...nodes) { this.children = nodes; }
}
global.document = { createElement: (t) => new Node(t), createElementNS: (_, t) => new Node(t), createTextNode: (t) => ({ textContent: t }) };
require("../lemma/static/activities.js");

// ------------------------------------------------------------ helpers
const all = (n, pred) => [...(n && n.tagName && pred(n) ? [n] : []), ...((n && n.children) || []).flatMap((c) => all(c, pred))];
const text = (n) => (n.children && n.children.length ? n.children.map(text).join("") : n.textContent || "");
const button = (root, label) => all(root, (n) => n.tagName === "button").find((b) => text(b) === label);
const click = (n) => { assert.ok(n, "the element exists"); n.events.click({ preventDefault() {} }); };
const classes = (n) => (n.getAttribute("class") || n.className || "").split(/\s+/).filter(Boolean);
const status = (root) => all(root, (n) => classes(n).includes("activity-feedback"))[0].textContent;

// The ice–albedo loop's causal model, as the player's copy of it presents it.
const NODES = [["push", "First push (°C)"], ["temp", "Planet warms (°C)"], ["ice", "Ice cover"], ["reflect", "Sunlight bounced away"], ["absorb", "Sunlight soaked up"]];
const EDGES = [["push", "temp"], ["temp", "ice"], ["ice", "reflect"], ["reflect", "absorb"], ["absorb", "temp"]];
const label = (id) => NODES.find(([k]) => k === id)[1];
const PATH = {
  id: "loop", kind: "trace", on: "model", path: true, prompt: "Starting from the warming, trace the loop until it feeds back into warming.",
  answer: ["temp", "ice", "reflect", "absorb"], explanation: "Warming shrinks the ice, which bounces back less sunlight, so more is soaked up.",
  hints: ["Start at the warming.", "Ice comes next."],
};
const SET = { ...PATH, id: "parts", path: false, prompt: "Pick the two kinds of sunlight.", answer: ["reflect", "absorb"], values: { hold: 1 }, explanation: "Sunlight is either bounced away or soaked up.", hints: undefined };

// A stand-in for the player's drawing: records what it was asked to draw, and hands back the nodes and links it drew.
function diagram() {
  const calls = [], drawn = { nodes: {}, edges: [] };
  const renderDiagram = (box, values) => {
    calls.push(values);
    const pic = new Node("svg");
    pic.setAttribute("class", "viz");
    NODES.forEach(([id, name], i) => {
      const g = new Node("g");
      g.setAttribute("class", "cnode-g");
      g.setAttribute("data-node", id);
      const rect = new Node("rect"); rect.setAttribute("class", "cnode");
      const t = new Node("text"); t.setAttribute("class", "cnode-label"); t.textContent = name;
      g.append(rect, t);
      pic.append(g);
      drawn.nodes[id] = { el: g, label: name, x: 100 + i * 100, y: 50 };
    });
    for (const [from, to] of EDGES) {
      const line = new Node("line");
      line.setAttribute("class", "cedge pos");
      pic.append(line);
      drawn.edges.push({ from, to, el: line });
    }
    box.append(pic);
    return drawn;
  };
  return { calls, drawn, renderDiagram };
}

function mount(activity, { state = {}, env } = {}) {
  const d = diagram();
  const root = new Node("main");
  let completions = 0;
  LemmaActivities.mount(root, activity, state, () => completions++, env || { renderDiagram: d.renderDiagram });
  const node = (id) => d.drawn.nodes[id].el;
  const edge = (from, to) => d.drawn.edges.find((e) => e.from === from && e.to === to).el;
  const picked = () => NODES.map(([id]) => id).filter((id) => node(id).getAttribute("aria-pressed") === "true");
  const badge = (id) => all(node(id), (n) => classes(n).includes("trace-order")).map((n) => n.textContent).join("");
  return { root, state, d, node, edge, picked, badge, done: () => completions };
}
const pick = (m, ...ids) => ids.forEach((id) => click(m.node(id)));

// ------------------------------------------------------------ cases
const cases = {
  "27 draws the copy with the block's values": () => {
    const m = mount(SET);
    assert.deepEqual(m.d.calls, [{ hold: 1 }]);
    assert.ok(all(m.root, (n) => n.tagName === "svg").length >= 1, "the copy is inside the activity");
  },
  "27 draws the copy in the model's defaults when the block gives none": () => {
    const m = mount(PATH);
    assert.deepEqual(m.d.calls, [{}]);  // no values: the player draws the model's defaults
  },
  "28 every model node is a pickable button, and nothing else is": () => {
    const m = mount(PATH);
    for (const [id] of NODES) {
      assert.equal(m.node(id).getAttribute("role"), "button", id);
      assert.equal(m.node(id).getAttribute("tabindex"), "0", id);
      assert.equal(typeof m.node(id).events.click, "function", id);
      assert.equal(typeof m.node(id).events.keydown, "function", id);
    }
    assert.equal(all(m.root, (n) => n.getAttribute && n.getAttribute("role") === "button").length, NODES.length);
    for (const { el } of m.d.drawn.edges) assert.equal(el.events.click, undefined);
  },
  "29 clicking picks a node and clicking again unpicks it": () => {
    const m = mount(PATH);
    pick(m, "ice");
    assert.deepEqual(m.state.picked, ["ice"]);
    assert.ok(classes(m.node("ice")).includes("picked"));
    assert.ok(classes(m.node("ice")).includes("cnode-g"), "keeps its own class");
    pick(m, "ice");
    assert.deepEqual(m.state.picked, []);
    assert.ok(!classes(m.node("ice")).includes("picked"));
  },
  "30 Enter and Space pick with the default prevented; other keys do nothing": () => {
    const m = mount(PATH);
    let prevented = 0;
    const key = (id, k) => m.node(id).events.keydown({ key: k, preventDefault: () => prevented++ });
    key("temp", "Enter");
    key("ice", " ");
    assert.deepEqual(m.state.picked, ["temp", "ice"]);
    assert.equal(prevented, 2);
    key("reflect", "a"); key("reflect", "Tab"); key("reflect", "ArrowRight");
    assert.deepEqual(m.state.picked, ["temp", "ice"]);
    assert.equal(prevented, 2);
  },
  "31 aria-pressed follows the pick and the name says its place": () => {
    const m = mount(PATH);
    assert.equal(m.node("temp").getAttribute("aria-pressed"), "false");
    assert.equal(m.node("temp").getAttribute("aria-label"), label("temp"));
    pick(m, "temp", "ice");
    assert.equal(m.node("temp").getAttribute("aria-pressed"), "true");
    assert.equal(m.node("ice").getAttribute("aria-label"), `${label("ice")}, selected 2`);
    pick(m, "temp");
    assert.equal(m.node("ice").getAttribute("aria-label"), `${label("ice")}, selected 1`);
    assert.equal(m.node("temp").getAttribute("aria-label"), label("temp"));
  },
  "32 a path shows order numbers on picked nodes": () => {
    const m = mount(PATH);
    pick(m, "ice", "reflect");
    assert.equal(m.badge("ice"), "1");
    assert.equal(m.badge("reflect"), "2");
    assert.equal(m.badge("temp"), "");
    pick(m, "ice");
    assert.equal(m.badge("reflect"), "1");
    assert.equal(m.badge("ice"), "");
  },
  "32 a set shows no order numbers": () => {
    const m = mount(SET);
    pick(m, "reflect", "absorb");
    assert.deepEqual(m.picked(), ["reflect", "absorb"]);
    assert.equal(m.badge("reflect") + m.badge("absorb"), "");
  },
  "33 links between picked nodes are highlighted": () => {
    const m = mount(PATH);
    pick(m, "temp", "ice");
    assert.ok(classes(m.edge("temp", "ice")).includes("picked"));
    assert.ok(classes(m.edge("temp", "ice")).includes("cedge"), "keeps its own class");
    assert.ok(!classes(m.edge("ice", "reflect")).includes("picked"));
    pick(m, "ice");
    assert.ok(!classes(m.edge("temp", "ice")).includes("picked"));
  },
  "34 a set: a wrong set is not yet, the right set in any order completes": () => {
    const m = mount(SET);
    pick(m, "absorb");  // one left out
    click(button(m.root, "Check"));
    assert.equal(m.done(), 0);
    assert.equal(status(m.root), "Not yet. Check each one you picked, and any you left out.");
    pick(m, "ice");  // one too many
    click(button(m.root, "Check"));
    assert.equal(m.done(), 0);
    pick(m, "ice", "reflect");  // unpick ice, add reflect: the answer, in the other order from its key
    assert.deepEqual(m.state.picked, ["absorb", "reflect"]);
    click(button(m.root, "Check"));
    assert.equal(m.done(), 1);
    assert.equal(m.state.done, true);
    assert.equal(status(m.root), SET.explanation);
  },
  "35 a path: the wrong order is not yet, the right order completes": () => {
    const m = mount(PATH);
    pick(m, "ice", "temp", "reflect", "absorb");
    click(button(m.root, "Check"));
    assert.equal(m.done(), 0);
    assert.equal(status(m.root), "Not yet. Follow the links from the start, one step at a time.");
    click(button(m.root, "Clear"));
    pick(m, "temp", "ice", "reflect", "absorb");
    click(button(m.root, "Check"));
    assert.equal(m.done(), 1);
    assert.equal(status(m.root), PATH.explanation);
  },
  "36 Show me picks the answer, marks it and completes": () => {
    const m = mount(PATH);
    pick(m, "push");
    click(button(m.root, "Show me"));
    assert.deepEqual(m.state.picked, PATH.answer);
    assert.deepEqual(m.picked(), ["temp", "ice", "reflect", "absorb"]);
    assert.equal(m.badge("absorb"), "4");
    assert.equal(m.done(), 1);
    assert.equal(status(m.root), PATH.explanation);
  },
  "37 Clear empties the picks, resets done and the status": () => {
    const m = mount(PATH);
    click(button(m.root, "Show me"));
    click(button(m.root, "Clear"));
    assert.deepEqual(m.state.picked, []);
    assert.deepEqual(m.picked(), []);
    assert.equal(m.state.done, false);
    assert.equal(status(m.root), "");
    assert.ok(!classes(m.edge("temp", "ice")).includes("picked"));
  },
  "38 Hint shows the hints one at a time": () => {
    const m = mount(PATH);
    const shown = () => all(m.root, (n) => n.tagName === "li").map(text);
    assert.deepEqual(shown(), []);
    click(button(m.root, "Hint"));
    assert.deepEqual(shown(), ["Hint 1: Start at the warming."]);
    click(button(m.root, "Hint"));
    click(button(m.root, "Hint"));
    assert.deepEqual(shown(), ["Hint 1: Start at the warming.", "Hint 2: Ice comes next."]);
    assert.equal(button(mount(SET).root, "Hint"), undefined, "no hints, no Hint button");
  },
  "39 changing a pick after completing resets done": () => {
    const m = mount(PATH);
    click(button(m.root, "Show me"));
    assert.equal(m.state.done, true);
    pick(m, "push");
    assert.equal(m.state.done, false);
  },
  "40 coming back restores the picks and their marks": () => {
    const first = mount(PATH);
    pick(first, "temp", "ice");
    const again = mount(PATH, { state: first.state });
    assert.deepEqual(again.picked(), ["temp", "ice"]);
    assert.equal(again.badge("ice"), "2");
    assert.equal(again.node("ice").getAttribute("aria-label"), `${label("ice")}, selected 2`);
    assert.ok(classes(again.edge("temp", "ice")).includes("picked"));
  },
  "H3 without a way to draw the model, an error and nothing to pick": () => {
    const m = mount(PATH, { env: {} });
    const errors = all(m.root, (n) => classes(n).includes("activity-error"));
    assert.equal(errors.length, 1);
    assert.equal(errors[0].getAttribute("role"), "alert");
    assert.match(text(errors[0]), /couldn't be drawn/);
    assert.equal(all(m.root, (n) => n.tagName === "button").length, 0);
    assert.equal(m.done(), 0);
  },
  "H3 when the drawing fails, an error and nothing to pick": () => {
    for (const renderDiagram of [() => null, () => { throw new Error("no picture"); }]) {
      const m = mount(PATH, { env: { renderDiagram } });
      assert.equal(all(m.root, (n) => classes(n).includes("activity-error")).length, 1);
      assert.equal(all(m.root, (n) => n.tagName === "button").length, 0);
    }
  },
  "10 an authored trace keeps its node elements when a pick is made": () => {
    // Redrawing new elements would drop keyboard focus from the node just picked.
    const a = { kind: "trace", id: "chain", prompt: "Trace it.", path: true, answer: ["a", "b", "c"], explanation: "Each step is one link.",
      nodes: [{ id: "a", label: "A", x: 10, y: 50 }, { id: "b", label: "B", x: 50, y: 50 }, { id: "c", label: "C", x: 90, y: 50 }],
      edges: [{ from: "a", to: "b" }, { from: "b", to: "c" }] };
    const root = new Node("main"), state = {};
    LemmaActivities.mount(root, a, state, () => {}, {});
    const nodes = () => all(root, (n) => classes(n).includes("trace-node"));
    const before = nodes();
    before[0].events.keydown({ key: "Enter", preventDefault() {} });
    before[1].events.click();
    const after = nodes();
    assert.equal(after.length, 3);
    after.forEach((n, i) => assert.ok(n === before[i], `node ${i} is the same element`));
    assert.equal(after[1].getAttribute("aria-label"), "B, selected 2");
    assert.deepEqual(state.picked, ["a", "b"]);
  },
};

let failed = 0;
for (const [name, run] of Object.entries(cases)) {
  try {
    run();
    console.log(`PASS ${name}`);
  } catch (e) {
    failed++;
    console.log(`FAIL ${name} :: ${String(e && e.message || e).split("\n")[0]}`);
  }
}
process.exitCode = failed ? 1 : 0;
