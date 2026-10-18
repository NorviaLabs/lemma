/* Interactive teaching activities shared by the player and gallery. No network or generated code. */
(function (root) {
  "use strict";
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (key === "class") node.className = value;
      else node.setAttribute(key, value);
    }
    for (const child of children.flat()) if (child != null) node.append(typeof child === "string" ? document.createTextNode(child) : child);
    return node;
  }
  function svg(tag, attrs) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    return node;
  }
  const KINDS = ["sort", "construction", "inheritance", "worked", "compare", "stages", "match", "order", "trace", "passage", "estimate"];
  // A fixed shuffle, so the learner never sees the answer order but a revisit shows the same arrangement.
  function shuffled(items, seed) {
    let h = 2166136261;
    for (const ch of String(seed)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
    const out = items.map((x, i) => [x, i]);
    for (let i = out.length - 1; i > 0; i--) { h = Math.imul(h ^ (h >>> 15), 2246822507) >>> 0; const j = h % (i + 1); [out[i], out[j]] = [out[j], out[i]]; }
    if (out.length > 1 && out.every(([, i], k) => i === k)) out.push(out.shift());
    return out.map(([x]) => x);
  }
  // mount(container, activity, state, onComplete, env): env.renderModel(box, values) draws the concept's model in a
  // given state; env.sourceTitle(id) names a source. Both are optional.
  function mount(container, activity, state = {}, onComplete = () => {}, env = {}) {
    if (!KINDS.includes(activity.kind)) throw new Error(`Unsupported teaching activity: ${activity.kind}`);
    const box = el("section", { class: "activity-lab", "aria-label": activity.title || activity.prompt || activity.question || "Activity" });
    const status = el("p", { class: "activity-feedback", "aria-live": "polite" });
    if (activity.title) box.append(el("h3", {}, activity.title));
    if (activity.hypothetical) box.append(el("p", { class: "hypothetical-tag" }, "Hypothetical teaching case: made up to illustrate the idea, not evidence from the source."));
    if (activity.prompt || activity.question) box.append(el("p", { class: "activity-prompt" }, activity.prompt || activity.question));
    function complete(message) { state.done = true; status.textContent = message || ""; onComplete(); }
    // Hints get more specific, one at a time, before Show me.
    const hints = activity.hints || [];
    const hintList = el("ul", { class: "activity-hints" });
    function hintButton() {
      if (!hints.length) return null;
      const button = el("button", { type: "button", class: "ghost", onclick: () => {
        state.hints = Math.min((state.hints || 0) + 1, hints.length);
        drawHints();
      } }, "Hint");
      return button;
    }
    function drawHints() { hintList.replaceChildren(...hints.slice(0, state.hints || 0).map((t, i) => el("li", {}, `Hint ${i + 1}: ${t}`))); }
    drawHints();
    if (activity.kind === "sort") {
      const assignments = (state.assignments ||= {});
      const rows = activity.cards.map((card) => {
        const select = el("select", { "aria-label": `Classify: ${card.text}` },
          el("option", { value: "" }, "Choose a category"),
          activity.groups.map((g) => el("option", { value: g.id }, g.label)));
        select.value = assignments[card.id] || "";
        select.addEventListener("change", () => { assignments[card.id] = select.value; state.done = false; status.textContent = "Check the revised connections."; });
        const feedback = el("p", { class: "activity-card-feedback" });
        return { card, select, feedback, row: el("div", { class: "activity-card" }, el("p", {}, card.text), select, feedback) };
      });
      const check = () => {
        let correct = 0;
        rows.forEach(({ card, select, feedback }) => {
          const right = select.value === card.group;
          correct += right ? 1 : 0;
          feedback.textContent = !select.value ? "Choose a category first." : right ? card.feedback : "Reconsider the role this plays. " + card.feedback;
          feedback.dataset.result = right ? "correct" : "reconsider";
        });
        status.textContent = `${correct} of ${rows.length} placed with supporting reasons.`;
        if (correct === rows.length) complete(activity.takeaway);
      };
      box.append(el("div", { class: "activity-board" }, rows.map((r) => r.row)), hintList,
        el("div", { class: "actions" }, el("button", { type: "button", onclick: check }, "Check connections"), hintButton(),
          el("button", { type: "button", class: "ghost", onclick: () => {
            rows.forEach(({ card, select }) => { select.value = card.group; assignments[card.id] = card.group; });
            check();
          } }, "Show the connections")));
    } else if (activity.kind === "construction" && activity.steps) {
      const picture = svg("svg", { viewBox: "-5 -5 110 110", class: "construction-picture", role: "img", "aria-label": activity.title });
      const tools = el("div", { class: "activity-tools" });
      const draw = () => {
        const done = state.step || 0;
        picture.replaceChildren();
        activity.steps.slice(0, done).forEach((s, k) => s.shapes.forEach((sh) => {
          const cls = "construction-" + (sh.type === "line" ? "edge" : sh.type) + (k === done - 1 ? " latest" : "");
          if (sh.type === "circle") picture.append(svg("circle", { cx: sh.x, cy: sh.y, r: sh.r, class: cls }));
          else if (sh.type === "line") picture.append(svg("line", { x1: sh.x1, y1: sh.y1, x2: sh.x2, y2: sh.y2, class: cls }));
          else { picture.append(svg("circle", { cx: sh.x, cy: sh.y, r: 1.5, class: "construction-point" })); if (sh.label) { const t = svg("text", { x: sh.x + 2.5, y: sh.y - 2.5 }); t.textContent = sh.label; picture.append(t); } }
        }));
        tools.replaceChildren(...activity.steps.map((s, k) => el("button", { type: "button", "aria-pressed": String(k < done), ...(k === done ? {} : { disabled: "" }),
          onclick: () => { state.step = k + 1; draw(); if (state.step === activity.steps.length) complete(s.note + " " + activity.takeaway); else status.textContent = s.note; } }, s.label)),
          el("button", { type: "button", class: "ghost", onclick: () => { state.step = 0; state.done = false; draw(); status.textContent = ""; } }, "Reset"));
      };
      box.append(picture, tools); draw();
    } else if (activity.kind === "construction") {
      const picture = svg("svg", { viewBox: "-25 25 370 270", role: "img", "aria-label": "Segment AB and construction of an equilateral triangle" });
      const controls = el("div", { class: "activity-tools" });
      const draw = () => {
        picture.replaceChildren();
        if (state.first) picture.append(svg("circle", { cx: 100, cy: 160, r: 120, class: "construction-circle" }));
        if (state.second) picture.append(svg("circle", { cx: 220, cy: 160, r: 120, class: "construction-circle second" }));
        picture.append(svg("line", { x1: 100, y1: 160, x2: 220, y2: 160, class: "construction-edge" }));
        if (state.joined) picture.append(svg("path", { d: "M100 160 L160 56.077 L220 160", class: "construction-edge", fill: "none" }));
        for (const [name,x,y] of [["A",100,160],["B",220,160],...(state.joined ? [["C",160,56.077]] : [])]) {
          picture.append(svg("circle", { cx:x, cy:y, r:4, class:"construction-point" }));
          const label=svg("text",{x:x+8,y:y-8}); label.textContent=name; picture.append(label);
        }
        controls.replaceChildren(
          el("button", { type:"button", "aria-pressed":String(!!state.first), onclick:()=>{ state.first=true; draw(); status.textContent="Circle centered at A: every point on it is AB from A."; } }, "Draw circle: center A, radius AB"),
          el("button", { type:"button", "aria-pressed":String(!!state.second), onclick:()=>{ state.second=true; draw(); status.textContent="Circle centered at B: every point on it is BA from B."; } }, "Draw circle: center B, radius BA"),
          el("button", { type:"button", ...(state.first && state.second ? {} : {disabled:""}), onclick:()=>{ state.joined=true; draw(); complete("AC and AB are radii of the first circle; BC and BA are radii of the second. All three sides equal the given segment—not because they look equal."); } }, "Choose the upper intersection and join C to A and B"),
          el("button", { type:"button", class:"ghost", onclick:()=>{ state.first=false;state.second=false;state.joined=false;state.done=false;draw();status.textContent="Start again with the given segment AB."; } }, "Reset"));
      };
      box.append(picture,controls); draw();
    } else if (activity.kind === "inheritance") {
      const grid=el("div",{class:"inheritance-grid"});
      const output=el("p",{class:"inheritance-result","aria-live":"polite"});
      const counts=(state.counts ||= {round:0,wrinkled:0});
      const genotype=el("select",{"aria-label":"Genotype of first parent"},["AA","Aa","aa"].map((v)=>el("option",{value:v},v)));
      genotype.value=state.parent || activity.parent || "Aa";
      const second=activity.second || "Aa";
      const draw=()=>{
        const first=genotype.value; state.parent=first;
        grid.replaceChildren();
        for(const a of first) for(const b of second) {
          const code=[a,b].sort().join("");
          const round=code!=="aa";
          const cell=el("button",{type:"button",class:`inheritance-seed ${round?"round":"wrinkled"}`,onclick:()=>{
            state.inspected=true;
            status.textContent=`${a} from the first parent and ${b} from the second make ${code}: ${round?"round":"wrinkled"}. Each cell is one equally likely combination in this teaching model.`;
            onComplete();
          }},el("strong",{},code),el("span",{},round?"Round":"Wrinkled"));
          grid.append(cell);
        }
        const roundCells=[...first].flatMap((a)=>[...second].map((b)=>a!=="a"||b!=="a")).filter(Boolean).length;
        output.textContent=`Expected round: ${roundCells} of 4 combinations. Observed in your simulated sample: ${counts.round} round, ${counts.wrinkled} wrinkled.`;
      };
      genotype.addEventListener("change",()=>{counts.round=0;counts.wrinkled=0;state.done=false;draw();status.textContent="The first parent changed. Inspect the new combinations before sampling.";});
      box.append(el("p",{class:"note"},"Hypothetical teaching model: modern A/a notation, equal independent contributions, complete dominance. These are not Mendel’s observed seeds."),
        el("label",{},"First parent ",genotype,` × second parent ${second}`),grid,output,
        el("button",{type:"button",onclick:()=>{
          for(let i=0;i<20;i++) {
            const a=genotype.value[Math.floor(Math.random()*2)],b=second[Math.floor(Math.random()*2)];
            counts[a==="a"&&b==="a"?"wrinkled":"round"]++;
          }
          draw(); complete("A ratio describes expected outcomes, not a fixed batch. Changing the first parent changes the possible combinations; finite samples fluctuate.");
        }},"Grow 20 simulated offspring")); draw();
    } else if (activity.kind === "worked" || activity.kind === "stages") {
      // A worked example shows each step in turn; staged evidence reveals one stage at a time.
      const items = activity.kind === "worked" ? activity.steps : activity.stages;
      const list = el("ol", { class: activity.kind === "worked" ? "worked-steps" : "evidence-stages" });
      const next = el("button", { type: "button" });
      const draw = () => {
        const shown = (state.shown ||= 1);
        list.replaceChildren(...items.slice(0, shown).map((s) => el("li", {},
          s.label ? el("strong", {}, s.label + ": ") : null, s.text, s.result ? el("span", { class: "step-result" }, " → " + s.result) : null)));
        if (shown >= items.length) { next.setAttribute("disabled", ""); next.textContent = "All shown"; if (!state.done) complete(activity.takeaway); else status.textContent = activity.takeaway; }
        else next.textContent = activity.kind === "worked" ? "Next step" : `Reveal: ${items[shown].label}`;
      };
      next.addEventListener("click", () => { state.shown = Math.min((state.shown || 1) + 1, items.length); draw(); });
      box.append(list, el("div", { class: "actions" }, next)); draw();
    } else if (activity.kind === "compare") {
      const grid = el("div", { class: "compare-grid" });
      for (const c of activity.cases) {
        const panel = el("div", { class: "compare-case" }, el("h4", {}, c.label));
        if (c.values && env.renderModel) { const view = el("div", { class: "compare-model" }); panel.append(view); env.renderModel(view, c.values); }
        else if (c.values) panel.append(el("p", {}, Object.entries(c.values).map(([k, v]) => `${k} = ${v}`).join(", ")));
        if (c.text) panel.append(el("p", {}, c.text));
        grid.append(panel);
      }
      box.append(grid, el("div", { class: "actions" }, el("button", { type: "button", onclick: () => complete(activity.takeaway) }, "What the comparison shows")));
      if (state.done) status.textContent = activity.takeaway;
    } else if (activity.kind === "match") {
      const targets = shuffled(activity.pairs.map((p) => p.target), activity.id);
      const picks = (state.picks ||= {});
      const rows = activity.pairs.map((p) => {
        const select = el("select", { "aria-label": `Match: ${p.text}` }, el("option", { value: "" }, "Choose a match"), targets.map((t) => el("option", { value: t }, t)));
        select.value = picks[p.id] || "";
        select.addEventListener("change", () => { picks[p.id] = select.value; state.done = false; });
        const feedback = el("p", { class: "activity-card-feedback" });
        return { p, select, feedback, row: el("div", { class: "activity-card" }, el("p", {}, p.text), select, feedback) };
      });
      const check = () => {
        let right = 0;
        rows.forEach(({ p, select, feedback }) => {
          const ok = select.value === p.target; right += ok ? 1 : 0;
          feedback.textContent = !select.value ? "Choose a match first." : ok ? p.feedback : "Not this one. Look again at what each side says.";
          feedback.dataset.result = ok ? "correct" : "reconsider";
        });
        status.textContent = `${right} of ${rows.length} matched.`;
        if (right === rows.length) complete(activity.takeaway);
      };
      box.append(el("div", { class: "activity-board" }, rows.map((r) => r.row)), hintList,
        el("div", { class: "actions" }, el("button", { type: "button", onclick: check }, "Check matches"), hintButton(),
          el("button", { type: "button", class: "ghost", onclick: () => { rows.forEach(({ p, select }) => { select.value = p.target; picks[p.id] = p.target; }); check(); } }, "Show me")));
    } else if (activity.kind === "order") {
      const order = (state.order ||= shuffled(activity.items, activity.id));
      const list = el("ol", { class: "order-list" });
      const draw = () => list.replaceChildren(...order.map((item, i) => el("li", { class: "order-item" }, el("span", {}, item),
        el("span", { class: "order-btns" },
          el("button", { type: "button", class: "small order-btn", "aria-label": `Move “${item}” up`, ...(i === 0 ? { disabled: "" } : {}), onclick: () => { [order[i - 1], order[i]] = [order[i], order[i - 1]]; state.done = false; draw(); } }, "↑"),
          el("button", { type: "button", class: "small order-btn", "aria-label": `Move “${item}” down`, ...(i === order.length - 1 ? { disabled: "" } : {}), onclick: () => { [order[i + 1], order[i]] = [order[i], order[i + 1]]; state.done = false; draw(); } }, "↓")))));
      const check = () => {
        const placed = order.filter((x, i) => x === activity.items[i]).length;
        if (placed === order.length) complete(activity.explanation);
        else status.textContent = `${placed} of ${order.length} in the right place. Not yet: think about what each step needs from the one before.`;
      };
      draw();
      box.append(list, hintList, el("div", { class: "actions" }, el("button", { type: "button", onclick: check }, "Check order"), hintButton(),
        el("button", { type: "button", class: "ghost", onclick: () => { order.splice(0, order.length, ...activity.items); draw(); check(); } }, "Show me")));
    } else if (activity.kind === "trace") {
      const picked = (state.picked ||= []);
      const pos = Object.fromEntries(activity.nodes.map((n) => [n.id, n]));
      const picture = svg("svg", { viewBox: "-8 -8 116 116", class: "trace-diagram", role: "group", "aria-label": activity.prompt });
      const draw = () => {
        picture.replaceChildren();
        for (const e of activity.edges || []) {
          const a = pos[e.from], b = pos[e.to];
          picture.append(svg("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: "trace-edge" + (picked.includes(e.from) && picked.includes(e.to) ? " on" : "") }));
        }
        for (const n of activity.nodes) {
          const at = picked.indexOf(n.id);
          const node = svg("g", { class: "trace-node" + (at >= 0 ? " on" : ""), role: "button", tabindex: "0", "aria-pressed": String(at >= 0), "aria-label": n.label + (at >= 0 ? `, selected ${at + 1}` : "") });
          const toggle = () => { at >= 0 ? picked.splice(at, 1) : picked.push(n.id); state.done = false; draw(); };
          node.addEventListener("click", toggle);
          node.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault?.(); toggle(); } });
          const label = svg("text", { x: n.x, y: n.y + 10, "text-anchor": "middle" }); label.textContent = n.label;
          node.append(svg("circle", { cx: n.x, cy: n.y, r: 4.5 }), label);
          if (at >= 0 && activity.path) { const k = svg("text", { x: n.x, y: n.y + 1.4, "text-anchor": "middle", class: "trace-order" }); k.textContent = String(at + 1); node.append(k); }
          picture.append(node);
        }
      };
      const check = () => {
        const ok = activity.path ? picked.length === activity.answer.length && picked.every((x, i) => x === activity.answer[i])
          : picked.length === activity.answer.length && activity.answer.every((x) => picked.includes(x));
        if (ok) complete(activity.explanation);
        else status.textContent = activity.path ? "Not yet. Follow the links from the start, one step at a time." : "Not yet. Check each one you picked, and any you left out.";
      };
      draw();
      box.append(picture, hintList, el("div", { class: "actions" }, el("button", { type: "button", onclick: check }, "Check"), hintButton(),
        el("button", { type: "button", class: "ghost", onclick: () => { picked.splice(0, picked.length, ...activity.answer); draw(); check(); } }, "Show me"),
        el("button", { type: "button", class: "ghost", onclick: () => { picked.splice(0); state.done = false; draw(); status.textContent = ""; } }, "Clear")));
    } else if (activity.kind === "passage") {
      const options = activity.options.map((o, i) => {
        const input = el("input", { type: "radio", name: `passage-${activity.id}`, value: String(i) });
        input.checked = state.selected === i;
        input.addEventListener("change", () => { state.selected = i; state.done = false; });
        const from = o.source_id && env.sourceTitle ? env.sourceTitle(o.source_id) : "";
        return el("label", { class: "option passage-option" }, input, el("blockquote", {}, `“${o.quote}”`, from ? el("cite", {}, from) : null));
      });
      const check = () => {
        if (state.selected == null) { status.textContent = "Choose a passage first."; return; }
        const o = activity.options[state.selected];
        if (state.selected === activity.answer) complete(o.feedback);
        else status.textContent = "Not this one. " + o.feedback;
      };
      box.append(el("div", { class: "options", role: "radiogroup" }, options), hintList,
        el("div", { class: "actions" }, el("button", { type: "button", onclick: check }, "Check"), hintButton(),
          el("button", { type: "button", class: "ghost", onclick: () => { state.selected = activity.answer; options.forEach((o, i) => (o.children[0].checked = i === activity.answer)); check(); } }, "Show me")));
    } else if (activity.kind === "estimate") {
      const input = el("input", { type: "number", step: "any", "aria-label": activity.question });
      input.value = state.value ?? "";
      input.addEventListener("input", () => { state.value = input.value; state.done = false; });
      const check = () => {
        const v = parseFloat(input.value);
        if (!Number.isFinite(v)) { status.textContent = "Enter a number first."; return; }
        if (Math.abs(v - activity.answer) <= activity.tolerance + 1e-12) complete(activity.explanation);
        else status.textContent = `Not yet: ${v > activity.answer ? "too high" : "too low"}.`;
      };
      box.append(el("div", { class: "num-row" }, input, activity.unit ? el("span", {}, activity.unit) : null), hintList,
        el("div", { class: "actions" }, el("button", { type: "button", onclick: check }, "Check"), hintButton(),
          el("button", { type: "button", class: "ghost", onclick: () => { input.value = String(activity.answer); state.value = input.value; check(); } }, "Show me")));
    }
    box.append(status); container.append(box);
    if(state.done) status.textContent=activity.takeaway || "You can keep exploring or continue.";
    return box;
  }
  root.LemmaActivities={mount, shuffled, KINDS};
})(typeof window !== "undefined" ? window : globalThis);
