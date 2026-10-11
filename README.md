# Lemma

Lemma turns a research paper into a short, hands-on lesson. It starts with the paper in brief. Then, for each idea, a live model shows how it works, the explanation follows with an exact quote from the paper, and then you try it yourself. It works for papers from any field. The full product spec is in [`docs/product-spec.md`](docs/product-spec.md), and the visual design system is in [`DESIGN.md`](DESIGN.md).

## Quick start

You need [uv](https://docs.astral.sh/uv/) and a copy of this repository.

```sh
uv run lemma                 # installs what's needed on first run, then opens http://localhost:8765
```

The built-in example lesson (Galton, 1886) works straight away, with no setup.

To make lessons from your own papers, Lemma needs an AI tool you install and sign in to yourself. The home page walks you through it, and notices when you've finished:

| | Install | Sign in | Fits |
|---|---|---|---|
| **OpenCode Go** | `curl -fsSL https://opencode.ai/install \| bash` | `opencode providers login`, then choose OpenCode Go (needs an OpenCode Go plan) | Long papers (about 1M tokens) |
| **Codex** | `npm install -g @openai/codex` | `codex login` (signs in with ChatGPT) | Papers up to about 270k tokens |

Then paste a link or upload a PDF. Building a lesson usually takes 1–3 minutes, and you can start the first concept sooner.

## Run it

`uv run lemma --port 9000 --no-browser` changes the port or skips opening a browser. In Settings, pick the provider and its model. Each list is read live from your installation; the defaults are `gpt-5.6-luna` for OpenCode Go and `gpt-6.1-sol` for Codex. If a program isn't on your `PATH`, set its location in Settings, or in `LEMMA_OPENCODE` or `LEMMA_CODEX`.

### How Lemma uses OpenCode Go

Lemma starts its own `opencode serve --pure` process. It listens on 127.0.0.1 only, on a random port, behind a one-time password, and runs in an empty working directory (`~/.lemma/opencode-workdir`). Its inline config defines a `lemma` agent that has no tools and denies every permission, so the model can only read what Lemma sends and reply with text. OpenCode uses its own stored OpenCode Go credentials. Lemma never uses or stores a key; it only checks OpenCode's `auth.json` for an OpenCode Go entry. Each concept gets its own OpenCode session, so a repair can refer back to the first draft, and the session is deleted afterwards so papers don't stay in your OpenCode history. OpenCode stops when Lemma stops.

### How Lemma uses Codex

Each request is a one-off `codex exec`:
- **Nothing is saved:** `--ephemeral`, so Codex keeps no session on disk.
- **Your setup is left out:** `--ignore-user-config` and `--ignore-rules`, so your MCP servers, plugins and instructions aren't loaded. Codex still uses its own sign-in.
- **Sandboxed:** a read-only sandbox in an empty working directory (`~/.lemma/codex-workdir`), with approvals set to never.
- **Tools off:** the shell, code execution, multi-agent, web search, browser, computer use, apps, plugins, memories, image generation and image viewing are disabled, and Codex refuses any blocked tool call rather than running it.
- **Lemma's instructions:** passed as developer instructions. The paper goes in on standard input.

Because Codex keeps no session, a repair re-sends the paper, the earlier draft and the list of problems. Codex models have a smaller context (272k tokens) than the OpenCode Go ones, so Lemma refuses a paper that won't fit and says why, rather than cutting it short.

## How it works

1. **Find something to learn.** Search a topic (or press **Surprise me**): Lemma lists an overview article from Wikipedia, the most-cited open-access papers from OpenAlex and recent preprints from arXiv, and you pick one. Or paste a link (arXiv links are turned into PDF links), or upload a PDF, HTML or text file. Then say who the lesson is for. For a search result, Lemma tries each open copy of it until it finds full text it can read.
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

- `uv run lemma --dev` is development mode with hot reload. A supervisor restarts the server on the same port whenever a Python file in `lemma/` changes, including its private OpenCode server; if the new code fails to start, it shows the traceback and waits for your next save. The browser follows along: CSS changes are swapped in place without losing your place in a lesson, and JS, HTML and example changes, or a server restart, reload the page. Server memory (papers brought in and builds in progress) doesn't survive a restart; saved lessons do. Changes to `lemma/dev.py` itself need a manual restart.
- `uv sync` creates `.venv` from `uv.lock`, using the Python version in `.python-version` (3.12).
- `uv add <package>` adds a dependency and updates the lock file.
- `uv build` makes a wheel and an sdist with uv's own build backend. The frontend (`lemma/static`) and the example lesson (`lemma/examples`) are included.
- `uv tool install .` installs the `lemma` command for your user, outside the project.

## Privacy

The server listens on 127.0.0.1 only and rejects other Host headers and cross-origin requests. It writes no request logs. Paper text goes only to the provider and model named before you build, by way of your local OpenCode or Codex. When you search a topic, only the search words go to OpenAlex, arXiv and Wikipedia (no accounts or keys); nothing is searched unless you ask.

## Tests

```sh
uv run python -m unittest discover tests
```

The tests cover the expression language, Python/JavaScript parity (needs `node`), every quality check, the generation pipeline (with a fake provider, including a repair and a concept that is left out), both providers against stand-in programs (`tests/fake_opencode.py`: private server, password, sessions, cleanup, errors; `tests/fake_codex.py`: the lockdown flags, history re-sent on repair, context limits, errors), the HTTP API and the export.
