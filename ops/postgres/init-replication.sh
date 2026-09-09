#!/bin/sh
set -eu

# pg_basebackup uses PostgreSQL's replication protocol. The generated HBA file
# permits replication only from loopback, so allow password-authenticated
# replication from the private Compose network.
printf '%s\n' 'host replication all all scram-sha-256' >>"${PGDATA}/pg_hba.conf"

# Exporters receive a dedicated login with PostgreSQL's built-in read-only
# monitoring privileges. psql variable quoting keeps the generated password out
# of SQL interpolation and the role owns no application objects.
psql --set=ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set=monitor_password="${POSTGRES_MONITOR_PASSWORD:?required}" <<'EOSQL'
SELECT 'CREATE ROLE cds_monitor LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cds_monitor')\gexec
ALTER ROLE cds_monitor PASSWORD :'monitor_password';
GRANT pg_monitor TO cds_monitor;
EOSQL
