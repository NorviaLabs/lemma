# Lemma at openlemma.org

Lemma runs in Docker on a free-tier Google Cloud e2-micro VM (`lemma` in project `lemma-511811`, zone `us-central1-a`, Ubuntu 24.04, 34.172.130.18). A Cloudflare Tunnel (`lemma`, b9f37d76-4c40-4ceb-9e02-8988a0755f90) carries `https://openlemma.org` to it, so the VM opens no ports beyond SSH and Cloudflare handles HTTPS. The domain is registered with Cloudflare Registrar. The tunnel also carries `www.openlemma.org`, which Lemma redirects to `https://openlemma.org`.

Lemma's data (`accounts.db` and each account's library) lives in the `deploy_lemma-data` Docker volume.

## Files

- `compose.yaml`: Lemma and `cloudflared`.
- `cloudflared/config.yml`: the tunnel's routes. `cloudflared/lemma.json` holds the tunnel's credentials; it is secret and kept out of git.
- `lemma.env`: the Google and GitHub OAuth client IDs and secrets; secret and kept out of git. `lemma.env.example` lists its keys.
- `push.sh`: deploys this checkout. `vm-startup.sh`: prepares the VM (2 GB of swap and Docker), run by `push.sh`.

## Deploy, and redeploy after changes

```sh
deploy/push.sh ubuntu@34.172.130.18
```

Commit and push directly to `main` before deploying; do not create a pull request unless explicitly requested. Run the script from `main`, clean and matching `origin/main`; it refuses anything else, so the live site always matches `main`. It copies this checkout to the VM (secrets included), then rebuilds and restarts both containers. Logs: `ssh ubuntu@34.172.130.18 'cd lemma/deploy && sudo docker compose logs -f'`. Lemma's own lines are only error reports (`<time> error <id> in <where>: <type>` and the code it passed through); a learner who quotes an error id can be found with `sudo docker compose logs lemma | grep -A 30 <id>`.

## Limits and analytics

- Each account may start 40 searches and 20 outlines or builds a day (UTC), since every one uses the server's TypeSafe key. Change them with `LEMMA_DAILY_SEARCHES` and `LEMMA_DAILY_BUILDS` in `compose.yaml`.
- Lemma counts anonymous events per day (lessons opened and finished, goals reached alone or with Show me, searches, sign-ins, and outline and build outcomes) in `metrics.db` beside `accounts.db`. Signed in as an account listed in `LEMMA_ADMINS`, open `https://openlemma.org/api/stats` for the last 30 days.
- `.github/workflows/uptime.yml` checks the site every 15 minutes; GitHub emails whoever last edited its schedule when a check fails.
- Page views come from Cloudflare Web Analytics (Cloudflare dashboard → Analytics & Logs → Web Analytics, automatic setup for openlemma.org). Lemma's Content Security Policy allows its script on the hosted site.

## Sign-in apps

- GitHub: OAuth app "Lemma" under github.com/settings/developers, callback `https://openlemma.org/auth/github/callback`.
- Google: project `lemma-511811` → Google Auth Platform, External and in production, web client "Lemma web" with callback `https://openlemma.org/auth/google/callback`. Its privacy policy link is `https://openlemma.org/privacy`.

A new secret from either goes into `lemma.env`, followed by `push.sh`.

## Rebuilding from scratch

1. `cloudflared tunnel login`, then `cloudflared tunnel create --credentials-file deploy/cloudflared/lemma.json lemma`. Put the new tunnel id in `cloudflared/config.yml`, then run `cloudflared tunnel route dns lemma openlemma.org`.
2. Any Ubuntu VM reachable over SSH works, as long as it has about 1 GB of RAM or more.
3. Fill in `lemma.env` and run `push.sh`.

## Backups

```sh
ssh ubuntu@34.172.130.18 'sudo docker run --rm -v deploy_lemma-data:/data -v $HOME:/out alpine tar czf /out/lemma-data.tgz -C /data .'
scp ubuntu@34.172.130.18:lemma-data.tgz .
```
