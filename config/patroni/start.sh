#!/bin/sh
# A new named volume belongs to root, and PostgreSQL refuses to run as root.
set -eu
install -d -o postgres -g postgres -m 0700 /home/postgres/pgdata
node=$(hostname)
export HOME=/home/postgres PATRONI_NAME="$node" \
    PATRONI_RESTAPI_CONNECT_ADDRESS="$node:8008" PATRONI_POSTGRESQL_CONNECT_ADDRESS="$node:5432"
exec setpriv --reuid=postgres --regid=postgres --init-groups patroni /config/patroni.yml
