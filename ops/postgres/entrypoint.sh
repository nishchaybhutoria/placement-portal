#!/bin/sh
set -eu

# Named volumes start owned by root. PostgreSQL's archive command runs as the
# postgres OS user, so establish ownership before the official entrypoint drops
# privileges. The official image keeps all of its normal initialization logic.
if [ "$(id -u)" = "0" ]; then
    mkdir -p /wal_archive
    chown 999:999 /wal_archive
    chmod 700 /wal_archive

    # Existing clusters do not re-run docker-entrypoint-initdb.d. Add the
    # password-authenticated replication rule on upgrade as well as first boot.
    if [ -s "${PGDATA}/PG_VERSION" ] \
        && ! grep -q '^host replication all all scram-sha-256$' "${PGDATA}/pg_hba.conf"; then
        printf '%s\n' 'host replication all all scram-sha-256' >>"${PGDATA}/pg_hba.conf"
    fi
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"
