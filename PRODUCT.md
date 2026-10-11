# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary: the curious learner.** Someone outside a paper's field who has 15–30 minutes and a link to a paper, and wants to understand it without first taking a course. For example, an engineer reading a behavioural economics paper on loss aversion. They are a visual learner with no special background. When the needs of different users conflict, this person wins.

Secondary users, all served but never at the primary user's expense:
- **Students** building intuition for an assigned paper and checking their understanding.
- **Educators** preparing an interactive handout for a class, editing it, and sharing it before a seminar.
- **Researchers** explaining their own work to a wider audience, alongside the paper.

**Distribution:** open source. Other people install and run Lemma on their own computers: developers, and curious learners willing to run a local app. A stranger's first run therefore matters, including install, connecting an AI provider, and getting to a first lesson.

## Product Purpose

Lemma turns a research paper, from any discipline, into a short hands-on lesson. The learner hasn't read the paper, so Lemma teaches first: a short "paper in brief", then each idea shown and explained on a live model, then practice on that model. Quizzes are kept for the hardest ideas.

Summaries make a paper shorter but not easier, because the reader still receives conclusions passively. Hand-built interactive explainers work, but take experts days and exist for very few papers. Lemma makes an interactive lesson for any paper in minutes while staying honest about what the paper says.

Success means a learner who finishes a lesson has seen each mechanism change under their own hands, can pass the checks, and knows where in the paper each idea comes from. The spec's measures: lessons pass quality checks without manual edits (≥ 80%), quotes support their explanations (≥ 90%), models represent the mechanism correctly (≥ 85%), and learners reach goals without **Show me** (≥ 60%).

## Positioning

- **Teach first, then practise.** The paper's story comes before any exhibit, and every concept shows and explains its idea before asking the learner to do anything with it.
- **Live, checked models.** The models respond to input. Lemma proves every goal is reachable before a learner sees it, using one model engine implemented identically in the browser and on the server.
- **Grounded.** Every concept quotes the paper word for word, and Lemma verifies the quote appears in the source.
- **Any discipline.** Agent simulations, networks, causal diagrams and sampling exist for the softer sciences, not only curves for maths and computer science.
- **Private and local.** Lemma runs on the learner's own computer, uses AI tools they already have installed, and works offline once a lesson is saved.

Lemma is independent and not affiliated with Brilliant.org or 3Blue1Brown. Its lesson flow borrows Brilliant's interaction pattern; its look does not borrow either brand.

## Operating Context

- Runs locally as a Python web app (`uv run lemma`, or `uv run lemma --dev` with hot reload), served only to 127.0.0.1 and opened in the browser.
- The learner brings a paper as a link (arXiv links become PDFs), a PDF, a saved web page or a text file, and says who the explanation is for.
- Lessons are built by an AI tool the learner already has installed and signed in: OpenCode Go through the local OpenCode, or Codex through the local Codex CLI, chosen in Settings. Lemma locks either down so the model can only read what Lemma sends and reply with text.
- The journey: search a topic and pick a resource, or bring a paper → review and edit the outline → watch the honest build progress → start learning while later concepts are still building → finish summary → save to the library or download one offline HTML file.
- Educators and researchers can edit a lesson; every save re-runs the quality checks.

## Capabilities and Constraints

- **Quality checks are a gate:** structure, word-for-word grounding, models that evaluate to finite numbers across their ranges, and goals that are false at the start and true at a reachable solution. A lesson that fails is never shown; a concept that can't be fixed is left out, and the lesson says so.
- **Visual types:** curves, tables, bars, agent simulations, networks, causal diagrams, sampling and geometry. Check formats: put the model into a state, multiple choice, true/false, select all that apply, numeric, and ordering.
- **Honesty:** models are labelled as simplified teaching models, and invented numbers are never presented as findings. Every lesson reminds the learner that generated lessons can contain errors.
- **Privacy:** no accounts, no usage logs, no telemetry. Paper text goes only to the provider named before building. A topic search sends only the search words, to OpenAlex, arXiv and Wikipedia. Downloaded lessons make no network requests, including for fonts, and send nothing anywhere.
- **Non-goals:** public hosting or social features, guaranteeing scientific accuracy, reproducing a paper's data or figures, and replacing the paper.
- **Limits:** Codex models take a 272k-token context, so long papers need OpenCode Go. Papers must have extractable text; scanned PDFs are refused.
- **Undecided** (open questions in `docs/product-spec.md`): custom models when no visual type fits, explaining a selected passage, spaced review of earlier concepts, lessons in other languages, and the evaluation set and reviewers.

## Brand Commitments

- **Name:** Lemma.
- **Voice:** plain language, with short, clear sentences that keep scientific caveats rather than simplifying them away. Honest about limits and progress (no fake percentages). Encouraging when a learner is wrong.
- **Independence:** never imply affiliation with Brilliant.org or 3Blue1Brown, and don't use their names, logos or assets in the product.

## Evidence on Hand

- The built-in example lesson, from Galton's 1886 "Regression towards Mediocrity in Hereditary Stature" (public domain), with its source text: `lemma/examples/galton-1886.json` and `galton-1886.txt`.
- Real generation runs on that paper through both OpenCode Go and Codex, each passing the quality checks on the first draft.
- The full product spec: `docs/product-spec.md`.
- There are no users, testimonials, measured learning outcomes, benchmark results, adoption numbers or press yet. Don't fabricate any; the success measures above are targets, not results.

## Product Principles

1. **Teach first, then practise.** Explanation on a live model comes before goals and questions, on every concept.
2. **Never show what hasn't been checked.** Honesty about the paper, the model's simplifications and the build's progress outranks polish or speed.
3. **One idea at a time.** Each concept and each screen carries a single mechanism or action.
4. **The learner's computer, the learner's data.** Local, private, offline-capable, with no hidden network traffic.
5. **A stranger can get there.** As an open-source tool, the path from install to a first lesson must work for someone who has never seen Lemma.

## Accessibility & Inclusion

Target: **WCAG 2.2 AA**. On top of that, the product spec requires:
- every interaction to work with a keyboard, with nothing relying on drag-and-drop alone;
- values shown as text as well as colour, with a colour-blind-safe palette;
- reduced motion honoured, giving instant changes instead of animation;
- layouts that work on phones, with the model next to the step it belongs to.
