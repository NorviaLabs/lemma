# Judging rubric

Three judges score every lesson built from `papers.json`. Each judge is a different persona (`judges/`), ideally run on a model from a different family, and all three answer the same rubric so their scores can be combined and compared. This file is appended to each persona's prompt.

The rubric measures what Lemma's automatic checks (`lemma/lesson.py`) can't. The checks already prove that every quote appears word for word in the paper, that every expression gives finite numbers, and that every goal is false at the start and reachable. Judges don't repeat those checks. They judge meaning: whether the quote supports the claim, whether the model behaves like the paper's mechanism, whether the lesson teaches.

## What the judge receives

1. **The audience** the lesson was built for. Unless a run sets another, every lesson in `papers.json` is built for "A curious adult with no background in this field".
2. **The lesson** as JSON. `primer` is the paper in brief; each item in `concepts` has `idea`, `model` (controls, outputs, `visual`, `note`), `animation` (the narrated tour), `understand` (`explanation`, `quote`, `walkthrough`), `explore` (`goals` with `when`, `solution` and `hints`), `connect` (the equation), `predict` (the "Use it" step: a question about a new case, with the reasoning behind each option in `why`), `recap`, `terms`, and `check` when the concept is marked `hard`. The learner meets them in that order: tour, explanation, goals, "Use it", then the check. `omitted` lists concepts that were left out because they failed the checks.
3. **The paper's text** as Lemma extracted it. For a lesson built from several sources, each source is marked `SOURCE <id>`.

The Referee and the Teacher get all three at once. The Newcomer first gets only the audience and the lesson, and gets the paper and this rubric in a second turn (see `judges/newcomer.md`).

Models are written in Lemma's expression language: `+ - * / ^`, comparisons, `abs`, `min`, `max`, `sqrt`, `exp`, `log`, `if(cond, a, b)` and the like. Read an output's `expr` to see how it moves as the controls change. A goal's `when` is the condition the learner must reach, and `solution` is one set of control values that reaches it.

## Rules for every judge

- **Evidence first, then the score.** Every score cites at least one field path, such as `concepts[1].understand.quote`, and for faithfulness items a short passage from the paper. A score without evidence counts as missing.
- **Judge the lesson against the paper, not the paper against the world.** Don't fault the lesson for a claim the paper makes. Do fault it if it states a claim more strongly or more settled than the paper does, or drops a caveat the paper gives.
- **Simplification is allowed, when it's labelled.** A teaching model may leave out variables, use made-up numbers or straighten a curve, as long as `model.note` says so and the direction and shape of the effect still match the paper. Don't penalise a labelled simplification. Do penalise an unlabelled one, and any made-up number presented as a finding.
- **Length is not quality.** Don't reward a longer explanation or more concepts for being longer.
- **Say when you can't judge.** If the paper's text is too garbled to check a claim, or the relevant passage isn't in the text, answer `"cannot_judge"` and say why. Don't guess.
- **Critical errors are flagged separately** (below), even when everything else is good.

## Part A: each concept

Answer every item for every concept in `concepts`.

| Item | Question | Answers |
|---|---|---|
| **A1. Quote supports** | Read in its context in the paper, does `understand.quote` support what `understand.explanation` claims? *Yes* means the quote is evidence for the main claim. *Partly* means it is related but supports only part of the claim, or needs context the lesson leaves out. *No* means it is beside the point or, in context, says something different. | `yes` · `partly` · `no` · `cannot_judge` |
| **A2. Model is faithful** | Does the model behave like the mechanism the paper describes? Check the direction of each effect (raising a control moves an output the way the paper says), the shape (linear, saturating, threshold, tipping point), and which variables matter. Labelled simplifications are fine. *Partly* means the main effect is right but something secondary is wrong or missing in a way a learner would notice. | `yes` · `partly` · `no` · `cannot_judge` |
| **A3. Note is honest** | Does `model.note` say how the model is simplified and whether its numbers are illustrative or come from the paper? Are numbers the paper reports quoted correctly, and are no invented numbers presented as the paper's findings? | `yes` · `partly` · `no` |
| **A4. Taught before tested** | Is the idea shown (`animation`) and explained (`understand`) clearly enough that a learner in the audience could attempt `explore` and `predict` without guessing? | `yes` · `partly` · `no` |
| **A5. Goals need the idea** | Does reaching each goal in `explore.goals` require using the concept, rather than moving sliders at random or reading the answer from the prompt? Do the `hints` get more specific, without giving the answer away until the last one? | `yes` · `partly` · `no` |
| **A6. Questions are fair** | Is `predict` a genuinely new case rather than a repeat of the walkthrough? Are `predict` and `check` (when present) answerable from what was taught, with one clearly correct answer and wrong options a real learner might pick? Is each `why` correct? | `yes` · `partly` · `no` |

