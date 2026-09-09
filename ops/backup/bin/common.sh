#!/usr/bin/env bash
set -Eeuo pipefail

export TZ="${TZ:-UTC}"
export RCLONE_CONFIG="${RCLONE_CONFIG:-/config/rclone/rclone.conf}"

log() {
    printf '%s backup[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(basename "$0")" "$*"
}

require_env() {
    local name
    for name in "$@"; do
        if [[ -z "${!name:-}" ]]; then
            log "required environment variable is empty: ${name}"
            return 1
        fi
    done
}

remote_enabled() {
    [[ "${BACKUP_REMOTE_ENABLED:-1}" == "1" ]]
}

remote_root() {
    require_env RCLONE_ROOT
    printf '%s' "${RCLONE_ROOT%/}"
}

ensure_backup_directories() {
    mkdir -p /backups/base /backups/dumps
    if remote_enabled; then
        local root
        root="$(remote_root)"
        rclone mkdir "${root}/wal"
        rclone mkdir "${root}/base"
        rclone mkdir "${root}/dumps"
    fi
}

wait_for_postgres() {
    require_env PGHOST PGPORT PGUSER PGDATABASE PGPASSWORD
    local attempt
    for attempt in $(seq 1 60); do
        if pg_isready --quiet; then
            return 0
        fi
        sleep 2
    done
    log "PostgreSQL did not become ready in 120 seconds"
    return 1
}

# CONTRIBUTING.md invariant 4 -- guarantee G6, append-only history -- is a database
# permission, and a logical restore repeals it silently. `pg_dump` records an
# ACL as GRANTs and never as REVOKEs, while migration 0002_grants leaves
# ALTER DEFAULT PRIVILEGES granting cds_app full CRUD on every newly created
# table. So `pg_restore --clean` recreates these tables with DELETE and UPDATE
# available to the application role, and the dump's own "GRANT SELECT,INSERT"
# adds nothing that takes them back.
#
# Migration 0002_grants is the source of truth for this list; if it grows, this
# grows with it.
APPEND_ONLY_TABLES=(application_events audit_log)

# Re-assert the append-only revokes and prove they hold, failing loudly if they
# do not. A restore that leaves history deletable is worse than no restore.
assert_append_only_grants() {
    require_env PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE
    local table privileges
    for table in "${APPEND_ONLY_TABLES[@]}"; do
        psql --no-psqlrc --quiet --set ON_ERROR_STOP=1 \
            --command "REVOKE ALL PRIVILEGES ON TABLE ${table} FROM cds_app" \
            --command "GRANT SELECT, INSERT ON TABLE ${table} TO cds_app"
    done
    for table in "${APPEND_ONLY_TABLES[@]}"; do
        privileges="$(psql --no-psqlrc --set ON_ERROR_STOP=1 --tuples-only --no-align \
            --command "SELECT coalesce(string_agg(DISTINCT privilege_type, ',' \
                ORDER BY privilege_type), '') \
                FROM information_schema.role_table_grants \
                WHERE grantee = 'cds_app' AND table_schema = 'public' \
                  AND table_name = '${table}'")"
        if [[ "$privileges" != "INSERT,SELECT" ]]; then
            log "append-only repealed: cds_app holds [${privileges}] on ${table}, expected [INSERT,SELECT]"
            return 1
        fi
    done
    log "append-only verified: cds_app holds SELECT,INSERT only on ${APPEND_ONLY_TABLES[*]}"
}
