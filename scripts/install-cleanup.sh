#!/bin/sh
# Install weekly disk-cleanup cron on the VPS host. Run once as root.
# Re-running is idempotent (overwrites the cron entry).
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
chmod +x "$HERE/cleanup.sh"

cat > /etc/cron.d/geostats-cleanup <<EOF
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
0 4 * * 0 root $HERE/cleanup.sh >> /var/log/geostats-cleanup.log 2>&1
EOF
chmod 644 /etc/cron.d/geostats-cleanup

echo "installed: $HERE/cleanup.sh runs weekly Sun 04:00 UTC"
echo "log:       /var/log/geostats-cleanup.log"
