"""Everything the Jev eval asks about a lesson, as data. Change a question, bump VERSION: runs record it.

Every question is asked three ways (LENSES), and the majority decides. A question either needs the paper
(it gets the concept or lesson with the matching paper excerpts) or judges the teaching alone (it gets the
lesson only, as a learner sees it: no paper, and no hidden success conditions).

The eval's questions are its own. A build already asks Jev lemma/factcheck.py's critical-error questions and
repairs a concept until they pass, so asking the same ones here would only measure what the build was made to
pass. These ask about the same kinds of error from a different angle, in different words.

Part A items apply only to concepts that have what they ask about (a model, goals, scored tasks). Part B checks
are single questions; a check that looks for a problem says so with `passed_when: "no"`.
"""

VERSION = "jev-eval-11"

LENSES = {
    "referee": "You are a careful reviewer of research, checking a teaching lesson against the paper it is based on. ",
    "teacher": "You are a teacher who has taught this subject for years, deciding whether to give this lesson to a class. ",
    "newcomer": "You are an intelligent adult outside this field, using this lesson to learn the paper's ideas. ",
}
CONFIRM_AT = 0.7  # most lenses at or above this confirm a critical error; below, a yes goes to a person
# Per kind, where planted errors separated from the unmodified lessons (eval/results/existing-run3*, 2026-10-18:
# planted misleading quotes 0.58–0.82, unmodified quotes up to 0.41). The reversed_model question never separated,
# so it only sends a concept to a person; the direction check (DIRECTIONS) confirms reversed models instead.
# Wrong claims (2026-10-19, existing-run9*): planted 18, clean 93 concepts; at 0.7 the median lens caught 16/18 but
# confirmed 12 clean concepts, at 0.8 it caught 12/18 and confirmed 1. Both sets were used to choose this.
CONFIRM_BY_KIND = {"misleading_quote": 0.55, "reversed_model": None, "wrong_claim": 0.8}
BORDERLINE = 0.1  # a confirmation this close to its threshold is shown as borderline

# The direction check: for each control and output of a concept's model, Jev says which way the paper (and,
# separately, the lesson's own teaching) says the output moves; code compares that with what the model does.
DIRECTION_ANSWERS = {"rises": "It rises", "falls": "It falls", "not_said": "The text doesn't say, or it depends"}
DIRECTION_PAIRS = 6  # control–output pairs asked per concept, those the teaching talks about first
# P(the opposite of what the model does) at or above these confirms a reversed model. On 2026-10-18, a model
# contradicting its own teaching scored 0.91–1.0 when planted and at most 0.78 otherwise; the paper's reading
# didn't separate (planted 0.22–0.96, an unmodified Turner concept 0.79), so it confirms only when very clear.
DIRECTION_AT = {"text": 0.85, "paper": 0.9}
DIRECTION_REVIEW = 0.6  # at or above this, a possible reversal goes to a person
DIRECTION_ASK = {
    "paper": "According to the paper excerpt only (not any model in the lesson), when {control} increases with everything else unchanged, "
             "what happens to {output}?",
    "text": "According to this concept's explanation, tour and walkthrough, when {control} increases with everything else unchanged, "
            "what happens to {output}?",
}

ANSWERS = {  # Part A: Jev chooses one
    "yes": "Fully true",
    "partly": "True only in part, or true but missing something a learner would notice",
    "no": "Not true",
    "cannot_judge": "The text given isn't enough to judge this",
}

