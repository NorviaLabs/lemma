<img src="lemma/static/logo.svg" alt="" width="56" height="56">

# OpenLemma

OpenLemma teaches complex concepts visually. Ask about a concept, or bring a paper, article or chapter, and it builds a short, hands-on lesson: the idea in brief, then for each idea a live model that shows how it works, an explanation with an exact quote from a real source, and then you try it yourself. For a concept, it finds encyclopedias, textbooks and papers to teach from; every quote is checked against its source. It runs at [openlemma.org](https://openlemma.org), or on your own computer. Who it is for and what it promises are in [`PRODUCT.md`](PRODUCT.md), and the visual design system is in [`DESIGN.md`](DESIGN.md). OpenLemma is open source under the [MIT License](LICENSE); the code, package and command are still called `lemma`.

Try it at [openlemma.org](https://openlemma.org), or run your own copy.

## Quick start

You need [uv](https://docs.astral.sh/uv/) and a copy of this repository.

```sh
git clone https://github.com/NorviaLabs/lemma && cd lemma
uv run lemma                 # installs what's needed on first run, then opens http://localhost:8765
```

Signing in needs a Google OAuth client of your own, and development runs with `set -a; . ./local.env; set +a` first; [What you need](#what-you-need) has the details.

The built-in example lesson (Galton, 1886) and the gallery work straight away, with no setup. Signing in, searching and building need keys of your own; [What you need](#what-you-need) lists them.

To make your own lessons, OpenLemma needs your own key for an AI provider, and the server needs a TypeSafe key (`TYPESAFE_API_KEY`) for Jev's checks (see [Run it](#run-it)). The home page asks for one:

| | Get a key | Fits |
|---|---|---|
| **OpenCode Go** | [opencode.ai/auth](https://opencode.ai/auth) (needs an OpenCode Go plan) | Long papers (about 1M tokens) |
| **OpenAI** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | Depends on the model |
| **Claude** | [platform.claude.com/settings/keys](https://platform.claude.com/settings/keys) | Long papers (about 1M tokens) |
| **ChatGPT** | No key: sign in with your ChatGPT Plus or Pro account. Only when Lemma runs on your own computer | Depends on the model |

Ask about a concept and choose multiple sources, paste a link, or upload a PDF. Search results suggest an overview and up to two relevant papers only after downloading and checking readable full text; blocked copies are skipped in favor of readable alternatives. Checks are cached for five minutes, so availability can still change. You can change every selection. Lemma creates one combined lesson, attributes its evidence to individual sources, and asks the model to explain meaningful disagreements.

Creation runs in the background. Review the proposed outline, then watch concept-by-concept progress and an approximate time range once enough work has completed. You can start checked concepts early, leave the page, and return through the build's link or the Library. Completed lessons save automatically. Unreadable sources are listed as warnings; creation fails if none can be read.

Requests, source text, and progress are stored privately under `LEMMA_HOME` (by default `~/.lemma`). Credentials are never written into build records. Server restarts mark active builds interrupted rather than resuming them automatically; retry uses your current provider credentials. You can cancel running builds, retry stopped builds with the same selections, and delete stopped builds or saved lessons from the library.

Source text has no application-level word or character cap and is never silently truncated. The 40 MB file limit and the selected AI model's context limit still apply; if the model rejects the input as too long, choose a model with a larger context in Settings.

## Run it

Searching and building lessons need a TypeSafe key for Jev's checks: start Lemma with `TYPESAFE_API_KEY` set (for example `TYPESAFE_API_KEY=... uv run lemma`). Without it, the gallery, library and downloads still work, and Lemma says why search and building are off. `uv run lemma --port 9000 --no-browser` changes the port or skips opening a browser. In Settings, pick the provider, paste its key and choose a model. The model list is read live with your key; the defaults are `gpt-5.6-luna` for OpenCode Go and `gpt-6.1-sol` for OpenAI.

### How Lemma uses your key

Both providers are called over their OpenAI-compatible chat completions APIs (`https://opencode.ai/zen/go/v1` and `https://api.openai.com/v1`), with no tools, so the model can only read what Lemma sends and reply with text. Your browser keeps your provider, model and key, and sends them with each request in `X-Lemma-*` headers. The server uses the key for that request, or for the build it starts, and never writes it to disk or sends it back. The APIs keep no conversation, so a repair re-sends the paper, the earlier draft and the list of problems. OpenCode Go requests also carry a random `x-opencode-session` id, the same for a draft and its repairs, which OpenCode uses to route them together and cache the paper.

### How Lemma uses Claude

Claude is called through Anthropic's Python SDK with your key, streaming each reply, with adaptive thinking and high effort where the model offers it. The model list shows the models that support adaptive thinking; the default is `claude-opus-5-5`. A repair re-sends the paper, so the request is marked for prompt caching to make that repeat cheap, and Claude's earlier replies go back exactly as it sent them. On models that support it, a request Claude's safety checks decline is retried on the model Anthropic recommends for that case (`fallbacks: "default"`); if it is still declined, that concept is left out and the lesson says so.

### How Lemma uses your ChatGPT subscription

This signs in the same way the Codex CLI does. **Sign in with ChatGPT** on your account page opens OpenAI's sign-in page, which sends you back to `http://localhost:1455/auth/callback`; Lemma listens there only while you sign in. Your tokens are kept in `~/.lemma/chatgpt-auth.json`, readable only by you, and refreshed when they expire. **Sign out** deletes them. Lessons are built through the ChatGPT backend that Codex uses, with no tools, and count against your plan's usage. It is for your own use on your own computer: a hosted Lemma serving other people must not offer it.

### Host it for other people

`lemma --host 0.0.0.0 --allowed-hosts tools.example.com` (or `LEMMA_HOST` and `LEMMA_ALLOWED_HOSTS`) serves Lemma beyond this computer. A hosted Lemma answers only the domain names it is given, binds exactly `--port`, and doesn't offer ChatGPT sign-in; everything else behaves exactly as on your own computer (`tests/test_one_behaviour.py` holds that). People sign in with Google or GitHub (`lemma/auth.py`), and each account has its own profile, library, papers and builds, with at most two builds running per account. On your own computer you sign in with Google too: register `http://localhost:8765/auth/google/callback` on the OAuth client and set the same `LEMMA_GOOGLE_CLIENT_ID` and `_CLIENT_SECRET`. A library saved before accounts moves into the first account that signs in. Set `LEMMA_PUBLIC_URL` to where people reach it, such as `https://tools.example.com/lemma`: Lemma serves under that path and sends sign-ins back to `<public url>/auth/<google|github>/callback`. Each provider is offered once both its `LEMMA_<GOOGLE|GITHUB>_CLIENT_ID` and `_CLIENT_SECRET` are set. Accounts are kept in `$LEMMA_HOME/accounts.db`, and libraries in `$LEMMA_HOME/users/`. Serve it over HTTPS only, since learners' keys travel in request headers.

[`deploy/`](deploy/README.md) runs it at openlemma.org on a free Google Cloud VM behind a Cloudflare Tunnel.

## How it works

1. **Find something to learn.** Search a topic (or press **Surprise me**): Lemma lists an overview article from Wikipedia, in-depth explanations from the Stanford Encyclopedia of Philosophy and LibreTexts, open-access papers from OpenAlex and Europe PMC, and preprints from arXiv, and suggests a starting set: for an idea, an overview, an explanation and a paper; for a particular paper, the closest papers and an overview. Or paste a link (arXiv links are turned into PDF links), or upload a PDF, HTML or text file. Then say who the lesson is for. For a search result, Lemma tries each open copy of it until it finds full text it can read.
2. **Outline.** The model proposes three to six concepts. You can reorder them, remove them, or mark ones you already know.
3. **Build.** Concepts are built in parallel. Each one is checked by `lemma/lesson.py` and, if it fails, sent back with the list of problems, up to two times. A concept that still fails is left out, and the lesson says so. You can start learning as soon as the first concept is ready.
4. **Learn.** First the paper in brief: a few short pages on the question, what was done, what was found and why it matters, quoting the paper. Then each concept: Meet the model (a narrated tour) → How it works (a narrated walkthrough, then the explanation and quote) → Try it yourself (goals, with hints that get more specific and **Show me**) → Use it (a new case, with the reasoning behind every option) → Make it stick (hard concepts only: put the model into a target state, or answer a multiple-choice, true/false, numeric or ordering question) → Going further (the equation, with each coloured term linked to its control). Narrated parts play like a short video: pause, click any line to play from there, and the tour rolls on into the walkthrough. Charts leave a faint **Trail** of earlier states as they move, and the equation builds one part at a time, lighting up each part's control. They run as a focused sequence of small screens, one action each, with a segmented progress bar and a bottom bar for **Check** and **Continue** that slides up feedback, in the style of Brilliant.org lessons.
5. **Keep and share.** Save the lesson to your library (`~/.lemma`, or `$LEMMA_HOME`), edit it, or download it as one HTML file that works offline. Its Content-Security-Policy blocks all network requests.

### Quality checks (`lemma/lesson.py`)

- **Grounding:** every quote must appear word for word in the paper. The comparison ignores spacing, hyphenation and punctuation from PDF extraction.
- **Working models:** every expression is evaluated across each control's range and must give finite numbers. Every visual must be drawable.
- **Reachable goals:** each goal and model check must be false at the defaults and true at its stated solution, and the solution must sit on the slider's step grid.
- **Honest labelling:** each model needs a note saying how it is simplified and whether its numbers are illustrative.

Edits are checked the same way, so a broken lesson can't be saved or exported.

### One engine, two runtimes

Models use a small expression language (`lemma/expr.py` ⇄ `static/expr.js`) and seeded simulation kernels (`lemma/kernels.py` ⇄ `static/kernels.js`): Schelling segregation, SIR contagion, bounded-confidence opinions, network cascades, and sampling of means, two-group p-values and regression to the mean. The Python and JavaScript versions give identical results, which is what lets the server prove that a goal the browser shows can actually be reached. `tests/crosscheck.js` compares the two.

Visual types: curves, bars, tables, agent simulations, networks, causal diagrams, sampling and geometry.

## Development

### What you need

OpenLemma runs the same on your own computer as hosted, so a copy you run behaves like openlemma.org: people sign in with Google, and searching and building use keys. What works with each:

- **Nothing set up:** the home page, the gallery, the example lesson, downloads, and the tests (`uv run python -m unittest discover tests`), which use stand-ins for every outside service.
- **Signing in** (your library, searching, building) needs a Google OAuth web client of your own, from [Google Cloud](https://console.cloud.google.com/auth/clients), with `http://localhost:8765/auth/google/callback` as an authorized redirect URI. Start Lemma with `LEMMA_GOOGLE_CLIENT_ID` and `LEMMA_GOOGLE_CLIENT_SECRET` set.
- **Searching and building** also need a TypeSafe key, `TYPESAFE_API_KEY`, for Jev's checks; without it Lemma says why they are off.
- **Searching often** works better with a free OpenAlex key, `OPENALEX_API_KEY` (from [OpenAlex](https://openalex.org/settings/api)): without it, every caller at the same address shares a small daily allowance, about 100 searches, and OpenAlex results stop once it runs out.
- **Building** needs an AI provider of your own, chosen on your account page after you sign in: a key for OpenCode Go, OpenAI or Claude, or the ChatGPT subscription signed in on your computer.

For development, run one Lemma with the development config, which lifts the daily caps:

```sh
set -a; . ./local.env; . ./deploy/lemma.env; set +a
uv run lemma --dev
```

`local.env` holds no secrets and is committed. Your keys go in `deploy/lemma.env`, the same file the server reads: copy `deploy/lemma.env.example` and fill in `LEMMA_GOOGLE_CLIENT_ID`, `LEMMA_GOOGLE_CLIENT_SECRET` and `TYPESAFE_API_KEY`, and optionally `OPENALEX_API_KEY` (free from OpenAlex; without it, every caller at the server's address shares a small daily allowance). Git ignores it.

### Built-in lessons

The gallery contains eighteen playable lessons: attention, research reliability, Wuhan transmission, opinion dynamics, Gettier, Galton, Turner's frontier thesis, Aquinas on scriptural senses, Mendel's peas, Brown v. Board of Education, Poe's *The Masque of the Red Death*, Euclid's equilateral triangle, wave interference, Schelling's segregation model, information cascades, ice–albedo feedback, externalities and Pigouvian taxes, and loss aversion.

All lesson JSON lives in `lemma/examples/gallery/`, and a lesson appears in the gallery once it is registered in `index.json`. Every concept has an ordered `activities` sequence, and each gallery cover uses a live model from its lesson. No provider is called during playback; Galton remains the separate built-in example.

The gallery ships no source text except Galton's full public-domain paper, `lemma/examples/galton-1886.txt`. Each gallery lesson was checked against its complete source when it was built. When one is served, every check runs except grounding (the quotes against the source), which `lemma.lesson.check_lesson` skips when it has no source; `tests/` opens every gallery lesson. To rebuild one, build it in the app from its sources, then publish it with the scripts in `eval/`, which re-check the lesson against its full local source before writing it and make no provider calls.

The gallery lessons use the fixed model-first sequence. Newly built lessons choose their screens per concept: the outline proposes activity plans (worked examples, comparisons, staged evidence, matching, ordering, tracing, passages, estimates, and live-model blocks), Jev picks one plan per concept before drafting, and a concept may be taught without a live model. See `docs/lesson-flow-design.md` for the design and what remains.

- `uv run lemma --dev` is development mode with hot reload. A supervisor restarts the server on the same port whenever a Python file in `lemma/` changes, including its private OpenCode server; if the new code fails to start, it shows the traceback and waits for your next save. The browser follows along: CSS changes are swapped in place without losing your place in a lesson, and JS, HTML and example changes, or a server restart, reload the page. Server memory (papers brought in and builds in progress) doesn't survive a restart; saved lessons do. Changes to `lemma/dev.py` itself need a manual restart.
- `uv sync` creates `.venv` from `uv.lock`, using the Python version in `.python-version` (3.12).
- `uv add <package>` adds a dependency and updates the lock file.
- `uv build` makes a wheel and an sdist with uv's own build backend. The frontend (`lemma/static`) and the example lesson (`lemma/examples`) are included.
- `uv tool install .` installs the `lemma` command for your user, outside the project.

## Privacy

On your own computer the server listens on 127.0.0.1 only; hosted, it answers only the domain names it is given. Either way it rejects other Host headers and cross-origin requests, and it writes no request logs. When something breaks, it writes an error report to stderr: an id, the time, the exception's type and the lines of Lemma's code it passed through, never the exception's message, the request, the paper or a key. The learner sees the same id, so they can quote it.

Lemma handles at most 32 requests and 2 uploads at once, reads at most 2 PDFs at once, and closes a connection that sits silent for a minute, so on a small hosted VM a burst of large papers waits its turn instead of running out of memory. Paper text goes only to the provider and model named before you build, using your key. The server must set `TYPESAFE_API_KEY`: the title and opening text of each source also go to TypeSafe's Jev model, paid with that key, to sort the lesson into one of a fixed list of subject categories (`lemma/categorize.py`), and a topic search's words with each result's title and abstract go to Jev to rank the results and choose the recommended ones (`lemma/search.py`), and each drafted concept goes to Jev with the source passages it is about, to check for claims the paper doesn't support, invented findings and wrong marked answers (`lemma/factcheck.py`); a confident flag is sent back to the model as a repair, but never leaves a concept out. Jev is essential: without the key, search and lesson building don't start, and when Jev can't answer (after retrying a brief outage), the search stops, the build stops before its outline is drafted, or a concept Jev couldn't check is left out rather than shown unchecked. When you search a topic, the search words go to Wikipedia, the Stanford Encyclopedia of Philosophy, LibreTexts, OpenAlex, Europe PMC and arXiv (no accounts; OpenAlex gets the server's own key when `OPENALEX_API_KEY` is set), and to TypeSafe with the results they return; nothing is searched unless you ask.

## Tests

```sh
uv run python -m unittest discover tests
```

`eval/` holds an evaluation set of 50 papers from 23 fields and `eval/run.py`, which builds a lesson from each paper with a real model, judges every lesson with TypeSafe's Jev (the questions are in `eval/questions.py`, each asked three ways with the majority deciding; they are worded apart from the build's own Jev check, which the summary reports separately, and the teaching is judged as a learner sees it, without hidden success conditions) and summarises the results as a scorecard (Accuracy, Models, Grounding, Honesty, Teaching, Practice, Presentation and Coverage, each 0–100, their mean, and build reliability; Presentation is measured from the lesson itself and the rest from Jev's probabilities, with questions drawn from research on learning with visuals) and against the targets in `PRODUCT.md`, with a list of flags for a person to check that shows exactly what Jev was given. `eval/run.py plant` copies lessons with one deliberate critical error each, including a broken answer key in an activity block, so judging them measures what the eval catches. `eval/run.py compare --run NEW --against BASELINE` pairs two runs paper by paper and reports each score's change with a 95% interval, refusing runs judged with different questions or Jev models. It calls paid services, so it isn't part of the tests.

The tests cover the expression language, Python/JavaScript parity (needs `node`), every quality check, the generation pipeline (with a fake provider, including a repair and a concept that is left out), the HTTP provider against a stand-in API (history re-sent on repair, model filtering, bad keys, limits and context errors), the HTTP API and the export.
