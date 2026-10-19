#!/bin/sh
# Prepares the Lemma VM (run by push.sh, safe to repeat): 2 GB of swap (an e2-micro has 1 GB of RAM), Docker with Compose,
# and limits that keep the disk from filling: a journal cap and a weekly prune of old images and build cache.
set -eu
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
mkdir -p /etc/systemd/journald.conf.d
journal='[Journal]
SystemMaxUse=200M'
if [ "$(cat /etc/systemd/journald.conf.d/lemma.conf 2>/dev/null)" != "$journal" ]; then
  printf '%s\n' "$journal" > /etc/systemd/journald.conf.d/lemma.conf && systemctl restart systemd-journald
fi
cat > /etc/systemd/system/lemma-prune.service <<'UNIT'
[Unit]
Description=Remove Docker images and build cache unused for a week
[Service]
Type=oneshot
ExecStart=/usr/bin/docker image prune -af --filter until=168h
ExecStart=/usr/bin/docker builder prune -af --filter until=168h
UNIT
cat > /etc/systemd/system/lemma-prune.timer <<'UNIT'
[Unit]
Description=Weekly Docker prune for Lemma
[Timer]
OnCalendar=weekly
Persistent=true
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload && systemctl enable --now lemma-prune.timer
