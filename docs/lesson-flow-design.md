# Concept-specific lesson flows — design proposal

Status: design proposal, partly implemented: the activity blocks, their checks and plan selection with Jev exist (see Current support and gaps); the gallery has not been rebuilt with them. The gallery contains eighteen playable lessons using shared activity sequences, and the mappings below cover all of them: 93 concepts. The first six lessons (31 concepts) shaped the proposal; the other twelve (62 concepts) test it against history, theology, law, fiction, proof, and six multi-source lessons built to widen subject coverage. Automatic activity selection and the fuller interaction vocabulary remain proposed. These mappings are design hypotheses, not evidence of improved learning.

## Goal and agreed boundaries

Help learners internalize complex concepts by choosing activities that fit the reasoning involved, rather than requiring every concept to have a live model.

- Choose activities automatically per concept; a lesson can mix activities. Subject categories provide context, not fixed templates.
- Use structured responses only. Generate feedback during lesson creation; no AI grading or network calls during learning.
- Models, equations, numerical targets, and narrated model tours are optional.
- Initial judgments are optional, unscored, and used only when the learner has enough context. Do not require uninformed guesses.
- Determinate tasks offer correction, retry, hints, and Show me. Interpretive tasks explain supported positions and their limits without requiring agreement with a preferred interpretation.
- Interpretive tasks still correct factual mistakes, misattributions, and claims unsupported by the supplied evidence.
- Allow clearly labelled hypothetical teaching cases. Never fabricate evidence, quotations, findings, or attributed beliefs.
- Preserve source grounding, accessible interaction, and offline export.

## Design choice

Two approaches are plausible:

1. **Fixed flow families:** choose a mechanism lab, worked comparison, counterexample, or evidence investigation, each with a fixed sequence. This is easier to constrain but risks replacing one forced template with several. Gettier alone needs classification, deduction, staged revelation, and interpretation.
2. **Bounded activity sequences (recommended):** compose a short linear sequence from supported teaching and response blocks. Use a few example sequences as generation guidance, not mandatory templates. No arbitrary branching graphs or generated executable UI.

Keep a common shell: concept orientation, readable source references, Back/Continue, progress, feedback, and a concise takeaway. Do not require the same named stages or screen count for every concept. A live model is an optional resource reused across screens, not the conceptual center of every screen.

Planning order: source passages → learning objective → likely misconception → suitable activity → presentation and feedback. Do not start by choosing a chart.

## Activity vocabulary

Teaching blocks can explain a worked example, compare cases, reveal evidence in stages, or demonstrate a model. Response blocks use a small set of structured controls:

- Select one or several options: predictions, warranted claims, premises, or competing interpretations.
- Classify or match items: evidence to claims, steps to roles, cases to conditions. Provide click/keyboard alternatives; do not require dragging.
- Order a sequence where order matters: a calculation, argument, mechanism, or chronology.
- Select nodes, links, or spans from an authored set: trace information or identify a supporting passage. No arbitrary free-text selection is needed initially.
- Manipulate a model where the controls represent meaningful quantities or discrete states.

The learning activity is distinct from its control: multiple choice can ask for rote recall or substantive evidence comparison. A new task name alone does not improve teaching. Existing numeric-answer checks may remain, but new activities must not require written explanations.

Start with existing choice, ordering, and model controls where sufficient. Matching and tracing need dedicated support if the prototype shows choices cannot represent them clearly. Do not disguise categories as continuous sliders.

## Proposed gallery paths

Each numbered item below maps to an existing concept. It describes the central learning move, not an obligatory extra quiz after every screen. Reuse representations and combine repetitive exposition where appropriate.

### Galton: regression to the mean

Source: `lemma/examples/gallery/galton-1886.json`.

1. **One number for two parents:** demonstrate the mid-parent calculation; compare different couples with the same mid-parent and select what the summary retains and loses. Retain the height model.
2. **Children are two-thirds as unusual:** explore above- and below-average parents; predict a new expected deviation, then inspect the line. Distinguish the average prediction from an individual child's height.
3. **Where regression comes from:** select extreme first measurements in paired simulated data; compare the same group's second measurements at different correlations; select the explanation. Transfer to a labelled non-heredity example so regression is not learned as a biological shrinking force.