# Part A, for each concept. `paper`: whether the question needs the paper excerpts. `needs`: what a concept (or its
# lesson) must have for the item to apply (see applies()). `passed_when: "no"`: the item asks about a problem. Overlapping checks were removed: each problem counts once.
PART_A = {
    "A1": {"paper": True, "name": "Quote supports",
           "ask": "Read in its context in the paper excerpt, does the concept's quote support the main claim of its explanation?"},
    "A2": {"paper": True, "name": "Model is faithful", "needs": "model",
           "ask": "Does the concept's model behave like the mechanism the paper excerpt describes: the direction of each effect when a control rises, "
                  "its shape (linear, saturating, threshold, growth rate) and which variables matter? Simplifications the model's note labels are fine."},
    "A3": {"paper": True, "name": "Note is honest", "needs": "model",
           "ask": "Does the model's note say how the model is simplified and whether its numbers are illustrative or the paper's?"},
    "A4": {"paper": False, "name": "Taught before tested",
           "ask": "Is the idea taught clearly enough, before the learner is asked to do anything, that they could attempt every task without guessing?"},
    "A5": {"paper": False, "name": "Goals need the idea", "needs": "goals",
           "ask": "To reach the goals, does the learner have to reason with the concept's idea, rather than move controls at random?"},
    "A6": {"paper": False, "name": "Tasks are fair", "needs": "tasks",
           "ask": "Are the concept's scored tasks answerable from what was taught, with one supported answer and feedback that explains the others?"},
    "A7": {"paper": False, "name": "Activities fit the idea",
           "ask": "Do the concept's activities fit the kind of reasoning its idea involves: a live model where the idea is about quantities that vary, "
                  "and comparing, classifying, ordering or tracing where it is a distinction, an argument, a chain or a case?"},
    "A8": {"paper": True, "name": "Quote location is right",
           "ask": "The concept says where its quote comes from (QUOTE (...)). Does that match where the quote sits in the paper excerpt?"},
    "A9": {"paper": True, "name": "Sources named correctly", "needs": "multi_source",
           "ask": "The concept names the sources that support it. Do those sources, in the excerpt, actually support its explanation?"},
    "A10": {"paper": False, "name": "Interpretations aren't graded", "needs": "interpretive",
            "ask": "In the concept's interpretive questions, does the feedback explain each reading's support and limits without marking one reading "
                   "as the right opinion?"},
    "A11": {"paper": False, "name": "Hints build up", "needs": "hints",
            "ask": "Do the hints get more specific one at a time, from a nudge toward the answer?"},
    "A12": {"paper": True, "name": "Made-up cases are labelled",
            "ask": "Is every case, person or number in this concept that is not from the paper presented as hypothetical or illustrative, rather than as real?"},
    # From research on learning with visuals (see docs/lesson-flow-design.md): congruence and representational visuals
    # (Tversky et al. 2002; Höffler & Leutner 2007), coherence (Mayer), refutation of misconceptions, relating
    # representations (Ainsworth 2006), constructive tasks (Chi & Wylie 2014), self-explanation (Chi et al. 1994),
    # and worked examples before practice (Renkl & Atkinson).
    "A13": {"paper": False, "name": "Visual suits the mechanism", "needs": "model",
            "ask": "Does the concept's visual show its mechanism directly, in a form that matches it (change over time as motion, amounts as lengths, "
                   "causes as arrows), rather than decorating the explanation?"},
    "A14": {"paper": False, "name": "Nothing extraneous", "passed_when": "no",  # asked as a problem: the universal form was "no" on all 93 concepts
            "ask": "Does the concept include a side topic, decoration or digression that doesn't serve its idea?"},
    "A15": {"paper": False, "name": "Misconception refuted",
            "ask": "Does the concept name a mistaken belief a learner is likely to hold about this idea, and explain why it is wrong?"},
    "A16": {"paper": False, "name": "Representations connected", "needs": "model",
            "ask": "Does the concept help the learner relate its equation, its model and its explanation, so each part of one can be found in the others?"},
    "A17": {"paper": False, "name": "A task needs an inference",
            "ask": "Does at least one task make the learner work out something that wasn't shown (predict an outcome, explain a cause, apply the idea to "
                   "a new case), rather than only move controls or recall what was said?"},
    "A18": {"paper": False, "name": "Asks why",
            "ask": "Does a task ask the learner to choose or build the reason something happens, not only what happens?"},
    "A19": {"paper": False, "name": "Example before practice", "needs": "tasks",
            "ask": "Does the learner see the idea worked through on an example before solving a task on their own?"},
}

# Part C: critical errors, yes = an error was found. The kinds a build checks (lemma.factcheck.BUILD_KINDS) are
# worded apart from it on purpose; the others reuse the build module's wording, which the build never asks.
from lemma.factcheck import CRITICAL as _BUILD_CRITICAL  # noqa: E402

CRITICAL = {
    "wrong_claim": "Go through each statement this concept makes about what the paper found, argued or concluded. Is any of them contradicted by "
                   "the paper excerpt, or not supported by it at all?",  # overstatement is Honesty's question (B5), not a wrong claim
    "fabricated_finding": "Does this concept say the paper reported a specific number or result that is not in the paper excerpt? Numbers that "
                          "set up or come out of the teaching model (in its tour, walkthrough, goals or note) are illustrations, not reports: "
                          "answer no for those.",
    "reversed_model": _BUILD_CRITICAL["reversed_model"],
    "misleading_quote": _BUILD_CRITICAL["misleading_quote"],
}
WRONG_ANSWER = "Work the task out yourself from what the concept teaches. Is the answer it marks as correct different from the one you reach?"

