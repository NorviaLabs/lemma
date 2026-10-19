#!/bin/sh
# Copies the hosted Lemma's data to this computer: deploy/backup.sh ubuntu@<server address> [destination folder]
# The databases are copied with SQLite's online backup, so a backup taken while people use the site is consistent.
set -eu
host="${1:?usage: deploy/backup.sh user@server [destination]}"
dest="${2:-backups}"
stamp="$(date -u +%Y-%m-%dT%H%MZ)"
mkdir -p "$dest"
ssh "$host" 'cd lemma/deploy && sudo docker compose exec -T lemma python -c "
import sqlite3, pathlib
out = pathlib.Path(\"/data/.backup\"); out.mkdir(exist_ok=True)
for name in (\"accounts.db\", \"metrics.db\"):
    src = pathlib.Path(\"/data\") / name
    if src.exists():
        with sqlite3.connect(src) as a, sqlite3.connect(out / name) as b:
            a.backup(b)
"'
ssh "$host" "sudo docker run --rm -v deploy_lemma-data:/data alpine tar czf - -C /data --exclude ./accounts.db --exclude ./accounts.db-wal --exclude ./accounts.db-shm --exclude ./metrics.db --exclude ./metrics.db-wal --exclude ./metrics.db-shm ." > "$dest/lemma-data-$stamp.tgz"
echo "Saved $dest/lemma-data-$stamp.tgz (libraries, plus consistent copies of the databases in .backup/)."
