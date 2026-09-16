# Migration Runbook

## Revisions 0020-0021

Both are additive, fast, and safe to run without a maintenance window.

- `0020_idempotency_key_length` adds `ck_idempotency_keys_key_length` to
  `idempotency_keys`, bounding a stored replay key at 256 characters. No
  existing row can violate it: an over-length key could never have been
  committed, because the insert that would have written it is the insert that
  failed against the column's unique btree. Deploy the application together
  with or after this revision, since `app/core/keys.py` is what keeps callers
  inside the bound.
- `0021_placement_replaced_notice` inserts the global `placement_replaced`
  notification template. An operator who has customised templates should review
  its wording afterwards in **Admin - Templates**.

Postflight: confirm revision `0021_placement_replaced_notice`, that
`notification_templates` has exactly one `placement_replaced` row with
`cycle_id IS NULL`, and that the consistency checker reports no new findings.

## Revisions 0016-0018

This runbook applies to revisions 0016–0018. Production writes are never made
with ad-hoc SQL and no local database is copied to production.

## Required preflight

1. Record the deployed Git SHA, database version, Alembic revision, UTC time,
   and maintenance owner.
2. Take and verify a logical backup outside the repository. Record its SHA-256.
3. Restore that exact backup into an isolated PostgreSQL 16 instance and run
   the complete procedure there first.
4. Reconcile these blockers before running 0017:
   - every profile carrying a legacy dual flag names its primary programme;
   - every dual degree names its secondary programme;
   - every required component programme and programme/branch mapping exists;
   - combined-programme deterministic IDs and names do not belong to unrelated
     taxonomy rows.
5. Produce a private reconciliation manifest. Each correction requires owner
   confirmation, `admin_update_profile` preview, execution through
   `core/executor.py`, and audit verification. Never infer a programme from a
   branch, graduating year, roll number, or display name without that approval.

A failing 0017 upgrade is safe: PostgreSQL rolls back the revision transaction.
Confirm the revision and absence of the new columns before attempting recovery.

## Maintenance-window execution

1. Stop API/worker writes and retain a maintenance response at the edge.
2. Confirm the preflight counts and take a final verified backup.
3. Run `alembic upgrade head` using the migration role.
4. Confirm revision `0018_rule_semantics` and run the postflight checks below.
5. Start the API, then workers, and smoke-test staff builder, student profile,
   job list/detail, apply preview, staged-row listing, and taxonomy editing.
6. Re-enable traffic only after count/hash and audit reconciliation passes.

## Postflight checks

- Users, enrollments, profiles, branches, memberships, applications, offers,
  external offers, staged rows, and pre-existing audit rows retain their counts.
- Original staged payload JSON hashes are unchanged. Pending legacy payloads
  pass the read-only adapter; ambiguous rows remain unapplied with a reason.
- Existing eligibility/join rule JSON hashes are unchanged and their versions
  are 1. Newly authored rules default to 2.
- Legacy member/job verdicts match the pre-upgrade manifest exactly.
- The only programme count increase is the reviewed set of deterministic
  combined programmes. Every combined row has two valid single-degree
  components and the expected branch map.
- Existing application profile snapshots, events, offers, and audit rows are
  byte-preserved. New history remains append-only.

## Recovery and rollback

Rollback is a release decision, not an error-handler. Stop application traffic,
preserve failure evidence, and restore the pre-release backup when any data
reconciliation fails. If application binaries alone are rolled back, first run
`alembic downgrade 0015_override_scope_domains`; revisions 0018, 0017, and 0016
are PostgreSQL-transactional.

0017 deliberately retains combined programme rows during downgrade because a
rule may reference them. Profiles are restored to legacy flags/component
programme columns. A later re-upgrade recognizes deterministic IDs and must
succeed without duplicate-name collisions. Verify the same counts and hashes
after downgrade and after re-upgrade.

Terminal staged rows are never reset in SQL. A reviewed row may be requeued only
with the `retry_staged_row` command's preview and confirmation; its original
payload and prior error remain in audit history.
