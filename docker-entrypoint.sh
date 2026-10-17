#!/bin/sh
# Hosting platforms mount persistent disks owned by root; hand the data
# directory to the unprivileged app user, then drop root.
set -e
if [ "$(id -u)" = "0" ]; then
    mkdir -p "$SALESBOT_DATA_DIR"
    chown -R salesbot:salesbot "$SALESBOT_DATA_DIR"
    exec setpriv --reuid=salesbot --regid=salesbot --init-groups "$@"
fi
exec "$@"
