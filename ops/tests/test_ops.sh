#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

for script in ops/postgres/*.sh ops/backup/bin/* ops/drill/*.sh; do
    bash -n "$script"
done

services="$(SESSION_SECRET=cds-ops-check-session-secret-32-chars docker compose config --services)"
for required in db migrate api worker alert-relay backup caddy; do
    grep -qx "$required" <<<"$services"
done

rendered="$(mktemp)"
trap 'rm -f "$rendered"' EXIT
SESSION_SECRET=cds-ops-check-session-secret-32-chars docker compose config >"$rendered"
grep -q 'archive_mode=on' "$rendered"
grep -q 'archive_command=/opt/cds/archive-wal %p %f' "$rendered"
# archive_timeout is half of the recovery point objective -- a segment waits up
# to this long to close, then up to the five-minute sync to reach Drive -- so
# LLD.md G5 quotes a number that only this line makes true. Raising it silently
# lengthens the window of writes a disk loss would take with it.
grep -q 'archive_timeout=300s' "$rendered"
grep -q 'RPO ≈ 10 min' docs/LLD.md
grep -q 'ops/postgres/archive-wal.sh' "$rendered"
grep -q -- '--workers' "$rendered"
grep -q 'app.worker.procrastinate_app' "$rendered"
grep -q 'app.alert_relay:app' "$rendered"
grep -q '/etc/caddy/tls/fullchain.pem' Caddyfile
grep -q 'header_up X-Request-ID' Caddyfile
grep -q 'request>headers>X-Csrf delete' Caddyfile
grep -Fq 'request>uri regexp "^([^?]*).*$" "${1}"' Caddyfile
grep -q 'log_skip /auth/\*' Caddyfile
docker run --rm \
    -v "$repo_root/Caddyfile:/etc/caddy/Caddyfile:ro,Z" \
    caddy:2.11.4-alpine \
    caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null

obs_rendered="$(mktemp)"
dashboard_rules="$(mktemp)"
trap 'rm -f "$rendered" "$obs_rendered" "$dashboard_rules"' EXIT
SESSION_SECRET=cds-ops-check-session-secret-32-chars \
    POSTGRES_MONITOR_PASSWORD=cds-monitor-test \
    docker compose -f ops/observability/docker-compose.yml config >"$obs_rendered"
for required in prometheus loki alloy alertmanager grafana node-exporter cadvisor postgres-exporter blackbox-exporter; do
    grep -qx "$required" < <(docker compose -f ops/observability/docker-compose.yml config --services)
done
grep -q 'host_ip: 127.0.0.1' "$obs_rendered"
grep -q 'cds-observability' "$obs_rendered"
grep -q -- '--server.http.listen-addr=0.0.0.0:12345' "$obs_rendered"
[[ "$(grep -c 'datasourceUid: loki' ops/observability/grafana/provisioning/datasources/datasources.yml)" == "2" ]]
grep -Fq '| json | request_id="$${__value.raw}"' ops/observability/grafana/provisioning/datasources/datasources.yml
grep -Fq '| json | command_execution_id="$${__value.raw}"' ops/observability/grafana/provisioning/datasources/datasources.yml

for dashboard in ops/observability/grafana/dashboards/*.json; do
    python3 -m json.tool "$dashboard" >/dev/null
done
python3 - "$dashboard_rules" <<'PY'
import json
import sys
from pathlib import Path

required = {
    "backup.json": {
        "Backup metrics target",
        "Remote copying",
        "Local base backups",
        "WAL sync age",
        "Logical dump age",
        "Base backup age",
        "Attempt state",
        "Backup errors and warnings",
    },
    "overview.json": {
        "Firing alerts",
        "API target",
        "Backup target",
        "Worker target",
        "PostgreSQL target",
        "Public probes",
        "TLS days remaining",
        "HTTP 5xx percentage",
        "HTTP errors by route",
        "Slowest API routes (p95)",
        "Command execution rate",
        "Command p95 duration",
        "Errors and warnings",
    },
    "infrastructure.json": {
        "Node exporter",
        "cAdvisor",
        "Host CPU busy",
        "Memory available",
        "Lowest filesystem free",
        "Container CPU by service",
        "Container memory by service",
        "Container restarts (15m)",
        "Container OOM events (1h)",
        "Monitoring scrape health",
    },
    "postgresql.json": {
        "PostgreSQL target",
        "Exporter scrape",
        "Connection utilization",
        "Buffer cache hit ratio",
        "Locks by mode",
        "Checkpoint activity",
        "Tables with the most dead rows",
    },
    "workflow.json": {
        "Worker target",
        "Command error rate",
        "Command execution rate by outcome",
        "Command p95 duration by name",
        "Worker job completions",
        "Worker errors",
        "Periodic task activity",
    },
}

root = Path("ops/observability/grafana/dashboards")
uids: set[str] = set()
for filename, expected_titles in required.items():
    dashboard = json.loads((root / filename).read_text())
    uid = dashboard["uid"]
    if uid in uids:
        raise SystemExit(f"duplicate Grafana dashboard UID: {uid}")
    uids.add(uid)
    titles = {panel["title"] for panel in dashboard["panels"]}
    missing = expected_titles - titles
    if missing:
        raise SystemExit(f"{filename} is missing panels: {sorted(missing)}")

expressions: list[str] = []
for path in sorted(root.glob("*.json")):
    dashboard = json.loads(path.read_text())
    for panel in dashboard["panels"]:
        if panel.get("datasource", {}).get("type") != "prometheus":
            continue
        for target in panel.get("targets", []):
            expression = target.get("expr")
            if expression:
                expressions.append(
                    expression.replace("$database", ".*")
                    .replace("$compose_project", ".*")
                    .replace("$__range", "1h")
                )

with Path(sys.argv[1]).open("w") as rules:
    rules.write("groups:\n  - name: dashboard-expressions\n    rules:\n")
    for index, expression in enumerate(expressions):
        rules.write(f"      - record: dashboard_expr_{index}\n")
        rules.write(f"        expr: {json.dumps(expression)}\n")
PY
chmod 0644 "$dashboard_rules"

docker run --rm --entrypoint /bin/promtool \
    -v "$repo_root/ops/observability/prometheus:/etc/prometheus:ro,Z" \
    prom/prometheus:v3.4.1 \
    check config /etc/prometheus/prometheus.yml
docker run --rm --entrypoint /bin/promtool \
    -v "$dashboard_rules:/tmp/dashboard-rules.yml:ro,Z" \
    prom/prometheus:v3.4.1 \
    check rules /tmp/dashboard-rules.yml
docker run --rm --entrypoint /bin/promtool \
    -v "$repo_root/ops/observability/prometheus/rules:/rules:ro,Z" \
    -w /rules \
    prom/prometheus:v3.4.1 \
    test rules portal.test.yaml

grep -q '@app.periodic(cron="0 \* \* \* \*")' backend/app/worker.py
grep -q '@app.task(name="send_deadline_reminders")' backend/app/worker.py
grep -q '@app.periodic(cron="0 \*/6 \* \* \*")' backend/app/worker.py
grep -q '@app.task(name="send_round_reminders")' backend/app/worker.py

