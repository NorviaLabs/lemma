#!/bin/sh
# Prepares the Lemma VM (run by push.sh, safe to repeat): 2 GB of swap (an e2-micro has 1 GB of RAM) and Docker with Compose.
set -eu
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
