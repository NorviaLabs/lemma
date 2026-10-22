"""How much the learner already knows: one of three fixed levels, read the same way by prompts, Jev and the browser."""

from __future__ import annotations

# id: (name, what the learner knows and how to teach them). The descriptions are the rubric the model and Jev read.
LEVELS = {
    "beginner": ("Beginner", "no background in this field; define every term and use examples from everyday life"),
    "intermediate": ("Intermediate", "knows the field's basics and vocabulary, about one introductory course; remind them of prerequisites briefly"),
    "advanced": ("Advanced", "has studied or works in the field; skip the basics and go to the source's details, methods and caveats"),
}
DEFAULT = "beginner"


def parse(value) -> str | None:
    """The level id for a value from a request, ``DEFAULT`` when none was given, None when it isn't a level."""
    if value in (None, ""):
        return DEFAULT
    return value if value in LEVELS else None


def describe(level: str | None) -> str:
    name, rubric = LEVELS.get(level or DEFAULT, LEVELS[DEFAULT])
    return f"{name}: {rubric}"