Keep most existing models. Avoid repeating a full control tour when a representation is already familiar.

### Ioannidis: false research findings

Source: `lemma/examples/gallery/ioannidis-2005.json`.

1. **False alarms and power:** teach a worked true/false-effect example; classify outcomes as hits, misses, false alarms, or correct negatives. Simulation can demonstrate frequencies, not replace the distinctions.
2. **Count a whole field:** populate or match counts in a 2×2 table, then compare the composition of significant findings. Use a clearly labelled hypothetical field.
3. **PPV and prior odds:** compare two fields with the same significance threshold but different prior odds; predict which produces more reliable positive findings. Reveal the counts before optionally connecting them to the formula.
4. **Bias:** compare transparent before/after reporting scenarios; identify which changes add misleading findings. Retain the quantitative model to show the consequences under its stated assumptions.
5. **Many teams:** reveal a selected positive result, then the other teams' outcomes; identify the selection problem. Explicitly distinguish 'at least one positive among many tests' from independent replication evidence that consistently supports a result.

Retain the counting mathematics; reduce repeated slider-target exercises.

### Attention Is All You Need

Source: `lemma/examples/gallery/attention-2017.json`.

1. **Weighted average:** trace scores → weights → weighted values using a small labelled numerical example; predict how raising one score changes competing weights. Remove mastery targets based on an invented living-thing score.
2. **Scaling by √d_k:** compare weights with and without scaling as dimension changes; identify which distribution becomes saturated. Explain the learning implication, but do not treat a proxy 'room to learn' score as measured training performance.
3. **Multiple heads:** compare an illustrative single-head and multi-head diagram; match distinct relations to the heads shown and identify what concatenation preserves. Make clear that assigned relations illustrate capacity, not guaranteed learned specialization.
4. **Position encoding:** first compare reordered tokens to establish the need for position information; then explore single-wave ambiguity versus multiple wave pairs. Retain the wave model, with clear limits rather than an unqualified uniqueness claim.
5. **Computational cost:** compare sequence-length scenarios using the cost model; predict which arithmetic count grows faster and locate the crossover. Distinguish arithmetic counts from hardware-dependent runtime.
6. **Information paths:** select or trace a path between distant tokens in recurrent and self-attention diagrams; compare sequential dependencies. Avoid another numerical target when the graph directly teaches the point.

Retain genuine mathematical exploration; replace invented semantic targets with tracing and prediction.

### Wuhan: early transmission dynamics

Source: `lemma/examples/gallery/wuhan-2020.json`.

1. **Doubling time:** compare growth curves; predict the effect of slower growth, then explore. Retain the numerical relationship.
2. **Reporting-delay dip:** inspect an apparent recent decline and choose which conclusions are justified; reveal delayed reports in an explicitly illustrative example. Explain why the dip alone establishes neither a real decline nor continued growth.
3. **Serial interval:** identify symptom-onset dates on paired timelines and match the relevant interval. Contrast with infection-to-symptoms so serial interval is not confused with incubation.
4. **Reproduction number:** compare generation diagrams for R below, at, and above one; predict whether counts shrink or grow. Keep a model when useful, without compulsory parameter hunting.
5. **Growth to R₀:** compare outbreaks with equal growth but different serial intervals; predict the required reproduction number and explore the relationship. Close by selecting warranted and unwarranted claims about the early estimates, including small samples and model assumptions.

Keep quantitative models, add evidence interpretation. Do not present the teaching approximation as a reproduction of the paper's full estimation method.

### Opinion dynamics and bounded confidence

Source: `lemma/examples/gallery/opinion-dynamics-2002.json`.

1. **Repeated averaging:** teach one update, then select the next opinion or match a listening rule to a trajectory. Retain the model to reveal repeated convergence.
2. **Confidence window:** select which agents a focal agent listens to before advancing the simulation. Feedback connects inclusion to the distance rule.
3. **Three phases:** compare simulated outcomes at different confidence ranges; classify fragmentation, polarization, and consensus. Keep the crowd simulation central.
4. **Edge pull:** compare an edge agent and a middle agent; identify their eligible neighbors and predict movement. Reuse the same rule rather than introduce a detached chart.
5. **Own-side bias:** compare symmetric and asymmetric listening windows; predict which neighbors are excluded and how this changes movement.
6. **Splits lock in:** pause the simulation around gap formation; identify which connections disappear and select why averaging can no longer reconnect the camps under the demonstrated conditions.