Each item takes a one- or two-sentence `reason` with its evidence.

## Part B: the whole lesson

Score each on 1 to 5 by the problems you find, not by an overall impression. First list every problem you found for that dimension in `reason`, each with its path. Then score:

- **5**: you found no problem worth fixing.
- **4**: one minor problem a learner would barely notice.
- **3**: two or more minor problems, or one a learner would notice.
- **2**: a problem that would leave the learner with a wrong idea, or several that together make the dimension weak.
- **1**: the dimension fails as a whole.

A 4 is not a safe default: it means you found exactly one minor problem. The anchors below describe what 5, 3 and 1 look like for each dimension.

**B1. The paper in brief is faithful.** Do `primer` and `intro` state the paper's question, what was done, what was found and why it matters, as the paper does?
- 5: Accurate on all four, with the paper's own hedges. A researcher in the field would sign off on it.
- 3: Broadly right, but one point is vague, slightly overstated or missing.
- 1: Gets the question or the main finding wrong, or invents a result.

**B2. Coverage.** Do the concepts cover the ideas a reader needs to understand the paper's main contribution? Use `omitted` too: was something central left out?
- 5: Every core idea is taught, in an order where each one builds on the last.
- 3: The main idea is taught, but a core supporting idea is missing or the order makes the learner wait for something they need.
- 1: The lesson teaches side topics and misses what the paper is about.

**B3. Teaching.** Does each concept carry one idea, explain it on the model before asking anything, and build intuition rather than state conclusions?
- 5: Every concept teaches; a learner would understand why, not just what.
- 3: Mostly teaches, but some concepts state conclusions, pack in several ideas, or test before they explain.
- 1: Reads like a summary with quizzes attached.

**B4. Practice.** Do the goals, the "Use it" question (`predict`) and `check` make the learner use the idea, including on a new case?
- 5: Every exercise needs the idea, and at least one transfers it to a new situation.
- 3: Exercises are fair but mostly repeat what was shown.
- 1: Exercises can be done without understanding anything.

**B5. Honesty.** Are simplifications labelled, caveats kept, uncertainty and disagreements between sources explained, and left-out concepts disclosed?
- 5: A learner would come away with the paper's real level of certainty.
- 3: One caveat is dropped or one result sounds more certain than the paper says.
- 1: A learner would come away believing something the paper doesn't claim.

**B6. Clear for the audience.** Is the language right for the stated `audience`, with jargon defined in `terms` or in place, and short sentences?
- 5: The audience could follow every screen without looking anything up.
- 3: Readable, but several unexplained terms or long, dense passages.
- 1: Written for experts in the field.

## Part C: critical errors

List every instance of these. Any one of them means the lesson shouldn't be shown to learners as it is.

An error is critical when it would leave the learner believing something false, wherever it appears: in the explanation, the model, the narration, a hint or the note. It doesn't need to be about the main idea. Don't soften it into a `partly` on Part A because the rest of the concept is right: list it here, and answer the Part A item it falls under `no`.

- **wrong_claim**: the lesson says the paper found or argued something it didn't, or teaches something the paper contradicts.
- **reversed_model**: a model, or any part of it the learner is shown, behaves differently from what the paper says: the wrong direction, the wrong growth rate or the wrong rule.
- **fabricated_finding**: an invented number or result presented as the paper's.
- **misleading_quote**: a quote that, in context, says something different from what the lesson uses it for.
- **wrong_answer**: a question or goal whose marked answer is wrong.

Each entry gives the `type`, the field `path`, the lesson's text, the paper's text that contradicts it, and one sentence on why.

## Part D: verdict

