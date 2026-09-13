# Academic Eligibility Contract

This amendment narrows Behavior PRO-1 and ELG-1/2 and LLD §§8–9. It does not
introduce a registration or application gate for academic-standing collection.
Where this document is silent, `docs/BEHAVIOR.md` and `docs/LLD.md` continue to
apply.

## Canonical academic profile

- A profile declares one programme. A programme is `single`, `dual_major`, or
  `dual_degree`.
- Combined programmes reference primary and secondary single-degree components.
  The primary branch must belong to the primary component and the secondary
  branch to the secondary component. Equal branch IDs are valid.
- Current study year is explicitly declared from 1 through 8 together with the
  configured academic session's start year. It is never inferred or advanced.
  Changing the configured session makes the old declaration stale.
- Collection status (`missing`, `stale`, or `current`) is informational in this
  release. Existing join/apply behavior does not gain a completeness gate.

## Rule facts

| Predicate | v2 meaning | Unknown when |
|---|---|---|
| `program_id` | Exact declared programme | no programme |
| `component_program_id` | Any single degree contained in that programme; a single programme contains itself | shape/components are missing or invalid |
| `discipline_id` | Disciplines permitted for the job outcome below | required programme/branch/outcome/standing is unknown |
| `study_year` | Declared year for the configured current session | session is unconfigured, or declaration is missing/stale |

For placement, a dual major may use either recorded discipline without a year
threshold. For internship, its primary discipline opens in year 3 and secondary
in year 4. A dual degree uses only its postgraduate/secondary discipline in
both pathways. A single programme uses its primary discipline.

## Version and truth contract

- Existing job and cycle-join rules are marked semantics v1 without changing
  their JSON. v1 reconstructs the former primary programme fact after combined
  programme migration and otherwise retains legacy verdict behavior.
- New or explicitly re-saved rules use v2. v2 evaluates internally as true,
  false, or unknown. Negation preserves unknown; only true is eligible.
- Conversion is never automatic. Re-saving v1 uses the normal server preview,
  displays current impact, and records before/after version in the audit log.
- Application snapshots include all derived facts used for evaluation and the
  persisted semantics version.

## Authoring safety

The visual draft and last valid compiled rule are separate. An incomplete
clause/group, invalid JSON, or duplicate JSON key disables save and live impact
preview. A tree that cannot round-trip through visual controls stays in JSON
mode rather than being flattened. Predicates may repeat.

Every predicate in the schema has a control: the academic ones, and gender,
nationality, 10th/12th percentage and 10th/12th year. JSON remains the door to
operators the controls do not offer and to a group nested inside a group.

## Acceptance matrix

| Case | Expected |
|---|---|
| Combined BTech–MTech vs v2 `program_id=MTech` | deny |
| Same profile vs v2 `component_program_id=MTech` | pass |
| Migrated BTech–MTech vs v1 `program_id=BTech` | same verdict as before migration |
| Migrated BTech–MTech vs v1 `program_id=MTech` | same denial as before migration |
| Placement dual major, either discipline, no current year | matching discipline passes |
| Internship dual major year 2, primary discipline | deny |
| Internship dual major year 3, primary/secondary | pass/deny |
| Internship dual major year 4, primary/secondary | pass/pass |
| Internship year predicate with stale session | unknown final verdict, deny |
| `not` around any unknown v2 fact | unknown final verdict, deny |
| Invalid/duplicate raw JSON or unfinished visual clause | no impact request and no save |
| Upgrade existing rules | JSON unchanged, version 1 |
| Newly inserted or confirmed rule | version 2 |
