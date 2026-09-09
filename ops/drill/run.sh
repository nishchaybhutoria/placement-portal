#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source_compose=(docker compose --project-directory "$repo_root" -f "$repo_root/docker-compose.yml")

# The source stack's --project-directory is the repository root, so Compose
# loads the root .env by itself. The drill's is ops/drill, where there is no
# .env, so POSTGRES_PASSWORD and CDS_APP_DB_PASSWORD silently fell back to the
# `:-cds` development defaults in ops/drill/docker-compose.yml.
#
# A restored cluster carries the *source* cluster's roles and passwords -- the
# postgres image skips initialisation when PGDATA already holds a database, so
# POSTGRES_PASSWORD on the drill's db service changes nothing. Every drill
# client that authenticates therefore used the wrong password, and the whole
# rehearsal failed after a completely successful recovery with
# `password authentication failed for user "cds"`.
#
# It survived because a development .env sets no password: both sides defaulted
# to `cds` and matched. It could only ever fail against a production .env --
# which is precisely the run the launch ticket requires. RUNBOOK section 8's
# manual path already passes --env-file; this is the runner catching up to it.
drill_env_file=()
if [[ -f "$repo_root/.env" ]]; then
    drill_env_file=(--env-file "$repo_root/.env")
fi
drill_compose() {
    COMPOSE_PROJECT_NAME="${DRILL_PROJECT_NAME:-cds-restore-drill}" \
        docker compose \
        "${drill_env_file[@]}" \
        --project-directory "$repo_root/ops/drill" \
        -f "$repo_root/ops/drill/docker-compose.yml" \
        "$@"
}
expected_dir="$(mktemp -d /tmp/cds-drill-expected.XXXXXX)"
drill_started=0
configured_remote_root="$("${source_compose[@]}" config --format json | python3 -c \
    'import json, sys; print(json.load(sys.stdin)["services"]["backup"]["environment"]["RCLONE_ROOT"])')"
drill_remote_root="${DRILL_RCLONE_ROOT:-$configured_remote_root}"

cleanup() {
    status=$?
    if (( drill_started )); then
        if (( status != 0 )); then
            drill_compose logs --no-color >&2 || true
        fi
        drill_compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    fi
    rm -rf "$expected_dir"
    # The staged copy of base+WAL is a second full copy of the backup set --
    # 1.7 GB on the machine this was written on -- and used to sit in the
    # backup volume until the next drill overwrote it. A machine that drills
    # repeatedly filled its disk; this one did.
    "${source_compose[@]}" run --rm --no-deps --entrypoint rm \
        backup -rf /backups/drill-remote >/dev/null 2>&1 || true
    return "$status"
}
trap cleanup EXIT

# Every image the drill runs is rebuilt first. `docker compose run` will happily
# start a stale image, and a drill that rehearses last week's code has rehearsed
# nothing: this one failed on `Can't locate revision identified by
# '0012_application_event_order'` -- a migrate image older than the migration
# the database already had.
# The application compose file declares this network external, so every
# `docker compose` call against it fails with "network cds-observability
# declared as external, but could not be found" until someone has run
# the production observability setup. The drill does not need monitoring; it needs
# the file to load.
if ! docker network inspect cds-observability >/dev/null 2>&1; then
    printf '%s\n' '[drill] creating the cds-observability network the compose file declares'
    docker network create cds-observability >/dev/null
fi

printf '%s\n' '[drill] building the images this drill runs'
"${source_compose[@]}" build migrate api backup

printf '%s\n' '[drill] starting source database and applying the release gate'
"${source_compose[@]}" up -d --wait db
"${source_compose[@]}" run --rm migrate

printf '%s\n' '[drill] creating and uploading a fresh physical base backup'
"${source_compose[@]}" run --rm --no-deps \
    -e "RCLONE_ROOT=${drill_remote_root}" \
    -e BACKUP_REMOTE_ENABLED=1 \
    backup /opt/backup/bin/record-backup-metrics base_backup /opt/backup/bin/base-backup

printf '%s\n' '[drill] committing a pre-target consistency pass through the executor'
"${source_compose[@]}" run --rm --no-deps api python -m ops.check_consistency

target="$("${source_compose[@]}" exec -T db psql \
    --username "${POSTGRES_USER:-cds}" \
    --dbname "${POSTGRES_DB:-cds}" \
    --tuples-only --no-align \
    --command "SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')")"
printf '[drill] PITR target: %s\n' "$target"

"${source_compose[@]}" exec -T db psql \
    --username "${POSTGRES_USER:-cds}" \
    --dbname "${POSTGRES_DB:-cds}" \
    --set ON_ERROR_STOP=1 \
    --tuples-only --no-align --field-separator='|' >"$expected_dir/counts.txt" <<'SQL'
