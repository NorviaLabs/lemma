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
  function mount(container, activity, state = {}, onComplete = () => {}) {
    if (!["sort", "construction", "inheritance"].includes(activity.kind)) throw new Error(`Unsupported teaching activity: ${activity.kind}`);
    const box = el("section", { class: "activity-lab", "aria-label": activity.title });
    const status = el("p", { class: "activity-feedback", "aria-live": "polite" });
    box.append(el("h3", {}, activity.title), el("p", { class: "activity-prompt" }, activity.prompt));
    function complete(message) { state.done = true; status.textContent = message; onComplete(); }
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
      box.append(el("div", { class: "activity-board" }, rows.map((r) => r.row)),
        el("div", { class: "actions" }, el("button", { type: "button", onclick: check }, "Check connections"),
          el("button", { type: "button", class: "ghost", onclick: () => {
            rows.forEach(({ card, select }) => { select.value = card.group; assignments[card.id] = card.group; });
            check();
          } }, "Show the connections")));
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
      const draw=()=>{
        const first=genotype.value,second="Aa"; state.parent=first;
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
        el("label",{},"First parent ",genotype," × second parent Aa"),grid,output,
        el("button",{type:"button",onclick:()=>{
          for(let i=0;i<20;i++) {
            const a=genotype.value[Math.floor(Math.random()*2)],b="Aa"[Math.floor(Math.random()*2)];
            counts[a==="a"&&b==="a"?"wrinkled":"round"]++;
          }
          draw(); complete("A ratio describes expected outcomes, not a fixed batch. Changing the first parent changes the possible combinations; finite samples fluctuate.");
        }},"Grow 20 simulated offspring")); draw();
    }
    box.append(status); container.append(box);
    if(state.done) status.textContent=activity.takeaway || "You can keep exploring or continue.";
    return box;
  }
  root.LemmaActivities={mount};
})(typeof window !== "undefined" ? window : globalThis);