Finish by distinguishing a possible mechanism from evidence that real societies obey it. This paper is a strong fit for simulation, not a reason to remove simulations generally.

### Gettier: justified true belief

Source: `lemma/examples/gallery/gettier-1963.json`.

1. **Three conditions:** teach one everyday example, then classify short cases by truth, belief, and justification under the proposed definition. Distinguish satisfying the definition from settling what knowledge is.
2. **Justified but false:** reveal a person's evidence before revealing the actual situation; identify what changed about truth and what did not change about the person's evidence. Remove the invented percentage threshold for justification.
3. **Justification through deduction:** trace or order premise → valid inference → conclusion; distinguish valid reasoning from a true premise. Attribute the justification principle to the argument rather than present it as beyond dispute.
4. **Case I, coins and job:** stage the original case; match Smith's reasons and the actual truth-making facts to separate paths. Identify their disconnect.
5. **Case II, Ford or Barcelona:** use categorical city choices and a small disjunction table; distinguish the disjunct supported by evidence from the disjunct that happens to be true. No numbered-city slider.
6. **The gap:** classify a new, labelled hypothetical case and compare interpretations of its significance. Check faithful understanding of Gettier's objection without grading agreement with his intuition. Distinguish necessary conditions, sufficient conditions, and the fact that the paper supplies no complete replacement definition.

Retain truth tables or discrete logical switches when they illuminate a distinction; do not force every case into a manipulable numerical model.

### Turner: the frontier in American history

Source: `lemma/examples/gallery/turner-1893.json`.

Turner's thesis is an interpretive argument that later historians have heavily contested. Every task should attribute claims to Turner and let the learner separate what he argues from what the lesson's model assumes.

1. **Frontiers at different speeds:** keep the advancing-lines model, but replace the "catch your place in its ranching stage" targets with reading a timeline: for a chosen place, order the stages it passes through, then predict how a faster farming frontier (the railroad case) compresses them. The fixed rancher speed and the omitted mining frontier stay visible in the model note.
2. **The gate of escape:** a determinate mechanism under stated assumptions. Teach the outside-option rule with one worked wage, then compare two cities (cheap versus costly migration) and predict which wage floor rises. The model is useful; the wage numbers are illustrative and should say so.
3. **States competing for settlers:** stage the evidence: two states' voting rules, then decade-by-decade migration, then reform. Match each change to the pressure Turner says produced it. Replace the population-loss target with selecting which conditions (easy route west, restrictive franchise) make the pressure strongest, and ask what the model leaves out, such as immigration and economic motives.
4. **Same rules, opposite outcomes:** the richest-tenth curve is an invented function, which the model note admits. Teach with two labelled hypothetical districts, one with plentiful unclaimed land and one fully claimed; classify which outcome each produces under unchanged rules. Keep the curve only as an illustration, without numerical mastery targets on an invented quantity.
5. **When the frontier closes, law steps in:** interpretive. Present Turner's causal claim as a short chain (free land → equality → closure → regulation as substitute), have the learner order it, then compare his reading with a labelled alternative explanation (industrialisation, immigration, urban labour movements) without grading agreement. Factual misattributions still get correction. The current regulation slider, with targets of 0.59 and 0.69, should go.

Keep concepts 1 and 2 as models. Turn 3–5 into staged evidence, classification, and attributed interpretation.

### Aquinas: the nature and extent of sacred doctrine

Source: `lemma/examples/gallery/aquinas-senses.json`.

The lesson teaches a theological framework, and that framework rests on premises the learner need not accept. Determinate tasks ask what follows within Aquinas's argument; nothing asks the learner to affirm it.

