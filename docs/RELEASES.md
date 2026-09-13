# Academic Eligibility Release Evidence

No production deployment is authorized by this document. It records the
minimum evidence required before a separate maintenance-window approval.

## 2026-09-13 isolated rehearsal

Source: the verified production logical snapshot captured at revision
`0015_override_scope_domains`, restored into disposable PostgreSQL 16
containers. Private evidence is stored outside Git under
`/home/nishuz/placement-portal-private/rehearsal-20260913/`.

### Results

- An untouched restore correctly refused revision 0017 because **two legacy
  dual-degree profiles have no primary programme**. The revision remained 0015;
  profile/staging/audit counts remained 348/623/1849 and no 0016/0017 columns
  remained. This is an unresolved production release blocker.
- The private reconciliation manifest contains three profiles with no
  programme: the two blockers above and one profile with no dual flags. The
  owner subsequently confirmed both blockers are BTech–MTech dual degrees, so
  their approved legacy primary programme is the existing BTech entry; this
  mapping has not been applied to production.
- To test migration mechanics only, the two blockers were assigned BTech in the
  disposable database through preview plus the baseline
  `admin_update_profile` executor command. This was an explicit rehearsal
  assumption, added two audit rows, and **must not be copied to production or
  treated as owner approval**.
- Upgrade to `0018_rule_semantics`: passed.
- Downgrade to `0015_override_scope_domains`: passed.
- Re-upgrade to `0018_rule_semantics`: passed without ID/name collision.
- Preserved across upgrade: 378 users, 378 enrollments, 348 profiles, 15
  branches, 623 staged rows, 141 memberships, zero applications/portal offers,
  and two external offers. The migration added exactly two deterministic
  combined programmes and no audit rows.
- Staged payload hash and existing job/join-rule hashes were unchanged.
  All 277 pending clean staged rows were legacy payloads; all 277 passed the
  read-only adapter with zero mapping errors.
- Existing jobs and the existing cycle policy were marked semantics v1.
- Legacy verdict comparison evaluated 216 member/job pairs (two jobs × 108
  active members): **zero differences** between production code/data before
  migration and v1 code/data after migration.
- Downgrade/re-upgrade retained 348 profiles, 623 staged rows, 141 memberships,
  two external offers, the staged payload hash, and the job-rule hash.

### Automated evidence

The backend suite passed 1,991 tests and the refreshed frontend suite passed
185 tests after the rule-version, exact-programme, component-degree,
session-qualified study-year, and safe-draft changes. `make e2e` then passed
all suites: 3 critical-flow, 5
responsive/accessibility, and 25 full-lifecycle tests.

## 2026-09-13 roster coverage certification

The 2025–26 internship roster (78 company rows) was compiled row by row into
rule trees and checked against both the rule schema and the visual editor's
round-trip. Every row the roster states is authorable in the editor; no row
requires raw JSON. Two classes of criteria are **accepted as out of scope**
for this release by the project owner: facts the profile does not record (9
rows) and text that is screening rather than eligibility (17 rows). Three rows
state no eligibility at all in the roster and are an office question.

Method, counts and the accepted gaps: `docs/ELIGIBILITY-COVERAGE.md`. The
row-by-row matrix stays private, beside the workbook, under
`/home/nishuz/placement-portal-private/workbook-coverage-2025-2026/`.

Before the cycle opens, the minors taxonomy needs an **Artificial Intelligence**
entry: 14 roster rows open extra disciplines to students pursuing a Minor in
CSE/AI, and only Computer Science is seeded today.

## 2026-09-13 isolated rehearsal, owner-approved mapping

A second rehearsal from a fresh restore, using the approved BTech primary
programme rather than the earlier placeholder. Source: a logical dump taken
from production at 13:42:32Z, SHA-256 verified, restored into a disposable
PostgreSQL 16 container. Private evidence:
`/home/nishuz/placement-portal-private/rehearsal-20260913-approved/`.

- Blockers at restore were exactly the two known dual-degree profiles; no new
  one has appeared while the cycle has been running.
- Both corrections applied through `admin_update_profile` preview and execute,
  writing only `program_id`: two audit rows, zero profiles left blocking 0017,
  and **zero of 216 member/job verdicts changed** by the correction itself.
- Upgrade to `0018_rule_semantics`, downgrade to `0015_override_scope_domains`,
  and re-upgrade all passed. Counts, job-rule, join-rule and staged-payload
  hashes unchanged throughout; programmes rose 5 to 7 for the two reviewed
  combined rows and nothing else; existing rules carry version 1.
- Legacy verdict comparison: **216 of 216 identical**, deployed code before
  against release code after, and identical again after downgrade and
  re-upgrade.
- All 272 pending staged rows are legacy payloads and passed the read-only
  adapter with zero mapping errors.

Two findings changed the runbook:

1. **The corrections must be made before the release is deployed**, with the
   code currently running. The release code reads `study_year`, a column 0016
   adds, so it cannot edit a profile on the pre-migration schema.
2. **`academic_session_start_year` is unset in production.** Until it is set,
   every v2 rule that names a current study year evaluates unknown and denies,
   and a dual major's internship disciplines cannot be derived. The live cycle
   is a placement cycle, so nothing is affected today; it must be set before
   internship jobs are authored.

## Outstanding approval gates

1. Apply the two corrections in production, on the deployed code, through
   previewed `admin_update_profile` commands, and verify their audits. The
   third blank profile must be reviewed separately; migration does not require
   or guess it.
2. Take and verify the final backup immediately before the window.
3. Verify zero legacy verdict differences and all hashes/counts again.
4. Set `academic_session_start_year` before internship jobs are authored.
5. Review backup, maintenance, smoke-test, rollback, and communication owners.
6. Obtain explicit production deployment approval. Push, PR, merge, migration,
   and production commands remain out of scope until then.
