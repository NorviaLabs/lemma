# Agent guide

## Project

Lemma turns research papers into short, interactive lessons. Prioritize the curious learner with no background in the paper's field. Read `PRODUCT.md` before changing product behavior and `DESIGN.md` before changing the interface. `README.md` covers setup, providers, hosting, and privacy; `THESIS.md` explains the broader rationale.

## Repository map

- `lemma/__main__.py`: CLI and server startup.
- `lemma/server.py`: HTTP server and API.
- `lemma/ingest.py`, `lemma/search.py`: source retrieval and discovery.
- `lemma/generate.py`, `lemma/lesson.py`: generation, lesson format, and quality checks.
- `lemma/llm.py`, `lemma/claude.py`, `lemma/chatgpt.py`, `lemma/jev.py`: model integrations.
- `lemma/store.py`, `lemma/auth.py`: persistence and authentication.
- `lemma/expr.py`, `lemma/kernels.py`: expression and simulation engines.
- `lemma/static/`: browser UI in plain JavaScript, HTML, and CSS; no frontend build step.
- `lemma/examples/`: bundled lessons and source text.
- `tests/`: Python unittest suite and JavaScript cross-check helper.
- `eval/`: real-model evaluations, separate from automated tests.
- `deploy/`: hosting configuration.

## Development

Use uv and the committed `uv.lock`. The package supports Python 3.10+; `.python-version` selects Python 3.12 for development.

```sh
uv sync
uv run lemma --dev                 # restart Python and live-reload the browser
uv run lemma --no-browser          # default: http://localhost:8765
uv run python -m unittest discover tests
uv build                          # when changing packaging
```

CI runs the unittest discovery command with Node.js 22 installed. Install Node.js when changing the expression or simulation engines: Python/JavaScript parity tests otherwise skip.

## Change rules

- Follow the surrounding code and keep changes focused. Prefer the existing standard-library backend and plain browser frontend over new frameworks or dependencies.
- Keep the Python and JavaScript expression/simulation engines in sync: `lemma/expr.py` with `lemma/static/expr.js`, and `lemma/kernels.py` with `lemma/static/kernels.js`. Validate parity after changes.
- Preserve lesson quality gates in `lemma/lesson.py`: source-grounded quotes, finite model outputs, reachable goals on the control grid, complete lesson structure, and explicit teaching-model labels. Do not bypass validation to display a failing lesson.
- Update relevant tests when behavior changes. Use fake providers and local fixtures for automated tests rather than live model calls.
- Treat `eval/run.py` as a paid external-service workflow. Do not run evaluations unless the user explicitly requests or approves them.
- Preserve localhost-only defaults, Host/origin checks, and hosted-mode safeguards. Do not expose the server publicly as part of routine development.
- Keep credentials, auth tokens, and personal lesson data out of source control and logs. Use a temporary `LEMMA_HOME` for manual tests that write user data rather than modifying the user's normal `~/.lemma` directory.

## Verification

Run the narrowest relevant tests during development, then the full unittest suite before handing off code changes when possible. For interface changes, also exercise the affected flow in a browser; unit tests alone do not establish visual correctness. Report what was checked and any skipped or blocked validation.

## Publishing and deployment

When asked to publish or deploy, commit and push directly to `main`; do not create a pull request unless explicitly requested. Deploy from a clean `main` matching `origin/main` with `deploy/push.sh ubuntu@34.172.130.18`. Verify the live gallery and lesson endpoints after deployment. Never commit deployment credentials or evaluation-run secrets.