cron_jobs="$(grep -Ev '^[[:space:]]*(#|$)' ops/backup/crontab | wc -l | tr -d ' ')"
[[ "$cron_jobs" == "3" ]]
grep -q '^\*/5 \* \* \* \* /opt/backup/bin/record-backup-metrics wal_sync /opt/backup/bin/wal-sync ' ops/backup/crontab
grep -q '^0 2 \* \* \* /opt/backup/bin/record-backup-metrics base_backup /opt/backup/bin/base-backup ' ops/backup/crontab
grep -q 'gzip -c -6' ops/postgres/archive-wal.sh
grep -q 'gzip -c -6' ops/backup/bin/wal-sync
grep -q 'gzip -dc' ops/backup/bin/restore-physical
grep -q 'BASE_RETENTION_COUNT' ops/backup/bin/prune-retention
grep -q '^0 3 \* \* \* /opt/backup/bin/record-backup-metrics logical_dump /opt/backup/bin/logical-dump ' ops/backup/crontab

grep -q 'targets: \[backup:9100\]' ops/observability/prometheus/prometheus.yml
for alert in BackupTargetMissing BackupRemoteDisabled BackupAttemptFailing BackupWalSyncStale BackupLogicalDumpStale BackupBaseBackupStale BackupBaseRedundancyLow; do
    grep -q "alert: $alert" ops/observability/prometheus/rules/portal.yml
