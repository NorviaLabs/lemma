# Contributing to OpenLemma

Thank you for helping. OpenLemma turns a question or a source into a short lesson taught on live models, for a curious learner with no background in the field. Read `PRODUCT.md` before changing what it does and `DESIGN.md` before changing how it looks.

## Set up

You need [uv](https://docs.astral.sh/uv/). [README.md → What you need](README.md#what-you-need) lists which keys unlock what; the tests need none.

```sh
uv sync
uv run python -m unittest discover tests
set -a; . ./local.env; . ./deploy/lemma.env; set +a   # your keys: copy deploy/lemma.env.example (git-ignored)
uv run lemma --dev
```

Install Node.js 22 if you change the expression or simulation engines, so the Python/JavaScript parity tests run instead of skipping.

## Rules that keep OpenLemma honest

- **One behaviour everywhere.** OpenLemma behaves the same on your own computer as hosted; the only difference is the ChatGPT subscription. Don't branch on where it runs. `tests/test_one_behaviour.py` fails if you do.
- **Safe defaults.** Limits default to the values a public server needs; development lifts them through `local.env`. A missing setting must never make a public server more permissive.
- **Quality gates stay.** A lesson that fails `lemma/lesson.py`'s checks (word-for-word quotes, finite models, reachable goals, complete structure, labelled teaching models) is never shown. Don't loosen a check to make a lesson pass.
- **Two engines, one behaviour.** Keep `lemma/expr.py` with `lemma/static/expr.js`, and `lemma/kernels.py` with `lemma/static/kernels.js`, in step.
- **No new frameworks.** The backend is the Python standard library and the frontend is plain JavaScript, HTML and CSS with no build step.
- **No real services in tests.** Use the fake providers and local fixtures. Never commit keys, tokens or anyone's lesson data.

## Making a change

Keep each change focused and follow the code around it. Add or update tests for behaviour you change, run the full suite, and for interface changes try the flow in a browser at phone and desktop widths. In the pull request, say what you checked.

`eval/run.py` calls paid models; don't run it as part of a contribution.

## Reporting problems

- **A problem with the code:** open a GitHub issue at [github.com/NorviaLabs/lemma/issues](https://github.com/NorviaLabs/lemma/issues).
- **A problem on openlemma.org:** use **Send feedback** on the site (in the footer, or **Report this** under an error).
- **A security problem:** please don't open a public issue. See [SECURITY.md](SECURITY.md).

By contributing, you agree that your contribution is licensed under the MIT License (see `LICENSE` and `NOTICE`).
