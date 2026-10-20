#!/bin/sh
# Copies this checkout to the server and (re)starts Lemma there: deploy/push.sh [user@server]
# Without an argument it uses deploy/host (one line, user@server; git-ignored, so the address stays out of the repo).
set -eu
host="${1:-$(cat "$(dirname "$0")/host" 2>/dev/null || true)}"
[ -n "$host" ] || { echo "usage: deploy/push.sh user@server, or put user@server in deploy/host" >&2; exit 2; }
cd "$(dirname "$0")/.."
# Only main is deployed, exactly as it is on GitHub, so the live site always matches main.
[ "$(git branch --show-current)" = main ] || { echo "Deploy from main: merge your branch first, then check out main." >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "This checkout has uncommitted changes; commit and push them directly to main first." >&2; exit 1; }
git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "Local main differs from origin/main; pull or push so they match." >&2; exit 1; }
ssh "$host" 'sudo sh -s' < deploy/vm-startup.sh  # swap and Docker, the first time
# The secrets live only on the server (deploy/README.md says how to change one), so this computer has none to leak.
ssh "$host" 'sudo test -f lemma/deploy/lemma.env && sudo test -f lemma/deploy/cloudflared/lemma.json' || {
  echo "The server is missing lemma/deploy/lemma.env or lemma/deploy/cloudflared/lemma.json; see \"Secrets\" in deploy/README.md." >&2; exit 1; }
# Evaluation runs hold full paper texts and model output; the server needs neither.
# Local tool data (agent worktrees, design notes, caches) stays on this computer.
# Excluded paths are also kept on the server by --delete, so its secrets survive every deploy.
rsync -az --delete --exclude .git --exclude .venv --exclude '__pycache__' --exclude eval/results \
  --exclude /deploy/lemma.env --exclude '/deploy/cloudflared/*.json' --exclude /deploy/host \
  --exclude .claude --exclude .forge --exclude .impeccable --exclude .codex --exclude .cursor --exclude .gemini --exclude .pytest_cache --exclude backups ./ "$host:lemma/"
# The secrets stay readable only by their user; cloudflared runs as uid 65532 (nonroot) in its container.
ssh "$host" 'cd lemma/deploy && chmod 600 lemma.env && sudo chmod 600 cloudflared/lemma.json && sudo chown 65532 cloudflared/lemma.json && sudo docker compose up -d --build && sudo docker compose restart tunnel && sudo docker compose ps'  # cloudflared reads its routes only at startup
