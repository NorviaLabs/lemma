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
set -a; . ./local.env; set +a     # development config: lifts the daily caps (no secrets; committed)
uv run lemma --dev                 # the one way to run it: http://localhost:8765, restarts on Python changes, live-reloads the browser
uv run python -m unittest discover tests
uv build                          # when changing packaging
```

CI runs the unittest discovery command with Node.js 22 installed. Install Node.js when changing the expression or simulation engines: Python/JavaScript parity tests otherwise skip.

## Change rules

- Follow the surrounding code and keep changes focused. Prefer the existing standard-library backend and plain browser frontend over new frameworks or dependencies.
- Keep the Python and JavaScript expression/simulation engines in sync: `lemma/expr.py` with `lemma/static/expr.js`, and `lemma/kernels.py` with `lemma/static/kernels.js`. Validate parity after changes.
- Preserve lesson quality gates in `lemma/lesson.py`: source-grounded quotes, finite model outputs, reachable goals on the control grid, complete lesson structure, and explicit teaching-model labels. Do not bypass validation to display a failing lesson.
- Update relevant tests when behavior changes. Use fake providers and local fixtures for automated tests rather than live model calls.
- Build lessons locally (manual tests, gallery rebuilds) with an API-key provider the user chooses, using their key; don't pick a provider or spend on a key without asking. Eval builds (`eval/run.py build --builder <provider>:<model>`) need the user's explicit approval, as below.
- Treat `eval/run.py` as a paid external-service workflow. Do not run evaluations unless the user explicitly requests or approves them.
- Run exactly one Lemma at a time, always `uv run lemma --dev` (with a temporary `LEMMA_HOME` when it writes user data). Stop the running one before starting another; don't start extra servers, previews or ports to show something. Dev mode reloads on edits, so the one instance stays current. It always uses its port (8765 unless `--port` says otherwise): if the port stays busy for 10 seconds it stops with an error rather than moving, since Google sign-in returns only to `http://localhost:8765/auth/google/callback`.
- Lemma behaves the same on your own computer as hosted for others. The only difference is the ChatGPT subscription, which only a server bound to this computer offers. Everything else is identical: sign-in is Google OAuth both ways (locally it returns to `http://localhost:8765/auth/google/callback`, which must be registered on the OAuth client), and accounts, limits, providers, headers, pages and copy are the same. Where a deployment needs different numbers, make it configuration read the same way everywhere, never a check of where Lemma runs: the daily caps (`LEMMA_DAILY_SEARCHES`, `LEMMA_DAILY_BUILDS`, `LEMMA_DAILY_READS`) default to the safe production caps when unset, only the explicit value `unlimited` lifts one, `local.env` does that for development, and `deploy/compose.yaml` must never. Defaults are always the restrictive, production-safe values; a missing setting must never make production more permissive. That difference has one switch, `server.ON_THIS_COMPUTER`, set by `make_server` from the address it binds; never branch on where Lemma runs anywhere else, in Python or the browser, and don't add local-only conveniences. `tests/test_one_behaviour.py` enforces this: it fails if the switch is read outside `providers()`, `_chatgpt_only()`, `make_server` and `main`, or if the same requests to a local and a public server get different answers. Don't widen its allowlist to make a change pass; fix the change.
- Preserve Host/origin checks and the safeguards for a server on a public address (allowed hosts, exact port, no live reload, no ChatGPT subscription). Do not expose the server publicly as part of routine development.
- Deployment secrets (`lemma.env`, the tunnel credentials) live only on the server; never put them back in `deploy/` or copy them to this computer (see Secrets in `deploy/README.md`).
- Keep credentials, auth tokens, and personal lesson data out of source control and logs. Use a temporary `LEMMA_HOME` for manual tests that write user data rather than modifying the user's normal `~/.lemma` directory.

## Verification

Run the narrowest relevant tests during development, then the full unittest suite before handing off code changes when possible. For interface changes, also exercise the affected flow in a browser; unit tests alone do not establish visual correctness. Report what was checked and any skipped or blocked validation.

## Publishing and deployment

When asked to publish or deploy, commit and push directly to `main`; do not create a pull request unless explicitly requested. Deploy from a clean `main` matching `origin/main` with `deploy/push.sh` (it reads the server from the git-ignored `deploy/host`). Verify the live gallery and lesson endpoints after deployment. Never commit deployment credentials or evaluation-run secrets.
