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
  programme: the two blockers above and one profile with no dual flags. No
  production mapping has been selected.
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

`make check` passed with 1,991 backend tests and 184 frontend tests after the
rule-version, exact-programme, component-degree, session-qualified study-year,
and safe-draft changes. `make e2e` then passed all suites: 3 critical-flow, 5
responsive/accessibility, and 25 full-lifecycle tests.

## Outstanding approval gates

1. Programme owners must identify and approve the primary programme for each of
   the two blocking dual-degree profiles. The third blank profile must be
   reviewed separately; migration does not require or guess it.
2. Rehearse again from a fresh restore using only the approved command payloads.
3. Verify zero legacy verdict differences and all hashes/counts again.
4. Run `make check` and `make e2e` on the final commit.
5. Review backup, maintenance, smoke-test, rollback, and communication owners.
6. Obtain explicit production deployment approval. Push, PR, merge, migration,
   and production commands remain out of scope until then.
