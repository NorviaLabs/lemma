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

**Distribution:** open source (MIT), in two forms. A hosted Lemma at tools.mohitranka.com/lemma, where learners sign in with Google or GitHub and bring their own AI provider key; and a local Lemma that developers and curious learners run on their own computers. A stranger's first visit or first run therefore matters, including signing in or installing, connecting an AI provider, and getting to a first lesson.

## Product Purpose

Lemma turns a research paper, from any discipline, into a short hands-on lesson. The learner hasn't read the paper, so Lemma teaches first: a short "paper in brief", then each idea shown and explained on a live model, then practice on that model. Quizzes are kept for the hardest ideas.

Summaries make a paper shorter but not easier, because the reader still receives conclusions passively. Hand-built interactive explainers work, but take experts days and exist for very few papers. Lemma makes an interactive lesson for any paper in minutes while staying honest about what the paper says.

Success means a learner who finishes a lesson has seen each mechanism change under their own hands, can pass the checks, and knows where in the paper each idea comes from. The spec's measures: lessons pass quality checks without manual edits (≥ 80%), quotes support their explanations (≥ 90%), models represent the mechanism correctly (≥ 85%), and learners reach goals without **Show me** (≥ 60%).

## Positioning

- **Teach first, then practise.** The paper's story comes before any exhibit, and every concept shows and explains its idea before asking the learner to do anything with it.
- **Live, checked models.** The models respond to input. Lemma proves every goal is reachable before a learner sees it, using one model engine implemented identically in the browser and on the server.
- **Grounded.** Every concept quotes the paper word for word, and Lemma verifies the quote appears in the source.
- **Any discipline.** Agent simulations, networks, causal diagrams and sampling exist for the softer sciences, not only curves for maths and computer science.
- **Private, and the learner's own key.** Lessons are built with the learner's own AI provider key, which Lemma never stores. Lemma can run on the learner's own computer, and a saved lesson works offline.

Lemma is independent and not affiliated with Brilliant.org or 3Blue1Brown. Its lesson flow borrows Brilliant's interaction pattern; its look does not borrow either brand.

## Operating Context

- A Python web app. Hosted, it runs in Docker behind a Cloudflare Tunnel, with an account, profile and library per person, and at most two builds running per account (see `deploy/README.md`). Locally, `uv run lemma` (or `uv run lemma --dev` with hot reload) serves it only to 127.0.0.1 and opens the browser.
- The learner brings a paper as a link (arXiv links become PDFs), a PDF, a saved web page or a text file, and says who the explanation is for.
- Lessons are built with the learner's own key for OpenCode Go, OpenAI or Claude, chosen in Settings; locally, a ChatGPT Plus or Pro sign-in also works. The browser keeps the key and sends it with each request. Models are called with no tools, so they can only read what Lemma sends and reply with text.
- The journey: search a topic and select complementary sources, or bring a paper → asynchronously read sources and propose an outline → review and edit the outline → watch resumable build progress with an estimated time range → start learning while later concepts are still building → automatically save the completed lesson or download one offline HTML file. Source selections remain editable before starting; recommendations are a starting point, not a completeness guarantee.
- Multi-source lessons weave core ideas and prerequisites into one standard-depth lesson. Quotes are checked against their identified source; explanations identify supporting sources. Meaningful disagreements and uncertainty are explained rather than flattened into consensus. Deeper topics are suggested for follow-up.
- Build requests and progress persist privately. Leaving the page does not cancel work. Server restarts mark running builds interrupted for explicit retry; credentials are never persisted in requests. Unreadable sources produce warnings, and no readable sources is a failure. Cancel, retry and delete are available from the build/library flow.
- Educators and researchers can edit a lesson; every save re-runs the quality checks.

## Capabilities and Constraints

- **Quality checks are a gate:** structure, word-for-word grounding, models that evaluate to finite numbers across their ranges, and goals that are false at the start and true at a reachable solution. A lesson that fails is never shown; a concept that can't be fixed is left out, and the lesson says so.
- **Visual types:** curves, tables, bars, agent simulations, networks, causal diagrams, sampling and geometry. Check formats: put the model into a state, multiple choice, true/false, select all that apply, numeric, and ordering.
- **Honesty:** models are labelled as simplified teaching models, and invented numbers are never presented as findings. Every lesson reminds the learner that generated lessons can contain errors.
- **Privacy:** no usage logs, no analytics, no telemetry. A hosted Lemma keeps only the account details needed to sign in (`lemma/static/privacy.html`). Error reports name where Lemma broke, never the request, the paper or a key. Paper text goes only to the provider named before building, and, where the server has a TypeSafe key (the hosted Lemma does), the title and opening text of each source go to TypeSafe to sort the lesson into a subject category, a search's words and results (titles and abstracts) go to TypeSafe to rank and recommend results, and each drafted concept with the source passages it is about goes to TypeSafe to check it for critical errors before a learner sees it. A topic search sends the search words to Wikipedia, the Stanford Encyclopedia of Philosophy, LibreTexts, OpenAlex, Europe PMC and arXiv. Downloaded lessons make no network requests, including for fonts, and send nothing anywhere.
- **Non-goals:** social features, guaranteeing scientific accuracy, reproducing a paper's data or figures, and replacing the paper.
- **Limits:** a paper must fit the chosen model's context; OpenCode Go and Claude take about 1M tokens. Papers must have extractable text; scanned PDFs are refused. Files are limited to 40 MB.
- **Undecided:** custom models when no visual type fits, explaining a selected passage, spaced review of earlier concepts, lessons in other languages, and the evaluation set and reviewers.

## Brand Commitments

- **Name:** Lemma.
- **Voice:** plain language, with short, clear sentences that keep scientific caveats rather than simplifying them away. Honest about limits and progress (no fake percentages). Encouraging when a learner is wrong.
- **Independence:** never imply affiliation with Brilliant.org or 3Blue1Brown, and don't use their names, logos or assets in the product.

## Evidence on Hand

- The built-in example lesson, from Galton's 1886 "Regression towards Mediocrity in Hereditary Stature" (public domain), with its source text: `lemma/examples/galton-1886.json` and `galton-1886.txt`.
- Real generation runs on that paper through both OpenCode Go and Codex, each passing the quality checks on the first draft.
- There are no users, testimonials, measured learning outcomes, benchmark results, adoption numbers or press yet. Don't fabricate any; the success measures above are targets, not results.

## Product Principles

1. **Teach first, then practise.** Explanation on a live model comes before goals and questions, on every concept.
2. **Never show what hasn't been checked.** Honesty about the paper, the model's simplifications and the build's progress outranks polish or speed.
3. **One idea at a time.** Each concept and each screen carries a single mechanism or action.
4. **The learner's key, the learner's data.** Private, offline-capable once saved, with no hidden network traffic, whether hosted or on the learner's own computer.
5. **A stranger can get there.** The path from first visit or install to a first lesson must work for someone who has never seen Lemma.

## Accessibility & Inclusion

Target: **WCAG 2.2 AA**. On top of that, the product spec requires:
- every interaction to work with a keyboard, with nothing relying on drag-and-drop alone;
- values shown as text as well as colour, with a colour-blind-safe palette;
- reduced motion honoured, giving instant changes instead of animation;
- layouts that work on phones, with the model next to the step it belongs to.
