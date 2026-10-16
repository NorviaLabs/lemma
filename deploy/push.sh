#!/bin/sh
# Copies this checkout to the server and (re)starts Lemma there: deploy/push.sh ubuntu@<server address>
set -eu
host="${1:?usage: deploy/push.sh user@server}"
cd "$(dirname "$0")/.."
[ -f deploy/lemma.env ] || { echo "deploy/lemma.env is missing; copy deploy/lemma.env.example and fill it in." >&2; exit 1; }
ssh "$host" 'sudo sh -s' < deploy/vm-startup.sh  # swap and Docker, the first time
rsync -az --delete --exclude .git --exclude .venv --exclude '__pycache__' ./ "$host:lemma/"
# The secrets stay readable only by their user; cloudflared runs as uid 65532 (nonroot) in its container.
ssh "$host" 'cd lemma/deploy && chmod 600 lemma.env && sudo chmod 600 cloudflared/lemma.json && sudo chown 65532 cloudflared/lemma.json && sudo docker compose up -d --build && sudo docker compose ps'