# Part B, for the whole lesson: one question per check (yes = passed, unless passed_when is "no"). `when`: a check
# that only applies to some lessons ("omitted", "options", "multi_source"); it isn't asked otherwise.
PART_B = {
    "B1": {"paper": True, "name": "The paper in brief is accurate", "checks": [
        {"ask": "Does the paper in brief state the question the paper asks, as the paper does?"},
        {"ask": "Does it say what the researchers did, as the paper describes it?"},
        {"ask": "Does it state the paper's main finding correctly?"},
    ]},  # its numbers are checked one at a time, next to where the paper gives them (NUMBER_ASK)
    "B2": {"paper": True, "name": "Coverage", "checks": [
        {"ask": "Do the concepts teach the paper's main contribution?"},
        {"ask": "Do they include the supporting ideas a reader needs to understand that contribution?"},
        {"ask": "Does each concept come after the ones it builds on?"},
        {"ask": "Is something central to the paper missing from the concepts?", "passed_when": "no"},
        {"ask": "Do the concepts stay on what the paper is about rather than side topics?"},
        {"ask": "Does the lesson suggest deeper topics to follow up that it doesn't cover?", "when": "multi_source"},
    ]},
    "B3": {"paper": False, "name": "Teaching", "checks": [
        {"ask": "Does each concept carry one main idea?"},
        {"ask": "Do the explanations build intuition for why, not only state conclusions?"},
        {"ask": "Does a narrated tour or walkthrough describe something its model doesn't show?", "passed_when": "no"},
        {"ask": "Would a learner who finished the lesson be able to explain the main idea in their own words?"},
        {"ask": "Does the lesson build to, and deliver, the surprise it promises (THE BIG SURPRISE)?"},
    ]},
    "B4": {"paper": False, "name": "Practice", "checks": [
        {"ask": "Does at least one task apply an idea to a situation the teaching didn't show?"},
        {"ask": "Does any goal's text state the value or setting that reaches it?", "passed_when": "no"},
        {"ask": "Does any hint other than the last one give the answer away?", "passed_when": "no"},
        {"ask": "Are the wrong options in questions mistakes a real learner might make?", "when": "options"},
        {"ask": "Does a later concept bring back an earlier one, so the learner uses it again?", "when": "several_concepts"},
        {"ask": "Before an answer is revealed, is the learner asked to predict it from what they've been taught, rather than guess?"},
    ]},
    "B5": {"paper": True, "name": "Honesty", "checks": [
        {"ask": "Are the paper's caveats and limitations kept?"},
        {"ask": "Does the paper in brief claim more for the finding than the paper does?", "passed_when": "no"},
        {"ask": "Would a learner come away more certain than the paper is?", "passed_when": "no"},
        {"ask": "Does the lesson say which concepts were left out?", "when": "omitted"},
        {"ask": "Where the sources disagree or are uncertain, does the lesson explain it rather than present one view as settled?", "when": "multi_source"},
    ]},
    "B6": {"paper": False, "name": "Clear for the audience", "checks": [
        {"ask": "Is the language right for the stated audience?"},
        {"ask": "Is each technical term defined where it first appears or in the concept's terms?"},
        {"ask": "Are sentences short and direct?"},
        {"ask": "Is there a screen the audience couldn't follow without looking something up?", "passed_when": "no"},
    ]},
    "B7": {"paper": True, "name": "The paper in brief is grounded", "checks": [
        {"ask": "Does each quote in the paper in brief, read in its context in the paper, support what its page says?"},
        {"ask": "Is a quote in the paper in brief used for something its context doesn't say?", "passed_when": "no"},
    ]},
}

# The paper in brief's numbers, one question each: the sentence that uses it, beside the passage where the paper
# gives it (or the lesson-level excerpt, if the paper never prints it). A single question about every result in the
# brief was answered "yes, something's unsupported" 98% of the time on unmodified lessons, because Jev can't see
# every result at once.
NUMBERS_CHECKED = 8
NUMBER_ASK = "Look at item [{i}]. Does the paper report what this sentence says about {number}?"