1. **Same conclusion, different route:** the route sliders treat proofs as continuous quantities that switch on at the halfway mark, which disguises a category as a slider. Replace them with classification: match conclusions to the routes that reach them (astronomer, physicist, philosopher, revelation) and select which pairs count as one science or two under Aquinas's criterion. The surveyor-and-labourer transfer case already fits.
2. **Reason's route is few, slow, and mixed with error:** Aquinas gives three qualitative limits, not rates. Teach them as three named obstacles and classify short labelled scenarios by which obstacle applies. Keep a curve only if it is clearly labelled as an illustration; the "everyone has talent and leisure" transfer question is the real test.
3. **Borrowed starting points:** order the dependency chain (arithmetic → music; higher science → lower science), then classify examples (an engineer using physics, a musician using ratios) by whether they borrow principles. The invented "firmness" score adds nothing the chain does not show.
4. **One viewpoint makes one science:** keep the table and its topic toggles. Replace the target-hunting goals with selecting topics, predicting which sciences treat them, then switching to the formal aspect "as revealed" and observing them unify. The health-school transfer case is a good determinate check of the criterion.
5. **Teaching through bodily images:** compare two audiences and two ways of stating the same truth; predict which reaches more people and why. Drop the familiarity slider, which the model note says the model added, and keep the claim attributed to Aquinas.
6. **Why a worm can say more than the sun:** interpretive and the lesson's contribution. Stage Aquinas's three reasons, have the learner match each reason to an example image, and compare with a labelled objection. The invented risk curves should be clearly marked as illustration or removed.

This lesson is the strongest case in the gallery for removing models from most concepts: classification, ordering and attributed interpretation teach the distinctions directly.

### Mendel: experiments on plant hybrids

Source: `lemma/examples/gallery/mendel-1866.json`.

1. **Dominance:** keep the parent toggles, but ask the learner to predict the hybrid before each cross, then show that it looks the same whichever parent supplied the dominant form. Keep the blending what-if as a clearly labelled counterfactual comparison, not a slider target. The stem-length transfer case fits.
2. **Ratios only appear in large counts:** a strong fit for simulation. Let the learner draw pods and plants, predict whether a 2:1 plant is distinguishable from 3:1 at small and large counts, then reveal. Distinguish chance scatter from a different underlying ratio.
3. **Equal cells, random pairing:** build the 2×2 pairing table by matching egg and pollen types to offspring kinds, then explore unequal cell shares with the existing model. The backcross transfer case is determinate and good.
4. **3:1 is really 1:2:1:** stage the reveal. First group the offspring by appearance (3:1), then reveal breeding results showing two-thirds of the dominant-looking plants split. Classify plants as pure or hidden hybrid. Retain Mendel's actual reported ratios beside the model's averages.

Keep the sampling and pairing models; turn the parent crosses into predictions before reveals.

### Brown v. Board of Education

Source: `lemma/examples/gallery/brown-1954.json`.

The opinion is legal reasoning built on contested social-science evidence. Tasks distinguish what the Court held, what it relied on, and what the model invents.

1. **The old yardstick:** a determinate rule test. Present two schools' measurable features and classify whether they pass "separate but equal" as earlier courts applied it. The 5-point tolerance is the model's invention and should be labelled as such or replaced by "substantially equal" judgements on described cases.
2. **The escape route closes:** stage the history: earlier graduate-school cases won on a specific tangible gap; then the lower courts found these schools equalised. Order the cases and select why the Court could no longer avoid the doctrine. The Delaware transfer question fits well.
3. **Intangible factors:** compare two described schools, equal in buildings but one separated, and select which aspects of education the Court said separation removes. The weighted "opportunity" sum is invented; keep it only as a labelled illustration.
4. **The message of separation:** order the causal chain the opinion quotes from the Kansas finding (separation → sense of inferiority → motivation → learning), and identify which link the law's sanction strengthens. Make clear the Court described this mechanism in words and that the social-science support was later debated; do not present the link strengths as measured.
5. **Inherently unequal:** apply the holding to new labelled cases (equal buildings with separation; better-funded separate schools; separation without law) and select what the Court's reasoning implies for each. The last case is interpretive: the opinion addresses legally mandated separation, so feedback explains the limits of the holding rather than grading one answer.

Keep a causal diagram for concept 4; replace continuous slider targets with rule application and staged case history.

### Poe: The Masque of the Red Death

Source: `lemma/examples/gallery/poe-red-death.json`.

The source is fiction. The lesson uses epidemic models to read the story, so every task must separate what Poe wrote from the epidemiological teaching model laid over it, and never present the model as the story's claim.

