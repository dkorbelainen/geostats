#!/bin/sh
# Weekly disk reclaim for the geostats VPS host.
# Idempotent and safe to re-run; never touches db_data or caddy volumes.
set -u

docker image prune -af >/dev/null 2>&1 || true
docker builder prune -af >/dev/null 2>&1 || true

apt-get clean >/dev/null 2>&1 || true
DEBIAN_FRONTEND=noninteractive apt-get autoremove -y --purge >/dev/null 2>&1 || true

journalctl --vacuum-time=7d >/dev/null 2>&1 || true
find /var/log -maxdepth 1 -name '*.gz' -mtime +14 -delete 2>/dev/null || true

df -h / | tail -1
