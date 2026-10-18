"""Everything the Jev eval asks about a lesson, as data. Change a question, bump VERSION: runs record it.

Every question is asked three ways (LENSES), and the majority decides. A question either needs the paper
(it gets the concept or lesson with the matching paper excerpts) or judges the teaching alone (it gets the
lesson only, so the newcomer's view never sees the paper). Every yes/no question is phrased so that "yes"
is what's being looked for: a passed check in Part B, a found error in Part C.
"""

VERSION = "jev-eval-1"

# Each lens leads the question, so the same item is judged from three angles.
LENSES = {
    "referee": "You are a strict referee checking a lesson against the research it teaches. ",
    "teacher": "You are an experienced teacher of this subject, reviewing a lesson before students use it. ",
    "newcomer": "You are a curious adult new to this field, working through this lesson. ",
}

ANSWERS = {  # Part A: Jev chooses one
    "yes": "Fully true",
    "partly": "True only in part, or true but missing something a learner would notice",
    "no": "Not true",
    "cannot_judge": "The text given isn't enough to judge this",
}

# Part A, for each concept. `paper`: whether the question needs the paper excerpts.
PART_A = {
    "A1": {"paper": True, "name": "Quote supports",
           "ask": "Read in its context in the paper excerpt, does the concept's quote support the main claim of its explanation?"},
    "A2": {"paper": True, "name": "Model is faithful",
           "ask": "Does the concept's model behave like the mechanism the paper excerpt describes: the direction of each effect when a control rises, "
                  "its shape (linear, saturating, threshold, growth rate) and which variables matter? Simplifications the model's note labels are fine."},
    "A3": {"paper": True, "name": "Note is honest",
           "ask": "Does the model's note say how the model is simplified and whether its numbers are illustrative or the paper's, with any numbers "
                  "the paper reports quoted correctly and no invented number presented as a finding?"},
    "A4": {"paper": False, "name": "Taught before tested",
           "ask": "Are the idea's tour and explanation clear enough that a learner could attempt the goals and the 'Use it' question without guessing?"},
    "A5": {"paper": False, "name": "Goals need the idea",
           "ask": "Does reaching each goal require using the concept, rather than moving sliders at random or reading the answer from the goal or an "
                  "early hint, with hints that get more specific and give the answer only in the last one?"},
    "A6": {"paper": False, "name": "Questions are fair",
           "ask": "Is the 'Use it' question a genuinely new case rather than a repeat of the walkthrough, answerable from what was taught, with one "
                  "clearly correct answer, plausible wrong options and a correct reason for each?"},
}

# Part C, for each concept: is there a critical error of this kind? (yes = an error was found)
CRITICAL = {
    "wrong_claim": "Does anything in this concept (explanation, narration, hints, note, recap) state that the paper found or argued something "
                   "the paper excerpt doesn't support, or teach something it contradicts?",
    "reversed_model": "Does the model, or any part of it a learner is shown, behave differently from what the paper excerpt says: an effect in "
                      "the wrong direction, the wrong growth rate (for example logarithmic where the paper says linear) or the wrong rule?",
    "fabricated_finding": "Does the concept present a number or result as the paper's finding when the paper excerpt doesn't contain it?",
    "misleading_quote": "Read in its context in the paper excerpt, does the quote say something different from what the concept uses it for?",
}
WRONG_ANSWER = ("Is the answer this exercise marks as correct actually wrong, given the model and what the concept teaches?")

# Part B, for the whole lesson: concrete checks per dimension (yes = passed). The score is the share passed.
PART_B = {
    "B1": {"paper": True, "name": "The paper in brief is faithful", "checks": [
        "Does the paper in brief state the question the paper asks, as the paper does?",
        "Does it say what the researchers did, as the paper describes it?",
        "Does it state the paper's main finding correctly?",
        "Does it say why the finding matters, without claiming more than the paper does?",
        "Does it keep the paper's own hedges and limitations?",
        "Is every result it reports one the paper actually reports?",
    ]},
    "B2": {"paper": True, "name": "Coverage", "checks": [
        "Do the concepts teach the paper's main contribution?",
        "Do they include the supporting ideas a reader needs to understand that contribution?",
        "Does each concept come after the ones it builds on?",
        "Was nothing central to the paper left out, including among the concepts listed as omitted?",
        "Do the concepts stay on what the paper is about rather than side topics?",
    ]},
    "B3": {"paper": False, "name": "Teaching", "checks": [
        "Does each concept carry one main idea?",
        "Is each idea shown on its model and explained before the learner is asked to do anything?",
        "Do the explanations build intuition for why, not only state conclusions?",
        "Do the narrated tours and walkthroughs refer to what the model actually shows?",
        "Would a learner who finished the lesson be able to explain the main idea in their own words?",
    ]},
    "B4": {"paper": False, "name": "Practice", "checks": [
        "Does every goal and question require using the idea it belongs to?",
        "Does at least one exercise apply an idea to a new situation not shown in the walkthrough?",
        "Do goal texts avoid stating the value or setting that reaches them?",
        "Do hints hold back the answer until the last one?",
        "Are the wrong options in questions mistakes a real learner might make?",
    ]},
    "B5": {"paper": True, "name": "Honesty", "checks": [
        "Are the models' simplifications labelled in their notes?",
        "Are the paper's caveats and limitations kept?",
        "Would a learner come away with the paper's real level of certainty, not more?",
        "If concepts were left out, does the lesson say so?",
        "Are invented example numbers clearly kept apart from the paper's findings?",
    ]},
    "B6": {"paper": False, "name": "Clear for the audience", "checks": [
        "Is the language right for the stated audience?",
        "Is each technical term defined where it first appears or in the concept's terms?",
        "Are sentences short and direct?",
        "Could the audience follow every screen without looking anything up?",
    ]},
}

# The verdict comes from rules, not from another question (see verdict() in jev_judge.py).
B_PASS = 0.8  # a Part B dimension under this share of checks passed needs fixes
