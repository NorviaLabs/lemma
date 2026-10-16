# Lemma at tools.mohitranka.com/lemma

Lemma runs in Docker on a free-tier Google Cloud e2-micro VM (`lemma` in project `lemma-511811`, zone `us-central1-a`, Ubuntu 24.04, 34.172.130.18). A Cloudflare Tunnel (`lemma`, b9f37d76-4c40-4ceb-9e02-8988a0755f90) carries `https://tools.mohitranka.com/lemma/*` to it, so the VM opens no ports beyond SSH and Cloudflare handles HTTPS. Anything else on tools.mohitranka.com gets a 404 from the tunnel, which leaves room for other tools.

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

It copies this checkout to the VM (secrets included), then rebuilds and restarts both containers. Logs: `ssh ubuntu@34.172.130.18 'cd lemma/deploy && sudo docker compose logs -f'`.

## Sign-in apps

- GitHub: OAuth app "Lemma" under github.com/settings/developers, callback `https://tools.mohitranka.com/lemma/auth/github/callback`.
- Google: project `lemma-511811` → Google Auth Platform, External and in production, web client "Lemma web" with callback `https://tools.mohitranka.com/lemma/auth/google/callback`. Its privacy policy link is `https://tools.mohitranka.com/lemma/privacy`.

A new secret from either goes into `lemma.env`, followed by `push.sh`.

## Rebuilding from scratch

1. `cloudflared tunnel login`, then `cloudflared tunnel create --credentials-file deploy/cloudflared/lemma.json lemma`. Put the new tunnel id in `cloudflared/config.yml`, then run `cloudflared tunnel route dns lemma tools.mohitranka.com`.
2. Any Ubuntu VM reachable over SSH works, as long as it has about 1 GB of RAM or more.
3. Fill in `lemma.env` and run `push.sh`.

## Backups

```sh
ssh ubuntu@34.172.130.18 'sudo docker run --rm -v deploy_lemma-data:/data -v $HOME:/out alpine tar czf /out/lemma-data.tgz -C /data .'
scp ubuntu@34.172.130.18:lemma-data.tgz .
```
