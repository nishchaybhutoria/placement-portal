# Eligibility Coverage Certification

Certifies the 2025–26 three-month internship roster — the CDS eligibility
workbook, 78 company rows — against the rule engine and the rule editor. It
answers one question: can the office state each company's eligibility in the
portal, and where can it not?

The workbook is private operational material and is not in this repository.
The row-by-row matrix, and the script that generates it, live beside it at
`placement-portal-private/workbook-coverage-2025-2026/`. This document records
the method, the certified result, and the accepted gaps.

## Method

The claim certified is existence: for each row, that a rule stating the
roster's eligibility *can* be built from the controls. Each row is compiled
into a rule tree the way the visual editor compiles one, then checked twice:
against `parse_rule` in
`backend/app/domain/rule_schema.py`, and against `decompile` in
`frontend/src/screens/jobs/RuleEditor.tsx` — the function that decides whether
a stored rule opens in the visual controls or drops to JSON. A row is
certified *visual* only when its tree round-trips through the editor byte for
byte, so the controls cannot show one rule and save another.

Free-text criteria are classified by hand, one entry per row, and the
generator fails if a row carries criteria text no entry covers.

## Result

| Rows | Outcome |
|---|---|
| 49 | Eligibility stated in full, authorable in the visual editor |
| 9 | Stated in full except an accepted data gap (below) |
| 17 | Stated in full except accepted non-eligibility text (below) |
| 3 | The roster states no eligibility: no pathway columns, no criteria |
| **78** | **0 rows require raw JSON** |

Every rule the roster asks for compiles from the controls. Nothing in the
workbook needs a group nested inside a group, which is the one shape the
editor still refuses (it opens in JSON rather than being flattened).

## The structures the roster asks for

Fixed as regression tests in `backend/tests/domain/test_roster_patterns.py`.

1. **Pathway fan-out.** One column group per programme — MTech, BTech–MTech
   dual degree, BTech 3rd/4th year and dual majors, BTech 2nd year, BTech 1st
   year, MSc, MA — each opening its own disciplines and graduating years. One
   `any` group, one option per pathway, every option a flat clause list.
2. **Conditional minor.** "Open for ME/CE/CL/MSE also if pursuing Minor in
   CSE/AI", on 14 rows. Written as one discipline list plus a condition this
   would nest a group inside an option; written as the extra pathway it really
   is, it is one more option of the same group.
3. **Per-discipline CPI floor.** "7.00 in Computer Science branches and 8.00 in
   other branches" — the floor moves inside each option rather than sitting at
   the top level.
4. **Study-year cohorts.** First, second and third/fourth-year rows, evaluated
   only against a year declared for the configured session. The dual-major
   internship rule (second discipline from fourth year) is applied by
   `app/domain/pathways.py`, not restated per company.
5. **Identity and school marks.** "Female students graduating in 2027";
   "minimum 60% in 10th and 12th". Backed by clauses added in this change —
   gender, nationality, 10th/12th percentage and year — which previously
   existed in the schema but had no control.
6. **Pathway-only rows.** 29 rows state no criteria beyond the columns.

## Accepted gaps

Approved as out of scope for this release. Neither blocks the migration or the
cycle; both are recorded so a later release can revisit them deliberately.

**Facts the profile does not record (9 rows).** Graduation percentage as
distinct from CPI; diploma marks; a school mark given on a CGPA scale rather
than as a percentage; gaps between consecutive academic courses; prior
full-time employment. A rule cannot ask what the portal never collects, and
these rows are stated to the limit of what it does collect — a "60% in 10th,
12th and graduation" row becomes the 10th and 12th halves plus CPI.

**Text that is not eligibility (17 rows).** "Read JD", programming languages,
named tools, project counts, resume screening, a written puzzle, applications
taken on an external portal, criteria defined only in an attachment, and
prior participation in an earlier test. These are screening and process, not
profile facts, and belong to the round the company runs.

## Before the cycle opens

- The roster's "Minor in CSE/AI" needs an **Artificial Intelligence minor** in
  the minors taxonomy; the seeded set is Computer Science, Entrepreneurship and
  Physics. Minors are admin-managed, so this is a taxonomy entry, not a code
  change.
- The 1st and 2nd-year columns carry their batch in the **column heading**, not
  per row. A rule for those cohorts states the study year and the batch's
  graduating year explicitly.
- Three rows select no pathway and state no criteria. One is labelled open to
  everyone, which the portal already expresses as no rule at all; the other two
  are an office question, not a portal gap.

See also `docs/ACADEMIC-ELIGIBILITY.md` for the academic contract these rules
evaluate against.
