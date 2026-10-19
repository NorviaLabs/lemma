# Lemma at openlemma.org

Lemma runs in Docker on a free-tier Google Cloud e2-micro VM (Ubuntu 24.04) in `us-central1`. A Cloudflare Tunnel named `lemma` carries `https://openlemma.org` to it, so the VM opens no ports beyond SSH and Cloudflare handles HTTPS. The domain is registered with Cloudflare Registrar. The tunnel also carries `www.openlemma.org`, which Lemma redirects to `https://openlemma.org`.

Lemma's data (`accounts.db`, `metrics.db`, `feedback.db` and each account's library) lives in the `deploy_lemma-data` Docker volume.

## Files

- `compose.yaml`: Lemma and `cloudflared`.
- `cloudflared/config.yml`: the tunnel's routes. `cloudflared/lemma.json` holds the tunnel's credentials; it is secret and kept out of git.
- `lemma.env`: the Google OAuth client ID and secret, the TypeSafe key, and `LEMMA_ADMINS`; secret and kept out of git. `lemma.env.example` lists its keys.
- `host`: the VM's `user@address`, one line; kept out of git. `push.sh` and `backup.sh` use it when given no address.
- `push.sh`: deploys this checkout. `vm-startup.sh`: prepares the VM (2 GB of swap and Docker), run by `push.sh`.

## Deploy, and redeploy after changes

```sh
deploy/push.sh
```

Commit and push directly to `main` before deploying; do not create a pull request unless explicitly requested. Run the script from `main`, clean and matching `origin/main`; it refuses anything else, so the live site always matches `main`. It copies this checkout to the VM (secrets included), then rebuilds and restarts both containers. Logs: `ssh "$(cat deploy/host)" 'cd lemma/deploy && sudo docker compose logs -f'`. Lemma's own lines are only error reports (`<time> error <id> in <where>: <type>` and the code it passed through); a learner who quotes an error id can be found with `sudo docker compose logs lemma | grep -A 30 <id>`.

## Limits and analytics

- Each account may start 40 searches and 20 outlines or builds a day (UTC), and read 100 links or files on their own, since every one uses the server's TypeSafe key or bandwidth, and send 10 pieces of feedback. These are Lemma's safe defaults, which apply whenever a setting is missing; `compose.yaml` also sets them explicitly (`LEMMA_DAILY_SEARCHES`, `LEMMA_DAILY_BUILDS`, `LEMMA_DAILY_READS`, `LEMMA_DAILY_FEEDBACK`). Only the word `unlimited` lifts a cap: never use it here (a test fails if `compose.yaml` does). A value that isn't a whole number or `unlimited` stops Lemma from starting.
- Each visitor address (Cloudflare's `CF-Connecting-IP`) may make 120 requests that change something every 10 minutes; reads such as progress polling aren't limited.
- Lemma sends HSTS on every response and moves plain-HTTP visits to HTTPS. Container logs are capped at 3 × 10 MB each, the journal at 200 MB, and a weekly timer (`lemma-prune.timer`, installed by `vm-startup.sh`) removes images and build cache unused for a week.
- Lemma counts anonymous events per day (lessons opened and finished, goals reached alone or with Show me, searches, sign-ins, and outline and build outcomes) in `metrics.db` beside `accounts.db`. Signed in as an account listed in `LEMMA_ADMINS`, open `https://openlemma.org/api/stats` for the last 30 days.
- Feedback from signed-in accounts (a rating and/or message, the account's name and email for replies, and the page, lesson, error id or build id it was sent from) is kept in `feedback.db` until it is deleted. The accounts in `LEMMA_ADMINS` read it at `https://openlemma.org/api/feedback` (`?status=new` or `?status=done`), and `/api/status` tells them how many items are new.
- `.github/workflows/uptime.yml` checks the site every 15 minutes; GitHub emails whoever last edited its schedule when a check fails.
- Page views come from Cloudflare Web Analytics (Cloudflare dashboard → Analytics & Logs → Web Analytics, automatic setup for openlemma.org). Lemma's Content Security Policy allows its script on the hosted site.

## Deleting an account on request

Lemma has no delete button yet; when someone asks by email, find their account id, then remove the account and its sessions, its `users/<id>` folder (library and build requests) and its feedback:

```sh
ssh "$(cat deploy/host)" 'cd lemma/deploy && sudo docker compose exec -T lemma /app/.venv/bin/python -c "import sqlite3; print(sqlite3.connect(\"/data/accounts.db\").execute(\"SELECT id, provider, name FROM users WHERE email = ?\", (\"PERSON@EXAMPLE.COM\",)).fetchall())"'
ssh "$(cat deploy/host)" 'cd lemma/deploy && sudo docker compose exec -T lemma /app/.venv/bin/python -c "import shutil, sys; from lemma import auth, feedback, store; uid = sys.argv[1]; auth.delete_user(uid); feedback.delete_for_account(uid); shutil.rmtree(store.home() / \"users\" / uid, ignore_errors=True)" ACCOUNT_ID'
```

Anonymous daily counts in `metrics.db` name no account; its per-account quota rows are removed after about a week. Backups taken before the deletion still hold the account until they expire (snapshots after 14 days; delete it from local copies by hand).

## Sign-in apps

- Google: the project's Google Auth Platform, External and in production, web client "Lemma web" with callback `https://openlemma.org/auth/google/callback`. Its privacy policy link is `https://openlemma.org/privacy`.
- GitHub sign-in was turned off on 2026-10-19 (its settings removed from `lemma.env`). Lemma still supports it: to offer it again, create an OAuth app with callback `https://openlemma.org/auth/github/callback` and set `LEMMA_GITHUB_CLIENT_ID` and `LEMMA_GITHUB_CLIENT_SECRET`.

A new secret goes into `lemma.env`, followed by `push.sh`.

## Rebuilding from scratch

1. `cloudflared tunnel login`, then `cloudflared tunnel create --credentials-file deploy/cloudflared/lemma.json lemma`. Put the new tunnel id in `cloudflared/config.yml`, then run `cloudflared tunnel route dns lemma openlemma.org`.
2. Any Ubuntu VM reachable over SSH works, as long as it has about 1 GB of RAM or more.
3. Fill in `lemma.env`, put the VM's `user@address` in `deploy/host`, and run `push.sh`.

## Backups

All accounts and libraries live on the VM's one disk, so keep two kinds of backup:

- **Disk snapshots, automatically.** In Google Cloud, Compute Engine → Snapshots → Snapshot schedules, create a daily schedule (keep 14 days) in the VM's region and attach it to its boot disk. A snapshot restores the whole VM.
- **A copy of the data on your own computer.** `deploy/backup.sh` saves `backups/lemma-data-<time>.tgz` (git-ignored): every library, plus `accounts.db`, `metrics.db` and `feedback.db` copied with SQLite's online backup into `.backup/`, so it is consistent even while people use the site. To restore, unpack it into the `deploy_lemma-data` volume and move the two databases out of `.backup/`.

Restore drills (unpack into a scratch `LEMMA_HOME`, move the databases out of `.backup/`, run `PRAGMA integrity_check`, then read every account's requests and lessons through `server.api_requests`, `api_request` and `api_lessons`):

- 2026-10-19: `lemma-data-2026-10-19T1658Z.tgz` (87 KB). Both databases `ok`; 3 accounts, each with its folder; 3 sessions; 3 build requests opened through the API; no saved lessons yet. The documented steps worked as written.