1. **Person-to-person spread:** keep the grid simulation. Predict which outbreak spreads further (few sources with high transmission versus many sources with low transmission), then run it.
2. **The fast-killer paradox:** keep the simulation; predict how removal speed changes spread, then compare with the story's half-hour death. Distinguish the model's point (time to transmit) from anything Poe states.
3. **Crowding threshold:** a strong simulation fit. Pause the simulation and select whether an unbroken path through the crowd exists, then run it to confirm.
4. **The welded gates:** the gates are already an open-or-welded toggle. Show the two scenarios side by side rather than one at a time, and select which risks each changes. The many-small-lodges transfer case fits well.
5. **One masked guest:** stage the story's ending against the model: one arrival in a sealed, fully susceptible crowd. Then close with an interpretive task: compare a literal epidemiological reading with the allegorical readings critics give (death as inescapable), without grading which reading the learner prefers.

Retain simulations for 1–3; compare the gate scenarios side by side; add an explicit fiction-versus-model distinction and one interpretive close.

### Euclid: the equilateral triangle construction

Source: `lemma/examples/gallery/euclid-equilateral.json`.

Proof material is largely determinate. The critiques come from the lesson's guide to the proposition, so attribute them to it.

1. **A circle is a set of equal distances:** keep the geometry model; the transfer case (a bigger circle around A) is the real check. The "as far from B as possible" target is fine but optional.
2. **Two circles make three equal sides:** order the proof's steps (circle around A, circle around B, crossing point C, CA = AB, CB = AB, therefore CA = CB) and identify which postulate or common notion justifies each. Keep the model to show the construction.
3. **Zeno's worry:** reveal the hypothetical: lines meeting early at E and running together. Select which hidden assumption rules it out. The model targets on isosceles tolerances add little to that move.
4. **When do circles cross?** Keep the model; it is genuinely exploratory. Predict crossing for described radius and distance cases, then verify.
5. **A world where the circles never meet:** stage the argument: the fractions-only plane keeps both circles but loses C, because √3/2 is irrational. The existing true/false check fits. Keep the zoom as a demonstration; feedback should explain why no finite grid reaches C.

Keep the geometry models; add proof ordering and justification matching; treat the critiques as attributed hypotheticals.

### Wave interference and the double-slit experiment

Source: `lemma/examples/gallery/wave-interference.json`. Combined lesson from four sources: two encyclopedia articles and two textbook chapters.

1. **Superposition:** keep the shift model; predict combined height at in-step, half-cycle and quarter-cycle shifts before revealing. The unequal-amplitude transfer case fits.
2. **Brightness redistributes:** compare bright and dark spots and select what happens to total energy. Distinguish coherent from incoherent sources using the two-lamps case.
3. **Double-slit fringes:** a strong model fit. Predict how fringe spacing changes with wavelength, slit gap and distance, then verify. The red-and-blue transfer case is good.
4. **Dot by dot:** keep the dot-accumulation demonstration; predict what a single dot tells you and what a thousand tell you.
5. **Watching the slits** (left out of the built lesson because its model failed a quality check): this concept fits staged revelation better than a model. Reveal the which-path outcome and select which conclusions are warranted, with care to attribute interpretations of quantum measurement rather than present one as settled.

Strong fit for models in concepts 1–4; the missing concept argues for non-model activities.

### Schelling's model of segregation

Source: `lemma/examples/gallery/schelling-segregation.json`. Combined lesson from four sources: an encyclopedia article and three papers.

1. **Stay or move:** teach one household's rule on a single neighbourhood: select whether a given household moves, and why. The neighbourhood-counting transfer case already does this.
2. **Every move unsettles someone else:** step the simulation one move at a time and identify which neighbours become unhappy after each move.
3. **Mild wishes, strong divide:** predict the final alike share for households wanting about a third alike, then run. The existing check, that a segregated map does not reveal strong preferences, is the key distinction and should remain.
4. **Tipping, then a plateau:** compare runs across preference levels and locate the jump. Distinguish a threshold in this model from evidence about real cities.
5. **Threshold tracks group size:** compare a small and a large group at the same preference; predict which tips first.

Finish by separating what the model shows (preferences can be sufficient to produce segregation) from what it cannot show (that preferences are the cause in a real city), drawing on Clark and Fossett's social-context discussion. A strong simulation lesson, like opinion dynamics.

### Information cascades