# The scorecard: seven scores, each built from groups of questions. Every group counts once in its score (its answers
# are averaged first, over concepts for concept groups), so a score isn't weighted by how many questions a group
# happens to ask. Groups: Part A items ("A1"), Part C errors ("C:wrong_claim"), the direction check ("D"), and
# Part B dimensions ("B1"). Change these and bump VERSION, or scores stop being comparable.
SCORES = {
    "accuracy": {"name": "Accuracy", "about": "What the lesson says about the paper is true: no wrong claims or invented findings; the paper in brief",
                 "groups": ("C:wrong_claim", "C:fabricated_finding", "B1", "N")},
    "models": {"name": "Models", "about": "Models behave like the mechanism: faithful, effects in the right direction, not reversed",
               "groups": ("A2", "D", "C:reversed_model")},
    "grounding": {"name": "Grounding", "about": "You can see where each idea comes from: quotes support claims, locations and sources are right",
                  "groups": ("A1", "A8", "A9", "C:misleading_quote", "B7")},
    "honesty": {"name": "Honesty", "about": "Doesn't overstate: caveats kept, simplifications and made-up cases labelled, certainty not inflated",
                "groups": ("A3", "A12", "B5")},
    "teaching": {"name": "Teaching", "about": "Ideas taught well: before testing, with fitting visuals and activities, nothing extraneous, "
                                               "misconceptions refuted, representations connected, clearly, to the aha",
                 "groups": ("A4", "A7", "A13", "A14", "A15", "A16", "B3", "B6")},
    "practice": {"name": "Practice", "about": "Tasks make the learner use and explain the idea: fair, correctly marked, inferences and reasons, "
                                               "examples first, hints that build, earlier ideas revisited, interpretations not graded",
                 "groups": ("A5", "A6", "A10", "A11", "A17", "A18", "A19", "C:wrong_answer", "B4", "M:constructive")},
    "presentation": {"name": "Presentation", "about": "Measured from the lesson itself, without Jev: narration points at what it describes, "
                                                       "changes happen as they're described, and steps are short enough to take in",
                     "groups": ("M:signaling", "M:contiguity", "M:apprehension")},
    "coverage": {"name": "Coverage", "about": "The paper's main contribution and the ideas it needs, in order, without side topics",
                 "groups": ("B2",)},
}

# The data checks (M groups): exact measures computed from the lesson, no Jev. Signaling (Mayer): narrated steps that
# point at a part of the picture. Contiguity (Mayer): steps that describe a change and make it at the same moment.
# Apprehension (Tversky et al. 2002): narration steps short enough, and slow enough, to take in. Constructive (ICAP):
# concepts with at least one task that asks for an inference rather than manipulation alone.
STEP_WORDS = 40  # at most this many words in one narrated step
MS_PER_WORD = 200  # and on screen at least this long per word (about 300 words a minute), timed as player.js plays it
CHANGE_WORDS = ("rise", "rises", "fall", "falls", "increase", "decrease", "grow", "shrink", "drop", "raise", "lower", "push", "pull", "slide",
                "turn up", "turn down", "move", "moves", "shift", "watch", "now set", "set it", "make it", "add", "remove", "switch")
CONSTRUCTIVE = ("predict", "check", "choice", "match", "order", "trace", "passage", "estimate", "sort")

# The verdict comes from rules, not from another question (see verdict_for() in jev_judge.py).
B_PASS = 0.8  # a Part B dimension under this share of checks passed needs fixes

SCORED = ("choice", "match", "order", "trace", "passage", "estimate", "sort")


def scored_tasks(c: dict) -> list[tuple[str, str]]:
    """(key, label) for each task with a marked answer: the 'Use it' question, a check with an answer, and every
    activity block with an answer key."""
    out = []
    if "answer" in (c.get("predict") or {}):
        out.append(("predict", "the 'Use it' question"))
    if "answer" in (c.get("check") or {}) or (c.get("check") or {}).get("kind") == "choice":
        out.append(("check", "the check"))
    for a in c.get("activities") or []:
        if a.get("kind") in SCORED and not (a.get("kind") == "choice" and a.get("mode") != "determinate"):
            out.append((a["id"], f"the task \"{a.get('title') or a.get('question') or a.get('prompt') or a['id']}\""))
    return out


def applies(item: str, c: dict, lesson: dict | None = None) -> bool:
    need = PART_A[item].get("needs")
    if need == "model":
        return bool(c.get("model"))
    if need == "goals":
        return bool((c.get("explore") or {}).get("goals"))
    if need == "tasks":
        return bool(scored_tasks(c))
    if need == "multi_source":
        return bool((lesson or {}).get("sources"))
    if need == "interpretive":
        return any(a.get("kind") == "choice" and a.get("mode") == "interpretive" for a in c.get("activities") or [])
    if need == "hints":
        return any(g.get("hints") for g in (c.get("explore") or {}).get("goals") or []) or any(a.get("hints") for a in c.get("activities") or [])
    return True


def check_applies(check: dict, lesson: dict) -> bool:
    when = check.get("when")
    if when == "omitted":
        return bool(lesson.get("omitted"))
    if when == "multi_source":
        return bool(lesson.get("sources"))
    if when == "several_concepts":
        return len(lesson.get("concepts") or []) > 1
    if when == "options":
        return any((c.get("predict") or {}).get("options") or (c.get("check") or {}).get("options") or
                   any(a.get("kind") == "choice" for a in c.get("activities") or []) for c in lesson.get("concepts") or [])
    return True
