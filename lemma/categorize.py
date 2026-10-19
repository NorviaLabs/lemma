"""Sorts a lesson into a fixed list of subject categories, read from the start of its sources.

Jev (see jev.py) answers a choice question with a probability for every option. Every lesson is sorted: a build
doesn't start without Jev, and stops if Jev can't sort it. Only each source's title and opening text are sent.
"""

from __future__ import annotations

from . import jev
from . import lesson as L

TIMEOUT = 20
STATE_CHARS = 60_000  # about 15k tokens of source text, well inside Jev's 32k per question
SECOND_AT = 0.25  # a runner-up this likely is kept as the lesson's second category

# id: (name, what belongs in it). The descriptions are Jev's rubric, so they name what each category covers.
CATEGORIES = {
    "mathematics": ("Mathematics", "Pure and applied mathematics: algebra, analysis, geometry, topology, number theory, logic, combinatorics"),
    "statistics": ("Statistics & probability", "Probability, statistical inference, causal inference, survey methods, data analysis"),
    "computer_science": ("Computer science", "Algorithms, complexity, programming languages, systems, networks, databases, security, cryptography"),
    "ai_ml": ("AI & machine learning", "Machine learning, deep learning, neural networks, language models, computer vision, robotics, AI safety"),
    "physics_astronomy": ("Physics & astronomy", "Mechanics, quantum physics, relativity, particle and condensed-matter physics, optics, astronomy, cosmology"),
    "chemistry": ("Chemistry", "Organic, inorganic, physical and analytical chemistry, biochemistry's chemical side, chemical reactions"),
    "earth_climate": ("Earth & climate science", "Geology, oceanography, atmosphere and weather, climate change, environmental science, natural hazards"),
    "engineering": ("Engineering & technology", "Electrical, mechanical, civil, chemical and aerospace engineering, energy systems, materials science"),
    "biology": ("Biology", "Cell and molecular biology, genetics, genomics, microbiology, physiology, developmental biology"),
    "ecology_evolution": ("Ecology & evolution", "Evolution, natural selection, populations, species interactions, biodiversity, conservation"),
    "neuroscience": ("Neuroscience", "The brain and nervous system, neurons, perception, memory and cognition studied biologically"),
    "agriculture_food": ("Agriculture & food", "Crops, farming, soil, livestock, veterinary science, food science, nutrition"),
    "medicine": ("Medicine", "Disease, diagnosis, treatment, clinical trials, drugs and pharmacology, surgery, nursing, dentistry"),
    "public_health": ("Public health & epidemiology", "How disease spreads in populations, epidemics, vaccination, health risks, health policy and systems"),
    "psychology": ("Psychology", "Behaviour and mind: cognitive, social, developmental, clinical and personality psychology, decision-making"),
    "economics": ("Economics & finance", "Markets, prices, incentives, macroeconomics, behavioural economics, finance, trade, inequality"),
    "business": ("Business & management", "Firms, strategy, management, marketing, operations, accounting, entrepreneurship"),
    "political_science": ("Political science", "Government, elections, public policy, international relations, war and conflict, political theory"),
    "law": ("Law", "Legal systems, constitutions, courts, criminal and civil law, regulation, legal theory"),
    "sociology_anthropology": ("Sociology & anthropology", "Society, social groups and networks, culture, demography, inequality, ethnography"),
    "education": ("Education", "Teaching, learning, schools, curricula, educational policy and assessment"),
    "geography_urban": ("Geography & urban studies", "Places and regions, cities, migration, transport, land use, spatial analysis"),
    "communication_media": ("Communication & media", "Journalism, mass and social media, information science, libraries, persuasion, misinformation"),
    "history_archaeology": ("History & archaeology", "The human past in any period or region, historical events and sources, archaeology"),
    "philosophy": ("Philosophy & ethics", "Epistemology, metaphysics, philosophy of mind and science, philosophical logic, ethics, aesthetics"),
    "religion": ("Religion & theology", "Religions, religious texts and practice, theology, history of religion"),
    "linguistics": ("Linguistics & languages", "Language structure, sounds, grammar, meaning, language acquisition, sociolinguistics"),
    "literature": ("Literature", "Novels, poetry, drama, literary criticism and literary history"),
    "arts_design": ("Arts, music & design", "Visual arts, art history, music, film, theatre, architecture, design"),
    "research_methods": ("Research methods & science of science", "How research is done and judged: reproducibility, peer review, p-values in practice, meta-research"),
    "other": ("Other", "Fits none of the categories above"),
}


CategorizeError = jev.JevError


def _state(paper: dict) -> list[dict]:
    """Each source's title and opening text, sharing STATE_CHARS between them."""
    sources = list(L.source_map(paper.get("text")).values()) or [{"title": paper.get("title", ""), "text": paper.get("text", "")}]
    each = STATE_CHARS // len(sources)
    return [{"title": s.get("title", ""), "text": (s.get("text") or "")[:each]} for s in sources]


def _named(cid: str) -> dict:
    return {"id": cid, "name": CATEGORIES[cid][0]}


def categorize(paper: dict) -> dict:
    """The lesson's category from its sources: a primary, an optional secondary, and Jev's probabilities."""
    answers = jev.ask({"sources": _state(paper)}, {"category": {
        "type": "choice",
        "instructions": "Which subject do these sources mainly belong to? Judge by what they explain, not where they were published.",
        "criteria": {cid: desc for cid, (_, desc) in CATEGORIES.items()}}}, TIMEOUT)
    try:
        answer = answers["category"]
        probs = {k: float(v) for k, v in answer["probabilities"].items() if k in CATEGORIES}
        primary = answer["choice"]
        if primary not in CATEGORIES:
            raise KeyError(primary)
    except (KeyError, TypeError, ValueError):
        raise CategorizeError("the checking service sent a reply OpenLemma couldn't read") from None
    second = max((k for k in probs if k not in (primary, "other")), key=probs.get, default=None)
    return {
        "primary": _named(primary),
        "secondary": _named(second) if second and probs[second] >= SECOND_AT else None,
        "probabilities": {k: round(v, 3) for k, v in sorted(probs.items(), key=lambda kv: -kv[1]) if v >= .001},
        "confidence": round(float(answer.get("confidence") or 0), 3),
        "model": answers["_model"],
    }
