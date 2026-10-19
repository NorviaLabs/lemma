# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary: the curious learner.** Someone who has 15–30 minutes and wants to understand a complex concept by seeing it work, without first taking a course: how attention works in a transformer, why loss aversion bends choices, how herd immunity tips. They arrive with a question or with a source (a paper, an article, a chapter). They are a visual learner with no special background in the field. When the needs of different users conflict, this person wins.

Secondary users, all served but never at the primary user's expense:
- **Students** building intuition for a concept or an assigned paper and checking their understanding.
- **Educators** preparing an interactive handout for a class, editing it, and sharing it before a seminar.
- **Researchers** explaining their own work or field to a wider audience.

**Distribution:** open source (MIT), in two forms. A hosted OpenLemma at openlemma.org, where learners sign in with Google and bring their own AI provider key; and a local OpenLemma that developers and curious learners run on their own computers. A stranger's first visit or first run therefore matters, including signing in or installing, connecting an AI provider, and getting to a first lesson.

## Product Purpose

OpenLemma teaches complex concepts visually. A learner asks about a concept or brings a source, and gets a short hands-on lesson: a brief story of the idea, then each mechanism shown and explained on a live model they can move, then practice on that model. Quizzes are kept for the hardest ideas. Asking about a concept and bringing a source are equal ways in; a research paper is one kind of source among encyclopedias, textbooks and articles.

Text explanations and summaries tell a learner the conclusion, but a mechanism is understood by watching it change. Hand-built interactive explainers do this well, but take experts days and exist for very few ideas. OpenLemma makes one for any concept in minutes while staying honest about what its sources say.

Success means a learner who finishes a lesson has seen each mechanism change under their own hands, can pass the checks, and knows which source each idea comes from. The spec's measures: lessons pass quality checks without manual edits (≥ 80%), quotes support their explanations (≥ 90%), models represent the mechanism correctly (≥ 85%), and learners reach goals without **Show me** (≥ 60%).

## Positioning

- **Visual first.** Every idea is something the learner sees and moves, not a paragraph to read; the visual is the explanation, with words in support.
- **Teach first, then practise.** The idea's story comes before any exhibit, and every concept shows and explains its idea before asking the learner to do anything with it.
- **Live, checked models.** The models respond to input. Lemma proves every goal is reachable before a learner sees it, using one model engine implemented identically in the browser and on the server.
- **Grounded.** Every concept quotes a real source word for word, and OpenLemma verifies the quote appears in that source. This holds for concept lessons too: OpenLemma finds the sources and teaches from them, not from the model's memory.
- **Any discipline.** Agent simulations, networks, causal diagrams and sampling exist for the softer sciences, not only curves for maths and computer science.
- **Private, and the learner's own key.** Lessons are built with the learner's own AI provider key, which OpenLemma never stores. OpenLemma can run on the learner's own computer, and a saved lesson works offline.

OpenLemma is independent and not affiliated with Brilliant.org or 3Blue1Brown. Its lesson flow borrows Brilliant's interaction pattern; its look does not borrow either brand.

## Operating Context

- A Python web app that behaves the same on your own computer as hosted: an account, profile and library per person, the same limits (at most two builds running per account) and the same pages. People sign in with Google either way. Hosted, it runs in Docker behind a Cloudflare Tunnel (see `deploy/README.md`); locally, `uv run lemma --dev` serves it only to 127.0.0.1. The one local-only feature is the ChatGPT subscription.
- Two equal ways in: ask about a concept, and OpenLemma searches for complementary sources to teach from; or bring sources: any mix of links (arXiv links become PDFs), PDFs, saved web pages and text files, up to ten per lesson (five of them files), woven into one lesson. Either way the learner says who the explanation is for.
- Lessons are built with the learner's own key for OpenCode Go, OpenAI or Claude, chosen on the account page, or, on your own computer only, a ChatGPT Plus or Pro sign-in. The browser keeps the key and sends it with each request. Models are called with no tools, so they can only read what Lemma sends and reply with text.
- The journey: ask about a concept and select complementary sources, or bring a source → asynchronously read sources and propose an outline → review and edit the outline → watch resumable build progress with an estimated time range → start learning while later concepts are still building → automatically save the completed lesson or download one offline HTML file. Source selections remain editable before starting; recommendations are a starting point, not a completeness guarantee.
- Multi-source lessons weave core ideas and prerequisites into one standard-depth lesson. Quotes are checked against their identified source; explanations identify supporting sources. Meaningful disagreements and uncertainty are explained rather than flattened into consensus. Deeper topics are suggested for follow-up.
- Build requests and progress persist privately. Leaving the page does not cancel work. Server restarts mark running builds interrupted for explicit retry; credentials are never persisted in requests. Unreadable sources produce warnings, and no readable sources is a failure. Cancel, retry and delete are available from the build/library flow.
- Educators and researchers can edit a lesson; every save re-runs the quality checks.