Source: `lemma/examples/gallery/information-cascades.json`. Combined lesson from three sources: an encyclopedia article and two papers.

1. **Weighing clues:** a determinate update. Compare people with different clue counts and select who should be more confident; the Ana-and-Ben case does this. Keep the bars.
2. **When the lead hits two:** step through a line of choices, revealing each earlier action, and select when a person's own clue stops mattering. A sequential reveal teaches this better than slider targets.
3. **Cascades start early:** keep the curve; predict how quickly "no cascade yet" falls with group size and accuracy.
4. **Wrong cascades:** run many lines and classify each as a right or wrong cascade; the share of wrong ones is the point. Keep the existing check.
5. **Followers add no information:** compare a world where clues are visible with one where only choices are, and select which accumulates evidence. Keep the comparison model.
6. **Too many copiers:** keep the model, but label the mean-field approximation and the paper's network setting clearly.
7. **One small public fact can topple millions** (left out of the built lesson for exceeding a narration length limit): best taught by staged revelation. Show a settled cascade, reveal one public signal, and predict whether it breaks.

### Ice–albedo feedback and multiple climates

Source: `lemma/examples/gallery/ice-albedo-feedback.json`. Combined lesson from four sources: two encyclopedia articles and two papers.

1. **Energy balance:** keep the model; predict the direction of temperature change for a darker or brighter surface (the ash case), then verify.
2. **Ice that depends on temperature:** trace the feedback loop as a causal sequence (cooling → more ice → more reflection → more cooling) before exploring the S-shaped curve.
3. **Three balanced climates:** locate the crossings on the curves and classify each as snowball, intermediate or ice-free.
4. **Valleys and hilltops:** a strong fit for the ball-drop model. Predict where a dropped ball ends, then verify; classify each balance point as stable or unstable.
5. **Strength of the ice switch** (left out of the built lesson because its model dropped a control the earlier concept used): best as a comparison of strong and weak switches, predicting whether three balance points survive.
6. **Hysteresis:** keep the sweep model; order the states along a dimming-then-brightening path. The CO₂ transfer case connects it to the real Snowball Earth explanation.

Close by distinguishing the zero-dimensional teaching model from claims about Earth's actual climate history.

### Externalities and Pigouvian taxes

Source: `lemma/examples/gallery/externalities-pigou.json`. Combined lesson from four sources: two encyclopedia articles, a textbook reading and Banzhaf's history of pollution pricing.

1. **Private versus social cost:** a determinate worked example; keep the cost lines, with feedback on the size of the gap.
2. **Overproduction:** select the market output and the efficient output on the diagram, then identify the deadweight units. The vaccination transfer case fits.
3. **A corrective charge:** predict the effect of a charge below, at and above the harm, then explore.
4. **Price versus quantity:** compare a charge and a cap when costs turn out higher than planned; select which outcome each holds fixed. A good model fit.
5. **Open-access commons:** keep the fishery model; predict where open access settles relative to the value-maximising fleet.
6. **The borrowed name:** interpretive history. Jev left two possible problems on this concept for review, a possible wrong claim and a possible fabricated finding, so verify its claims against Banzhaf before redesigning it. The redesign should be staged evidence (the citation counts the paper reports) followed by selecting which conclusions those counts support and which they cannot, given the paper's own caveats about search methods. The guess-the-bar sliders should go.

### Loss aversion and myopic loss aversion

Source: `lemma/examples/gallery/loss-aversion.json`. Combined lesson from four sources: an encyclopedia article and three papers.

1. **Losses loom larger:** keep the value curve; the find-$20, lose-$20 case is a good determinate check.
2. **When to take a coin flip:** predict acceptance for described bets and λ values, then verify; the doubled-stakes case fits.
3. **How big is λ:** a pooling mechanism. Compare a precise study and a noisy one with the same estimate, and predict which is pulled further toward the middle. Keep the meta-analytic estimate attributed and its uncertainty visible.
4. **Bundling bets:** compare judging one flip with judging a bundle; the watching-each-flip case checks that bundling depends on how outcomes are evaluated.
5. **Evaluation period:** keep the model, labelled clearly as illustrative returns rather than the paper's data. Predict how lengthening the period changes stocks' felt value.
6. **The price of vigilance:** compare two investors with different evaluation periods and select the required premium for each. Distinguish the model's mechanism from the empirical claim about the equity premium.

