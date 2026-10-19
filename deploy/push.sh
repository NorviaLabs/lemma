#!/bin/sh
# Copies this checkout to the server and (re)starts Lemma there: deploy/push.sh ubuntu@<server address>
set -eu
host="${1:?usage: deploy/push.sh user@server}"
cd "$(dirname "$0")/.."
[ -f deploy/lemma.env ] || { echo "deploy/lemma.env is missing; copy deploy/lemma.env.example and fill it in." >&2; exit 1; }
# rsync --delete below would otherwise remove the server's tunnel credentials, and the site would go down at its next restart.
[ -f deploy/cloudflared/lemma.json ] || { echo "deploy/cloudflared/lemma.json (the tunnel credentials) is missing; see deploy/README.md." >&2; exit 1; }
# Only main is deployed, exactly as it is on GitHub, so the live site always matches main.
[ "$(git branch --show-current)" = main ] || { echo "Deploy from main: merge your branch first, then check out main." >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "This checkout has uncommitted changes; commit and push them directly to main first." >&2; exit 1; }
git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "Local main differs from origin/main; pull or push so they match." >&2; exit 1; }
ssh "$host" 'sudo sh -s' < deploy/vm-startup.sh  # swap and Docker, the first time
# Evaluation runs hold full paper texts and model output; the server needs neither.
# Local tool data (agent worktrees, design notes, caches) stays on this computer.
rsync -az --delete --exclude .git --exclude .venv --exclude '__pycache__' --exclude eval/results \
  --exclude .claude --exclude .forge --exclude .impeccable --exclude .codex --exclude .cursor --exclude .gemini --exclude .pytest_cache ./ "$host:lemma/"
# The secrets stay readable only by their user; cloudflared runs as uid 65532 (nonroot) in its container.
ssh "$host" 'cd lemma/deploy && chmod 600 lemma.env && sudo chmod 600 cloudflared/lemma.json && sudo chown 65532 cloudflared/lemma.json && sudo docker compose up -d --build && sudo docker compose restart tunnel && sudo docker compose ps'  # cloudflared reads its routes only at startup