## Capabilities and Constraints

- **Quality checks are a gate:** structure, word-for-word grounding, models that evaluate to finite numbers across their ranges, and goals that are false at the start and true at a reachable solution. A lesson that fails is never shown; a concept that can't be fixed is left out, and the lesson says so.
- **Visual types:** curves, tables, bars, agent simulations, networks, causal diagrams, sampling and geometry. Check formats: put the model into a state, multiple choice, true/false, select all that apply, numeric, and ordering.
- **Honesty:** models are labelled as simplified teaching models, and invented numbers are never presented as findings. Every lesson reminds the learner that generated lessons can contain errors.
- **Privacy:** no request logs, no tracking cookies, no advertising. A hosted OpenLemma stores its data on a Google Cloud server in us-central1 and keeps the account details needed to sign in, per-account daily usage counts for limits (deleted after seven days), and anonymous per-day event totals with no account or lesson attached; page views are counted by cookieless Cloudflare Web Analytics (`lemma/static/privacy.html`). Error reports name where Lemma broke, never the request, the paper or a key. Source text goes only to the provider named before building, and, since every search and build needs the server's TypeSafe key, the title and opening text of each source go to TypeSafe to sort the lesson into a subject category, a search's words and results (titles and abstracts) go to TypeSafe to rank and recommend results, and each drafted concept with the source passages it is about goes to TypeSafe to check it for critical errors before a learner sees it. A topic search sends the search words to Wikipedia, the Stanford Encyclopedia of Philosophy, LibreTexts, OpenAlex, Europe PMC and arXiv. Downloaded lessons make no network requests, including for fonts, and send nothing anywhere.
- **Non-goals:** social features, guaranteeing scientific accuracy, reproducing a source's data or figures, replacing the sources, and teaching from the model's memory without sources.
- **Daily limits:** per account per day, 40 searches, 20 outlines or builds and 100 sources read by default, the safe caps openlemma.org uses. They are configuration: `local.env` lifts them for development with `unlimited`. At most 120 requests that change something per visitor address every 10 minutes, everywhere.
- **Limits:** sources must fit the chosen model's context; OpenCode Go and Claude take about 1M tokens. Sources must have extractable text; scanned PDFs are refused. Files are limited to 40 MB.
- **Undecided:** custom models when no visual type fits, explaining a selected passage, spaced review of earlier concepts, lessons in other languages, and the evaluation set and reviewers.

## Brand Commitments

- **Name:** OpenLemma, at openlemma.org. The rename is brand-only: the Python package, the `lemma` command, `LEMMA_*` settings and the repository keep the name `lemma`.
- **Voice:** plain language, with short, clear sentences that keep scientific caveats rather than simplifying them away. Honest about limits and progress (no fake percentages). Encouraging when a learner is wrong.
- **Independence:** never imply affiliation with Brilliant.org or 3Blue1Brown, and don't use their names, logos or assets in the product.

## Evidence on Hand

- The built-in example lesson, from Galton's 1886 "Regression towards Mediocrity in Hereditary Stature" (public domain), with its source text: `lemma/examples/gallery/galton-1886.json` and `galton-1886.txt`.
- Real generation runs on that paper through both OpenCode Go and Codex, each passing the quality checks on the first draft.
- There are no users, testimonials, measured learning outcomes, benchmark results, adoption numbers or press yet. Don't fabricate any; the success measures above are targets, not results.

## Product Principles

1. **See it to understand it.** A complex concept is taught through visuals the learner manipulates; text supports the visual, never replaces it.
2. **Teach first, then practise.** Explanation on a live model comes before goals and questions, on every concept.
3. **Never show what hasn't been checked.** Honesty about the sources, the model's simplifications and the build's progress outranks polish or speed.
4. **One idea at a time.** Each concept and each screen carries a single mechanism or action.
5. **The learner's key, the learner's data.** Private, offline-capable once saved, with no hidden network traffic, whether hosted or on the learner's own computer.
6. **A stranger can get there.** The path from first visit or install to a first lesson must work for someone who has never seen OpenLemma.

## Accessibility & Inclusion

Target: **WCAG 2.2 AA**. On top of that, the product spec requires:
- every interaction to work with a keyboard, with nothing relying on drag-and-drop alone;
- values shown as text as well as colour, with a colour-blind-safe palette;
- reduced motion honoured, giving instant changes instead of animation;
- layouts that work on phones, with the model next to the step it belongs to.
