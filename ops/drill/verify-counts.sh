#!/usr/bin/env bash
set -Eeuo pipefail

actual="$(mktemp)"
trap 'rm -f "$actual"' EXIT

psql --no-psqlrc --set ON_ERROR_STOP=1 --tuples-only --no-align --field-separator='|' >"$actual" <<'SQL'
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

if ! diff -u "$EXPECTED_COUNTS_FILE" "$actual"; then
    echo "restore drill count verification failed" >&2
    exit 1
fi

echo "restored row counts match the source snapshot"
cat "$actual"