- `ship`: good enough to show a learner as it is.
- `ship_with_fixes`: worth showing after the listed fixes, none of them critical.
- `dont_ship`: has a critical error, or fails at teaching the paper.

Then list the **top three problems**, most important first, each with its path and a suggested fix.

## Output

Reply with one JSON object and nothing else.

```json
{
  "judge": "referee | teacher | newcomer",
  "paper_id": 0,
  "concepts": [
    {
      "id": "mid_parent",
      "A1": {"answer": "yes", "reason": "...", "evidence": ["concepts[0].understand.quote", "paper: \"...\""]},
      "A2": {"answer": "yes", "reason": "...", "evidence": ["..."]},
      "A3": {"answer": "yes", "reason": "...", "evidence": ["..."]},
      "A4": {"answer": "yes", "reason": "...", "evidence": ["..."]},
      "A5": {"answer": "partly", "reason": "...", "evidence": ["..."]},
      "A6": {"answer": "yes", "reason": "...", "evidence": ["..."]}
    }
  ],
  "lesson": {
    "B1": {"score": 4, "reason": "...", "evidence": ["..."]},
    "B2": {"score": 4, "reason": "...", "evidence": ["..."]},
    "B3": {"score": 3, "reason": "...", "evidence": ["..."]},
    "B4": {"score": 3, "reason": "...", "evidence": ["..."]},
    "B5": {"score": 5, "reason": "...", "evidence": ["..."]},
    "B6": {"score": 4, "reason": "...", "evidence": ["..."]}
  },
  "critical_errors": [
    {"type": "reversed_model", "path": "concepts[2].model.outputs[0].expr", "lesson": "...", "paper": "...", "why": "..."}
  ],
  "verdict": "ship_with_fixes",
  "top_problems": [
    {"path": "...", "problem": "...", "fix": "..."}
  ],
  "lens": {}
}
```

`lens` holds the persona's own extra answers, described in its prompt.

## Combining the three judges

- **Part A:** a concept item takes the majority answer. When all three disagree, it counts as `partly` and goes to human review.
- **Part B:** each score takes the median.
- **Part C:** a critical error counts when two or more judges report it, or when one judge reports it and another answers `partly` or `no` on the same concept's A1, A2, A3 or A6, since that usually means the second judge saw the same problem and rated it more gently. Any other critical error reported by a single judge goes to human review, because a single judge can be wrong.
- **Verdict:** the median verdict (with two judges, the more cautious one). A lesson with a critical error that counts is `dont_ship`.
- **Agreement:** report the share of Part A items where all three agree, and Krippendorff's alpha for Part B. Low agreement on an item means the rubric wording needs work before its numbers can be trusted.

These map to the targets in `PRODUCT.md`:

| Target | Measured as |
|---|---|
| Quotes support their explanations, at least 90% | share of concepts with A1 = `yes` |
| Models represent the mechanism correctly, at least 85% | share of concepts with A2 = `yes` |
| Lessons pass the checks without edits, at least 80% | not judged: the runner records whether the build passed `lesson.py` with no concept omitted |
| Learners reach goals without **Show me**, at least 60% | not judged: this needs real learners. A5 and the teacher's estimate are only a proxy |

## Calibrating the judges

Before trusting the numbers, check that the judges catch known faults:

1. Judge the hand-written Galton lesson (`lemma/examples/galton-1886.json`). Expect `ship` from all three, with A1 and A2 `yes` throughout.
2. Make broken copies of a few lessons, one fault each, and confirm that at least two judges flag each one:
   - swap a concept's `quote` for another real sentence from the paper that doesn't support the explanation (expect A1 `no` or `partly`, and `misleading_quote`);
   - flip a sign in a model's main `expr` (expect A2 `no` and `reversed_model`);
   - change a number the paper reports (expect A3 `no` and `fabricated_finding`);
   - give `predict` the wrong `answer` (expect A6 `no` and `wrong_answer`);
   - delete a model's `note` caveat about illustrative numbers (expect A3 `partly` or `no`).
3. Run each judge twice on the same five lessons. If its own verdicts change between runs, use a lower temperature or a stronger model.

To reduce self-preference, don't let the only judge come from the same model family that built the lesson. Use one judge from each of three families, and record which model built each lesson.
