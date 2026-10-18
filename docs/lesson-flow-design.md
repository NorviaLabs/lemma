# Concept-specific lesson flows — design proposal

Status: design proposal, not a completed generation redesign. The gallery now contains twelve playable lessons using shared activity sequences; the detailed mappings below were based on the original six lessons and their 31 concepts. Automatic activity selection and the fuller interaction vocabulary remain proposed. These mappings are design hypotheses, not evidence of improved learning.

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

## Automatic selection and Jev

The existing Jev adapter supports typed choices; this is a plausible extension, not a tested instructional selector.

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

## Engineering boundaries for a later implementation

Current generation (`lemma/generate.py`), schema/checking (`lemma/lesson.py`), and playback (`lemma/static/player.js`) all encode a model-first structure. Hiding the model panel alone will not fix the constraint. Authoring, fact-check presentation, progress/resume, and export also need to agree on the new format.

Proposed conceptual contract, not final field names:

- **Concept:** objective, prerequisite IDs, supporting sources, ordered blocks, optional shared models.
- **Block:** a supported teaching or response variant, with explicit data requirements.
- **Response:** structured input kind, judgment purpose, answer/rubric where appropriate, complete prepared feedback, and completion policy.
- **Evidence:** source passage or clearly labelled hypothetical material. Model assumptions and illustrative quantities remain explicit.

Universal checks cover valid references, grounding, complete feedback, supported block kinds, prerequisite order, and honest material labels. Model-specific checks retain finite outputs and reachable goals whenever a model goal exists. Do not require a model goal to validate a source-comparison task. Mechanical checks do not prove philosophical validity or historical accuracy.

## How to evaluate the proposal before rollout

Build representative prototypes across the gallery: Galton exploration, attention tracing, Wuhan evidence interpretation, opinion simulation, Ioannidis count comparison, and Gettier case reasoning. Then cover every mapped concept before treating the design as general.

Check whether learners can explain the intended distinction through a fresh structured case, not merely reproduce demonstrated clicks. Observe confusion and the use of hints/Show me with explicit participant consent; preserve the product's no-telemetry policy. Establish success criteria before claiming learning improvement.

Verify saved and exported lessons, keyboard operation, feedback for wrong/partial responses, and optional-model lessons end to end. Computational reachability proves only that an interaction can be completed—not that completing it teaches the concept.

History and theology now have source-grounded gallery lessons based on Turner and Aquinas. They broaden the design corpus but do not establish coverage of either discipline. Before claiming general coverage, test additional sources and review whether feedback fairly represents their evidence and interpretive positions.