SELECT table_name, row_count
FROM (
    SELECT 'application_events' AS table_name, count(*) AS row_count FROM application_events
    UNION ALL SELECT 'applications', count(*) FROM applications
    UNION ALL SELECT 'audit_log', count(*) FROM audit_log
    UNION ALL SELECT 'companies', count(*) FROM companies
    UNION ALL SELECT 'consistency_findings', count(*) FROM consistency_findings
    UNION ALL SELECT 'cycles', count(*) FROM cycles
    UNION ALL SELECT 'enrollments', count(*) FROM enrollments
    UNION ALL SELECT 'external_offers', count(*) FROM external_offers
    UNION ALL SELECT 'jobs', count(*) FROM jobs
    UNION ALL SELECT 'cycle_memberships', count(*) FROM cycle_memberships
    UNION ALL SELECT 'offers', count(*) FROM offers
    UNION ALL SELECT 'users', count(*) FROM users
) AS counts
ORDER BY table_name;
SQL

# A committed transaction after the target proves recovery stopped at the
# requested instant rather than merely opening the base backup.
sleep 1
printf '%s\n' '[drill] committing a post-target transaction and archiving its WAL'
"${source_compose[@]}" run --rm --no-deps api python -m ops.check_consistency
wal_segment="$("${source_compose[@]}" exec -T db psql \
    --username "${POSTGRES_USER:-cds}" \
    --dbname "${POSTGRES_DB:-cds}" \
    --tuples-only --no-align \
    --command "SELECT pg_walfile_name(pg_switch_wal() - 1)")"

# `archive_command` writes `<segment>.gz`; a database archived before that
# change, or restored from one, still holds the native name. Accept either, so
# the drill measures whether the segment was archived rather than which naming
# generation the host happens to be on.
archived() {
    "${source_compose[@]}" exec -T db sh -c \
        "test -f '/wal_archive/${wal_segment}.gz' || test -f '/wal_archive/${wal_segment}'"
}
for _ in $(seq 1 60); do
    if archived; then
        break
    fi
    sleep 1
done
if ! archived; then
    printf '[drill] WAL segment was not archived: %s (looked for .gz and native)\n' \
        "$wal_segment" >&2
    exit 1
fi
"${source_compose[@]}" run --rm --no-deps \
    -e "RCLONE_ROOT=${drill_remote_root}" \
    -e BACKUP_REMOTE_ENABLED=1 \
    backup /opt/backup/bin/record-backup-metrics wal_sync /opt/backup/bin/wal-sync
printf '%s\n' '[drill] creating and uploading a fresh logical dump for the fallback leg'
"${source_compose[@]}" run --rm --no-deps \
    -e "RCLONE_ROOT=${drill_remote_root}" \
    -e BACKUP_REMOTE_ENABLED=1 \
    backup /opt/backup/bin/record-backup-metrics logical_dump /opt/backup/bin/logical-dump

# The target is already known, so staging can download the one base the restore
# will open and only the WAL at or after it, instead of mirroring the entire
# retained archive out of Drive.
"${source_compose[@]}" run --rm --no-deps \
    -e "RCLONE_ROOT=${drill_remote_root}" \
    -e BACKUP_REMOTE_ENABLED=1 \
    -e "PITR_TARGET_TIME=${target}" \
    backup /opt/backup/bin/stage-restore-drill

source_db_id="$("${source_compose[@]}" ps -q db)"
source_project="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$source_db_id")"
source_backup_volume="$(docker volume ls \
    --filter "label=com.docker.compose.project=${source_project}" \
    --filter 'label=com.docker.compose.volume=backup_cache' \
    --format '{{.Name}}')"
if [[ -z "$source_backup_volume" ]]; then
    printf '%s\n' '[drill] could not locate the source backup volume' >&2
    exit 1
fi

export PITR_TARGET_TIME="$target"
export SOURCE_BACKUP_VOLUME="$source_backup_volume"
export DRILL_EXPECTED_DIR="$expected_dir"
export DRILL_PROJECT_NAME="${source_project}-restore-drill"

printf '[drill] restoring remote base + WAL from volume %s\n' "$source_backup_volume"
drill_started=1
drill_compose down --volumes --remove-orphans >/dev/null 2>&1 || true
drill_compose up --build -d --wait db
drill_compose logs --no-color db | grep -E \
    'starting point-in-time recovery|recovery stopping before commit|archive recovery complete'
drill_compose run --rm --no-deps --build verify
printf '%s\n' '[drill] running the application consistency checker on the restored database'
drill_compose run --rm --no-deps --build checker

# RUNBOOK section 9's fallback, exercised rather than assumed. `pg_dump` writes
# an ACL as GRANTs only, so `pg_restore --clean` hands application_events and
# audit_log back with the DELETE and UPDATE that migration 0002's ALTER DEFAULT
# PRIVILEGES supplies -- silently repealing append-only history on the one path
# an operator reaches for mid-incident. The restore re-asserts the revokes; the
# proof after it is independent, so a drill cannot pass on a self-check that is
# no longer there.
printf '%s\n' '[drill] restoring the newest logical dump over the recovered database'
drill_compose run --rm --no-deps --build restore-logical
printf '%s\n' '[drill] proving the restored database is still append-only for cds_app'
drill_compose run --rm --no-deps --build append-only

printf '%s\n' '[drill] PASS: physical PITR, count verification, consistency checker, logical fallback, and append-only proof succeeded'