done
for job in alertmanager loki alloy grafana blackbox-exporter; do
    grep -q "job_name: $job" ops/observability/prometheus/prometheus.yml
done
for alert in ObservabilityTargetMissing ContainerRestartLoop ContainerOomKilled PostgresConnectionsSaturated PostgresDeadlocksDetected PostgresLongTransaction CommandExecutionFailed PrometheusRuleEvaluationFailures PrometheusAlertDeliveryFailing MonitoringConfigurationReloadFailed; do
    grep -q "alert: $alert" ops/observability/prometheus/rules/portal.yml
done

metrics_test_dir="$(mktemp -d)"
trap 'rm -f "$rendered" "$obs_rendered" "$dashboard_rules"; rm -rf "$metrics_test_dir"' EXIT
metrics_env=(
    BACKUP_METRICS_DIR="$metrics_test_dir/metrics"
    BACKUP_BASE_DIR="$metrics_test_dir/base"
    WAL_ARCHIVE_DIR="$metrics_test_dir/wal"
    BACKUP_REMOTE_ENABLED=1
)
mkdir -p "$metrics_test_dir/base" "$metrics_test_dir/wal"
env "${metrics_env[@]}" bash ops/backup/bin/backup-metrics init
env "${metrics_env[@]}" bash ops/backup/bin/record-backup-metrics wal_sync true
if env "${metrics_env[@]}" bash ops/backup/bin/record-backup-metrics logical_dump false; then
    echo 'failing backup metric probe unexpectedly succeeded' >&2
    exit 1
fi
env "${metrics_env[@]}" bash ops/backup/bin/record-backup-metrics base_backup bash -c 'sleep 1' &
metrics_pid=$!
sleep 0.1
env "${metrics_env[@]}" bash ops/backup/bin/record-backup-metrics base_backup true
wait "$metrics_pid"
grep -q 'cds_backup_last_attempt_success{kind="wal_sync"} 1' "$metrics_test_dir/metrics/web/metrics"
grep -q 'cds_backup_consecutive_failures{kind="logical_dump"} 1' "$metrics_test_dir/metrics/web/metrics"
grep -q 'cds_backup_skipped_total{kind="base_backup"} 1' "$metrics_test_dir/metrics/web/metrics"
docker run --rm -i --entrypoint /bin/promtool \
    prom/prometheus:v3.4.1 \
    check metrics <"$metrics_test_dir/metrics/web/metrics"

# Make targets are the source of truth for executable procedures. Public
# documentation may cite them but must not duplicate command bodies that drift.
# a cited target that does not exist is a runbook step nobody can follow, and
# that is a failure a reader discovers at the worst possible moment.
targets="$(grep -oE '^[a-zA-Z0-9_-]+:' Makefile | tr -d ':' | sort -u)"
cited="$(grep -rhoE '`make [a-z][a-z0-9-]+`' README.md docs/*.md \
    | sed -e 's/^`make //' -e 's/`$//' | sort -u)"
for target in $cited; do
    grep -qx "$target" <<<"$targets" || {
        echo "documented Make target does not exist: make $target" >&2
        exit 1
    }
done

# A restored cluster keeps the source cluster's roles and passwords, so every
# drill client must authenticate with the same .env the source stack used. The
# drill's --project-directory is ops/drill, where Compose finds no .env, so
# without an explicit --env-file the credentials fall back to the development
# defaults and the rehearsal fails after a successful recovery. This is
# invisible on a development host, where both sides default to `cds` and match.
grep -q -- '--env-file' ops/drill/run.sh || {
    echo "ops/drill/run.sh must pass --env-file to the drill compose project" >&2
    exit 1
}

echo 'ops configuration checks passed'
