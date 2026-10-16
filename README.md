# Lemma

Lemma turns a research paper into a short, hands-on lesson. It starts with the paper in brief. Then, for each idea, a live model shows how it works, the explanation follows with an exact quote from the paper, and then you try it yourself. It works for papers from any field. The full product spec is in [`docs/product-spec.md`](docs/product-spec.md), and the visual design system is in [`DESIGN.md`](DESIGN.md).

## Quick start

You need [uv](https://docs.astral.sh/uv/) and a copy of this repository.

```sh
uv run lemma                 # installs what's needed on first run, then opens http://localhost:8765
```

The built-in example lesson (Galton, 1886) works straight away, with no setup.

To make lessons from your own papers, Lemma needs your own key for an AI provider. The home page asks for one:

| | Get a key | Fits |
|---|---|---|
| **OpenCode Go** | [opencode.ai/auth](https://opencode.ai/auth) (needs an OpenCode Go plan) | Long papers (about 1M tokens) |
| **OpenAI** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | Depends on the model |
| **Claude** | [platform.claude.com/settings/keys](https://platform.claude.com/settings/keys) | Long papers (about 1M tokens) |
| **ChatGPT** | No key: sign in with your ChatGPT Plus or Pro account. Only when Lemma runs on your own computer | Depends on the model |

Search a topic and choose multiple sources, paste a link, or upload a PDF. Search results suggest an overview and up to two relevant papers only after downloading and checking readable full text; blocked copies are skipped in favor of readable alternatives. Checks are cached for five minutes, so availability can still change. You can change every selection. Lemma creates one combined lesson, attributes its evidence to individual sources, and asks the model to explain meaningful disagreements.

Creation runs in the background. Review the proposed outline, then watch concept-by-concept progress and an approximate time range once enough work has completed. You can start checked concepts early, leave the page, and return through the build's link or My library. Completed lessons save automatically. Unreadable sources are listed as warnings; creation fails if none can be read.

Requests, source text, and progress are stored privately under `LEMMA_HOME` (by default `~/.lemma`). Credentials are never written into build records. Server restarts mark active builds interrupted rather than resuming them automatically; retry uses your current provider credentials. You can cancel running builds, retry stopped builds with the same selections, and delete stopped builds or saved lessons from the library.

Source text has no application-level word or character cap and is never silently truncated. The 40 MB file limit and the selected AI model's context limit still apply; if the model rejects the input as too long, choose a model with a larger context in Settings.

## Run it

`uv run lemma --port 9000 --no-browser` changes the port or skips opening a browser. In Settings, pick the provider, paste its key and choose a model. The model list is read live with your key; the defaults are `gpt-5.6-luna` for OpenCode Go and `gpt-6.1-sol` for OpenAI.

### How Lemma uses your key

Both providers are called over their OpenAI-compatible chat completions APIs (`https://opencode.ai/zen/go/v1` and `https://api.openai.com/v1`), with no tools, so the model can only read what Lemma sends and reply with text. Your browser keeps your provider, model and key, and sends them with each request in `X-Lemma-*` headers. The server uses the key for that request, or for the build it starts, and never writes it to disk or sends it back. The APIs keep no conversation, so a repair re-sends the paper, the earlier draft and the list of problems.

### How Lemma uses Claude

Claude is called through Anthropic's Python SDK with your key, streaming each reply, with adaptive thinking and high effort where the model offers it. The model list shows the models that support adaptive thinking; the default is `claude-opus-5-5`. A repair re-sends the paper, so the request is marked for prompt caching to make that repeat cheap, and Claude's earlier replies go back exactly as it sent them. On models that support it, a request Claude's safety checks decline is retried on the model Anthropic recommends for that case (`fallbacks: "default"`); if it is still declined, that concept is left out and the lesson says so.

A Claude Pro or Max subscription can't be used: Anthropic doesn't allow subscriptions in third-party apps.

### How Lemma uses your ChatGPT subscription

This signs in the same way the Codex CLI does. **Sign in with ChatGPT** in Settings opens OpenAI's sign-in page, which sends you back to `http://localhost:1455/auth/callback`; Lemma listens there only while you sign in. Your tokens are kept in `~/.lemma/chatgpt-auth.json`, readable only by you, and refreshed when they expire. **Sign out** deletes them. Lessons are built through the ChatGPT backend that Codex uses, with no tools, and count against your plan's usage. It is for your own use on your own computer: a hosted Lemma serving other people must not offer it.

### Host it for other people

`lemma --host 0.0.0.0 --allowed-hosts tools.example.com` (or `LEMMA_HOST` and `LEMMA_ALLOWED_HOSTS`) serves Lemma beyond this computer. A hosted Lemma answers only the domain names it is given, binds exactly `--port`, and doesn't offer ChatGPT sign-in. People sign in with Google or GitHub (`lemma/auth.py`), and each account has its own profile, library, papers and builds, with at most two builds running per account. Set `LEMMA_PUBLIC_URL` to where people reach it, such as `https://tools.example.com/lemma`: Lemma serves under that path and sends sign-ins back to `<public url>/auth/<google|github>/callback`. Each provider is offered once both its `LEMMA_<GOOGLE|GITHUB>_CLIENT_ID` and `_CLIENT_SECRET` are set. Accounts are kept in `$LEMMA_HOME/accounts.db`, and libraries in `$LEMMA_HOME/users/`. Serve it over HTTPS only, since learners' keys travel in request headers.

[`deploy/`](deploy/README.md) runs it at tools.mohitranka.com/lemma on a free Oracle Cloud VM behind a Cloudflare Tunnel.

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

The server listens on 127.0.0.1 only and rejects other Host headers and cross-origin requests. It writes no request logs. Paper text goes only to the provider and model named before you build, using your key. When you search a topic, only the search words go to OpenAlex, arXiv and Wikipedia (no accounts or keys); nothing is searched unless you ask.

## Tests

```sh
uv run python -m unittest discover tests
```

The tests cover the expression language, Python/JavaScript parity (needs `node`), every quality check, the generation pipeline (with a fake provider, including a repair and a concept that is left out), the HTTP provider against a stand-in API (history re-sent on repair, model filtering, bad keys, limits and context errors), the HTTP API and the export.