## Patterns across all eighteen lessons

- **Strong fits for live models (keep them central):** opinion dynamics, Schelling, Poe's contagion concepts, wave interference, ice–albedo, Mendel's sampling, Euclid's crossing circles, and the quantitative parts of Galton, Ioannidis, Wuhan, attention, cascades, externalities and loss aversion.
- **Models that should give way to other activities:** Aquinas (all six concepts), Turner 3–5, Brown 1–3 and 5, Gettier, and the historical concept in externalities. These invent continuous quantities for qualitative arguments or legal tests.
- **Categories disguised as sliders:** only Aquinas's four route sliders, which count a route as a proof once past halfway. The other on/off choices (Mendel's parents, Brown's law, Poe's gates, Aquinas's topics) already use toggles (40 across the gallery). The remaining problem with them is the target-hunting goals, not the control.
- **Interpretive closes:** Turner, Aquinas, Brown, Poe and Gettier need feedback that attributes positions and explains limits without grading agreement.
- **Missing concepts:** the three concepts left out of the built lessons (watching the slits, the ice switch's strength, a public fact breaking a cascade) are all better suited to staged revelation or comparison than to a model. That is evidence for the proposal: model-only generation struggles exactly where other activities fit.
- **Multi-source lessons:** they add a source-attribution layer. Activities can ask which source supports a claim, which is a natural use of the "select a supporting passage" response.

## Automatic selection and Jev

The existing Jev adapter supports typed choices, and every build now requires Jev for categorisation and critical-error checks; activity selection would be a plausible extension, not a tested instructional selector.

1. The generation model proposes the objective, relevant source passages, misconception, and a small set of feasible activity plans per concept.
2. Code excludes unsupported plans or plans missing required evidence/resources.
3. Jev chooses among eligible plans using the objective, audience, prerequisites, source material, and concrete activity descriptions. Include a 'none suitable' outcome; do not force a choice among bad plans.
4. The generation model writes the selected sequence and prepared feedback. Missing, failed, uncertain, or 'none suitable' Jev advice returns selection/revision to the generation model, without forcing a live-model fallback.
5. Structural validation and grounded content review evaluate the built result, not just the planned activity. Reuse existing fact-checking context where possible; do not add redundant semantic calls by default.

Do not route by the primary category alone. Do not interpret Jev's probabilities as probabilities of learner mastery. Keep decisions and their inputs tied to the exact outline version. No learner response is sent to Jev during playback.

## Feedback and completion

Each response block declares its purpose:

- **Opening judgment:** optional, unscored; revisit after teaching when useful.
- **Determinate:** an answer follows from the supplied facts, stated rules, or explicitly attributed framework. Give an explanation, retry, and an eventual Show me route. Incorrect attempts are not proof of inability.
- **Interpretive:** prepared responses explain support, assumptions, tensions, and limits. A disagreement is not itself an error; factual mistakes still receive correction. Continue after inspecting feedback without requiring agreement.

Avoid requiring every concept to end in an additional test. Require an explicit learning objective and meaningful engagement; use transfer tasks where they genuinely add value. Completion records progress, not a claim of mastery.

## Current support and gaps

An inventory of the code and the eighteen gallery lessons, measured against the vocabulary above.

### What the code supports

- **Model blocks:** `watch` (narrated model tour), `walk` (narrated walkthrough), `goal` (put the model into a target state, with hints that get more specific and Show me), `predict` → `reveal`, `check`, and `connect` (the equation, each term linked to its control).
- **Teaching blocks without a model:** `explain` (explanation with source quote); `worked` (2–8 steps shown in turn, with optional results); `compare` (2–3 cases side by side, either text or the concept's own live model set to each case's values, with its key numbers under each); `stages` (2–6 pieces of evidence revealed one at a time).
- **Response blocks:** `choice` with a declared purpose (`determinate`, single or `multi` select-all; `interpretive`; `opening`), optionally `revisits` an earlier opening judgment; `sort` (cards into 2–4 groups); `match` (one-to-one pairs, targets shuffled); `order` (3–7 items, arrow buttons); `trace` (select nodes, or a path along the links, on an authored diagram, by click or keyboard); `passage` (choose the supporting passage, each option checked word for word against the source and, in combined lessons, against the source it names); `estimate` (a number within a tolerance); `construction` (authored drawing steps, or the classic equilateral triangle); `inheritance` (crosses with a chosen second parent).
- **On any block:** `hypothetical: true` shows a "Hypothetical teaching case" label; response blocks take 1–3 `hints` before Show me.
- **Checks:** `lemma/lesson.py` validates every block, including references, ranges, one-to-one matching, path answers that follow the links, grounding of passages, and teaching before practice. Jev's fact-check reads every block and its marked answers.
- **Generation:** an outline concept may be `"visual": "none"` (taught without a live model) and proposes 2–3 activity `plans`. Before any concept is drafted, Jev chooses one plan per concept, or `none_suitable`, which leaves the choice to the model. The chosen plan goes into the concept prompt, and the decision and its options are kept with the lesson as `activity_plans`. Concepts without a model have their own prompt. Every generated concept must have `activities`.

### What the gallery uses

- All 93 gallery concepts still follow one fixed sequence: watch → walk → explain → goal → goal → predict → reveal → connect, plus a check on 32. `eval/publish_gallery.py` and `eval/publish_coverage.py` added that sequence; the gallery has not been rebuilt with the new generation.
- Every gallery concept has a live model: 41 curves, 13 bars, 11 agents, 11 causal, 8 tables, 6 geometry, 3 sampling. The network visual is unused.

### Remaining gaps

1. **The gallery.** None of the eighteen lessons uses the new blocks. The mappings above say which concepts should change; rebuilding them is paid generation work.
2. **Real-model evidence.** The plan → Jev → write pipeline is covered by automated tests with fake providers. Whether real models write good blocks, and whether Jev's choices are good, needs an evaluation run.
3. **Selecting on a model's own visual.** `trace` uses an authored diagram. The causal and network visuals of a live model still only display, so the learner cannot trace on the model itself.
4. **Learning evidence.** As the evaluation section says, completing a block proves only that it can be completed.

## Engineering boundaries for a later implementation

Current generation (`lemma/generate.py`), schema/checking (`lemma/lesson.py`), and playback (`lemma/static/player.js`) all encode a model-first structure. Hiding the model panel alone will not fix the constraint. Authoring, fact-check presentation, progress/resume, and export also need to agree on the new format.

Proposed conceptual contract, not final field names:

- **Concept:** objective, prerequisite IDs, supporting sources, ordered blocks, optional shared models.
- **Block:** a supported teaching or response variant, with explicit data requirements.
- **Response:** structured input kind, judgment purpose, answer/rubric where appropriate, complete prepared feedback, and completion policy.
- **Evidence:** source passage or clearly labelled hypothetical material. Model assumptions and illustrative quantities remain explicit.

Universal checks cover valid references, grounding, complete feedback, supported block kinds, prerequisite order, and honest material labels. Model-specific checks retain finite outputs and reachable goals whenever a model goal exists. Do not require a model goal to validate a source-comparison task. Mechanical checks do not prove philosophical validity or historical accuracy.

## How to evaluate the proposal before rollout

Build representative prototypes across the gallery: Galton exploration, attention tracing, Wuhan evidence interpretation, opinion simulation, Ioannidis count comparison, Gettier case reasoning, Aquinas classification without models, Brown rule application to new cases, Poe's fiction-versus-model distinction, and Euclid proof ordering. Then cover every mapped concept before treating the design as general.

Check whether learners can explain the intended distinction through a fresh structured case, not merely reproduce demonstrated clicks. Observe confusion and the use of hints/Show me with explicit participant consent; preserve the product's no-telemetry policy. Establish success criteria before claiming learning improvement.

Verify saved and exported lessons, keyboard operation, feedback for wrong/partial responses, and optional-model lessons end to end. Computational reachability proves only that an interaction can be completed—not that completing it teaches the concept.

History, theology, law, literature, physics, urban studies, climate science and behavioural economics now have source-grounded gallery lessons. They broaden the design corpus but do not establish coverage of any discipline. Jev placed both the information-cascades and the loss-aversion lessons in economics, so subject labels in the gallery are a weak proxy for coverage. Before claiming general coverage, test additional sources and review whether feedback fairly represents their evidence and interpretive positions.
