#!/usr/bin/env bash
set -Eeuo pipefail

# Prove, from outside and as the application role itself, that the restored
# database still refuses to rewrite history (CONTRIBUTING.md invariant 4, guarantee
# G6).
#
# `restore-logical` re-asserts these grants and verifies them on its own way
# out. This runs the proof again, independently: a drill that can only report
# what the restore script said about itself cannot detect the failure it exists
# to detect. Deleting the re-assert from `restore-logical` has to fail the
# drill, not merely make it quieter.
#
# The negative cases are real statements, not `has_table_privilege` lookups.
# They carry `WHERE false` so a database that wrongly permits them destroys
# nothing while it fails the drill.

: "${PGHOST:?PGHOST is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"

tables=(application_events audit_log)

fail() {
    printf 'append-only proof failed: %s\n' "$1" >&2
    exit 1
}

run_sql() {
    psql --no-psqlrc --set ON_ERROR_STOP=1 --tuples-only --no-align --command "$1"
}

# A refusal only proves something if the connection and the table are real.
if [[ "$(run_sql "SELECT current_user")" != "cds_app" ]]; then
    fail "the proof must run as cds_app, not $(run_sql 'SELECT current_user')"
fi

for table in "${tables[@]}"; do
    if [[ "$(run_sql "SELECT to_regclass('public.${table}') IS NOT NULL")" != "t" ]]; then
        fail "${table} does not exist on the restored database"
    fi
    run_sql "SELECT count(*) FROM ${table}" >/dev/null

    privileges="$(run_sql "SELECT coalesce(string_agg(DISTINCT privilege_type, ',' \
        ORDER BY privilege_type), '') \
        FROM information_schema.role_table_grants \
        WHERE grantee = 'cds_app' AND table_schema = 'public' \
          AND table_name = '${table}'")"
    if [[ "$privileges" != "INSERT,SELECT" ]]; then
        fail "cds_app holds [${privileges}] on ${table}, expected [INSERT,SELECT]"
    fi

    for statement in \
        "DELETE FROM ${table} WHERE false" \
        "UPDATE ${table} SET created_at = created_at WHERE false" \
        "TRUNCATE ${table}"; do
        if error="$(psql --no-psqlrc --set ON_ERROR_STOP=1 --quiet \
            --command "$statement" 2>&1 >/dev/null)"; then
            fail "cds_app was allowed to run: ${statement}"
        fi
        if ! grep -qi 'permission denied\|must be owner' <<<"$error"; then
            fail "'${statement}' was refused for the wrong reason: ${error}"
        fi
    done

    printf 'append-only holds on %s: SELECT,INSERT only; DELETE, UPDATE and TRUNCATE refused\n' \
        "$table"
done

printf 'restored database is append-only for cds_app on: %s\n' "${tables[*]}"
