# Placement Portal — Complete Features & Behavior Specification (v2.3)

**Status:** Implemented product contract. **This document fully supersedes v1** — read it standalone; nothing from v1 survives unless restated here. Every feature carries a stable ID for reference. If a case is not described here, it is not specified and should fail closed until the policy is decided. Historical confirmations have been resolved into the text below.

### What changed in v2.3
1. **Job cancellation now terminates open offers** (kind `company_revoked`, reason job-cancelled) so no unresponded offer dangles behind a rejected application; accepted applications are listed as untouched in the preview (JOB-5).
2. **Open-cycle straight-to-accepted is formally a composed transition** — extend→accept (or extend→decline) in one transaction with two events, preserving APP-4's "nothing outside the table" (JOB-6).
3. **Restoring an auto-declined application** (offer termination) re-extends a **fresh Offer row** with a staff-set optional new deadline — the old offer stays declined in history (OFR-5).
4. **Editing a job's offer-acceptance deadline propagates** to that job's open (unresponded, unterminated) offers and reschedules their expiry (JOB-3).
5. **`duplicate_application` removed from override domains** — the one-active-application rule is a database constraint and structurally cannot be overridden; reinstatement and direct offer are the sanctioned paths (INT-2).
6. Mechanism-level fixes recorded in the LLD: per-enrollment lock serializing all placed-state mutations (closes a cross-cycle double-accept race); coordinator is assignment-derived, not a user-role value; cycle-policy row auto-created with kind defaults; reinstate blocked while another active application exists; archived-cycle guard made explicit in the gates.

### What changed in v2.2 (final confirmations)
1. **B/C/D/F locked as proposed:** external offers student-visible read-only; profile field table as written; who-does-what as tabled; attachment auto-registers the student in the target cycle.
2. **G resolved — internship gating is same-cycle and applies to dedicated internship cycles only; open cycles are exempt in both directions** (ELG-3.6, OFR-3, DER-1). Season groups rejected.
3. Ripple of G: **`max_accepted_offers` is now nullable (= uncapped)**, defaulting to 1 for placement/internship cycles and **uncapped for open cycles** — otherwise the cap would re-block the multiple open-cycle internships G just allowed (CYC-2, ELG-3.7). Placement stays limited to one everywhere by the universal gate regardless of caps.
4. **EXT-3 concretized (your F question):** recording and attaching are decoupled in time — offers are recorded cycle-less, wait in a visible *unattached pool*, and are attached per-offer or in bulk once the cycle exists; dedicated-cycle pages surface matching unattached offers for one-click bulk attach.

### What changed in v2.1 (your latest round)
1. **Resume links: URL-shape check only** — the public-accessibility probe is deleted (PRO-3).
2. **Cycle start/end dates are informational only**, stated explicitly; behavior is gated solely by the registration window, active flag, and archival (CYC-1).
3. **Open-cycle jobs:** custom questions confirmed present; **application deadline is optional**; no acceptance deadline exists; staff-recorded outcomes confirmed (JOB-6).
4. **Outcome gate & cascade re-scoped per outcome:** placement stays universal; **internship is cycle-scoped**, so second-/third-year summers, winter, and 6-month stints in different cycles coexist (ELG-3.6, DER-1, OFR-3, EXT-3). Season grouping was rejected.
5. **State-change consistency doctrine added** (§16) — the general answer to "what stops a state edit from orphaning its downstream consequences," including fire-time re-validation of scheduled tasks (OFR-4).
6. Bulk-upsert key confirmed: institute email + roll cross-check, applied to the current enrollment (PRO-2).

### What changed since v1 (for fast re-reading)
1. **Cycle kinds are now a system enum** — `placement`, `internship`, `open` — with hard behavioral semantics (CYC-1). The one-active-cycle-per-type constraint and its setting are **deleted entirely**; any number of any kind may be active, managed by hand.
2. **Open cycles** (new): joinable by any student with a complete profile, auto-active on join, containing **lightweight jobs** — eligibility + application + staff-recorded final outcomes; no rounds, no attendance, no venue machinery (JOB-6).
3. **Every job has a fixed outcome** — `internship` or `placement` — set at creation, immutable. In dedicated cycles it is forced to the cycle kind; in open cycles it is chosen per job (a company offering both = two jobs) (JOB-1).
4. **External Offers** (new, replaces the old informational-job hack): standalone records for PPOs and off-campus offers, cycle-independent at creation (the placement cycle may not exist yet), full CRUD, later **attachable** to a matching dedicated cycle for cap and analytics (EXT-1..4). The old `ppo`/`off_campus` job kinds are gone — every job is a real job.
5. **Two independent placed dimensions** per enrollment — *internship-placed* and *placement-placed* — derived from accepted offers of that outcome from **any** source (any cycle's job, or an external offer, attached or not). Accepting a PPO ⇒ placement-placed; declining it leaves you fully eligible (DER-1).
6. **Hard universal outcome gate + universal cascade:** being X-placed blocks applying to any X-outcome job anywhere; accepting an X-outcome offer auto-declines your other X-outcome offers and auto-withdraws your in-flight X-outcome applications **across all cycles**. The old per-cycle cascade toggles are deleted — this is invariant behavior (ELG-3, OFR-3).
7. **Membership approval** (new): joining a cycle can require staff approval — per-cycle toggle, default ON for placement/internship, OFF for open. Pending members see only a status screen; rejection carries a reason and is re-requestable (CYC-3).
8. Offer expiry default = **auto-decline** (per-cycle setting, `auto_accept` selectable) (OFR-4).
9. Cycle archival **force auto-withdraws** unresolved applications (CYC-1). Rejected applications block re-applying (APP-2). Membership outcome tags for NIRF denominators are in (ANA-3).

---

## 1. Identity & Access

### IDN-1 — Sign-in
Google OAuth is restricted to the configured institution domain (`example.edu` in the checked-in demo defaults), enforced server-side on the callback (the Google-side hint is UX only). First sign-in auto-creates a `User` — UUID primary key, name + institute email captured. **Email is unique on `users` and is never a key anywhere else.** Sessions: server-side, httpOnly/Secure/SameSite=Lax cookie, fixed lifetime, POST-only logout. Deactivated users authenticate at Google but are refused a session. OAuth-outage lockout is an accepted risk (rare; recovery is config repair, no password fallback exists).

### IDN-2 — Users vs. Enrollments (the rejoin answer)
A `User` is the human, forever. An `Enrollment` is one academic stint: roll number, program, academic identity. This split exists for exactly one real case: **a BTech graduate who was placed through the cell rejoins 1–2 years later as an MTech/PhD with the same email.** He must be a fresh placement candidate while his history survives.

- Every user has ≥1 enrollment; **the most recently created one is *current***; all new actions (profile edits, joins, applications) bind to it. No conclude/graduate lifecycle exists — natural gating (graduating-year rules, archived cycles, deadlines) makes stale enrollments inert.
- First enrollment auto-created at first sign-in, empty, pending self-declaration (PRO-1).
- **Rejoin flow:** admin runs "Start new enrollment" on the user → it becomes current → on next login the student self-declares its details (new roll, MTech program, fresh CPI) exactly like a new student. Because *placed status, strikes, penalties, memberships, and applications all attach to the enrollment*, the MTech enrollment starts clean — unplaced, zero strikes — and is eligible for MTech placements by construction, while the BTech enrollment keeps its placed history intact and visible (to staff, and to the student as their own history).
- An enrollment with any memberships/applications can never be deleted, only superseded.

### IDN-3 — Roles
Stored roles are `Student` and `Admin`; coordinator capability is a per-cycle assignment, notified on assign/remove. Coordinators get full operational control **inside assigned cycles** — jobs, pipeline, attendance, venue, offers, bulk ops, cycle-scoped interventions, membership approval, exports, cycle analytics — plus company create/edit and external-offer recording (EXT-2). Admin-only powers are tabled in INT-1 (confirmed). Coordinators may be students in the cycles they run; the safeguard is the audit trail, not a block. Authorization is server-side per request: role, then cycle scope; wrong-cycle access is always a 403.

---

## 2. Profile

### PRO-1 — Self-declaration, admin ownership, locking
One profile per enrollment, completed once by the student. **Admin-managed fields** accept the student's initial value, then lock — thereafter editable only by admins (single edit or bulk upsert). **Student-managed fields** stay editable any time. Every change is audited (who, field, old→new).

Field inventory (confirmed):

| Field | After initial declaration | Required to join a cycle |
|---|---|---|
| Full name | Admin (seeded from Google) | yes |
| Institute email | System (immutable; identity migration is not implemented) | yes |
| Roll number | **Admin** | yes |
| Program | **Admin** | yes |
| Primary branch | **Admin** | yes |
| Secondary branch (dual majors) | **Admin** | if dual major |
| Graduating year | **Admin** | yes |
| CPI (0–10, 2 dp) | **Admin** | yes |
| Active backlog count | **Admin** | yes |
| Total (ever) backlog count | **Admin** | yes |
| Gender | Admin (used in rules) | yes |
| Personal email | Student | yes |
| Contact number | Student | yes |
| Nationality | Student (default IN) | yes |
| 10th %, 10th year, 12th %, 12th year | Student | yes |
| Minor 1 / Minor 2 | Student | no |
| GitHub / LinkedIn / portfolio URLs | Student | no |
| Resume library (PRO-3) | Student | ≥1 entry |

Backlogs are two **counts** so `active_backlogs = 0`, `total_backlogs = 0`, and `active_backlogs ≤ 1` are all expressible. Profile changes **never** touch existing applications (ELG-4).

### PRO-2 — Admin bulk upsert
Semesterly CSV/XLSX load of admin-managed fields. **Match key: institute email → resolves to the user → applies to the *current* enrollment's profile.** If a `roll_number` column is present, it must equal the current enrollment's roll or the row errors — this cross-check makes rejoin cases safe: a stale file carrying the old BTech roll can never write onto the new MTech enrollment (confirmed). Rows for addresses with no user yet are **staged** and auto-applied at that user's first sign-in (staged rows listable/deletable). Provided columns update; absent columns untouched. Preview before commit (per row: update / stage / error+reason), post-commit report, per-row audit, idempotent re-runs. Historical enrollments are never bulk-touched — those are deliberate single edits.

### PRO-3 — Resume library (Google Drive links; the portal stores zero files, anywhere)
List of `(label, drive_url)` on the current enrollment; one default. Saving an entry validates **URL shape only** (must be a Google Drive/Docs file link) — there is **no accessibility probe**: whether the link is actually shareable is the student's responsibility, and a restricted link reaching a company unopenable is an accepted outcome. The UI embeds Drive `/preview`, which renders only when the link is public — doubling as the student's own visual check.
**Freeze semantics:** applying copies the chosen URL *string* onto the application; the student may change it until that job's deadline (APP-3); after that the copied string is final regardless of later library edits/deletions.

---

## 3. Cycles & Membership

### CYC-1 — Cycles and kinds
A cycle: name (unique), **kind ∈ {`placement`, `internship`, `open`}** (system enum — behavioral semantics below, so not a free-form taxonomy), optional start/end dates (**informational only** — display labels and analytics year-grouping; the `start ≤ end` check merely keeps that metadata sane, and no behavior gates on these dates — behavior is gated exclusively by the registration window, the active flag, and archival), description, registration window, active flag, coordinators. **No limit of any kind on concurrently active cycles** — the old constraint and its setting are deleted; the office manages overlap by hand.

| Kind | Job outcome | Job machinery | Join approval default |
|---|---|---|---|
| placement | forced `placement` | full pipeline (rounds, attendance, venue, offers) | **on** |
| internship | forced `internship` | full pipeline | **on** |
| open | chosen per job | lightweight (JOB-6) | **off** (auto-active) |

**Archival** (explicit admin action): preview lists every non-terminal application; on confirm they are **force auto-withdrawn** (system events, notified), then the cycle is read-only everywhere (no joins, applications, ops, or config; analytics/exports keep working).

### CYC-2 — Per-cycle policy (the complete knob list)
| Key | Default | Meaning |
|---|---|---|
| `membership_requires_approval` | on for placement/internship, off for open | CYC-3 flow |
| `join_rule` | empty (open to all members-to-be) | Rule tree (ELG-2) evaluated at join |
| `max_accepted_offers` | 1 (placement/internship); **uncapped for open** | Accepted, non-terminated offers an enrollment may hold **in this cycle**, counting attached external offers (EXT-3). **Nullable = uncapped**; open cycles default uncapped so multiple open-cycle internships over time aren't re-blocked by the cap (placements stay limited to one everywhere by the universal gate regardless of caps) |
| `penalty_blocks_applications` | on | Whether this cycle's gates consult active penalties |
| `allow_withdrawal_after_deadline` | off | Student self-withdraw window past the job deadline |
| `allow_edit_after_deadline` | off | Same for edits |
| `strike_on_absence` | on | Finalization awards strikes (RND-3); N/A in open cycles |
| `offer_expiry_behavior` | **auto_decline** | or `auto_accept` (OFR-4); N/A in open cycles |
| `deadline_reminder_offset` | 6h | |
| `round_reminder_offset` | 24h | N/A in open cycles |

Deleted from v1: the two acceptance-cascade toggles (now invariant, OFR-3) and everything file-related.

### CYC-3 — Membership lifecycle
Join requires: registration window open, cycle active, **complete profile (all required fields, ≥1 resume — including for open cycles)**, `join_rule` satisfied on the live profile (failures shown with reasons), consent acknowledgment, cycle-default resume chosen. The registration dates and `join_rule` are independently overrideable through INT-2; the cycle active flag is not. One membership per (enrollment, cycle); simultaneous memberships across any number of cycles, including same-kind, are allowed.

**Statuses:** `pending` → `active` | `rejected`; `active` → `withdrawn` (student, any time) | `removed` (staff, reason).
- If `membership_requires_approval` is off: join lands directly in `active`.
- If on: join lands in `pending`. **A pending member sees only a status screen** ("your registration awaits approval") — no jobs, no applying. Approvers = the cycle's coordinators + admins; approve → `active`, reject (reason mandatory) → `rejected`; both notified. **Bulk approval** follows the standard bulk contract (RND-2): selection, filters, or pasted roll list; preview; per-row results.
- `rejected` members see the reason and may **re-request**, which re-runs the machine checks and returns them to `pending`.
- `withdrawn`/`removed` trigger auto-withdrawal of that cycle's in-flight applications (CYC-4). Staff may restore a membership to `active` (applications are reinstated separately, per application).
- One staff-side creation path exists: attaching an accepted external offer auto-creates an `active` membership if none exists (EXT-3).

### CYC-4 — Exiting semantics (unchanged split, restated)
- **Student application-withdrawal** (`withdrawn`): per-job, only while `in_progress`, only inside the window (before that job's deadline unless `allow_withdrawal_after_deadline`). After the window, mid-process exits are staff matters.
- **System auto-withdrawal** (`auto_withdrawn`): not deadline-gated; triggers = acceptance cascade (OFR-3), membership `withdrawn`/`removed`, cycle archival. Position (current round, round states) is preserved underneath, so reinstatement to the exact round — or a direct offer — is always possible (INT-1). Each event records its trigger.

---

## 4. Companies
Global directory: name (unique, case-insensitive), description, website URL, sector (taxonomy), active flag; contacts (name, email unique per company, phone, designation, single primary enforced atomically). **No logos, no files.** Coordinators and admins create/edit; **deactivation and merge are admin-only** (merge: pick survivor, repoint jobs + contacts + external offers, deactivate duplicate, audit both). Inactive companies hidden from pickers, retained everywhere else.

---

## 5. Jobs

### JOB-1 — Outcome
Every job carries **`outcome ∈ {internship, placement}`, fixed at creation, immutable forever** (changing it mid-flight would corrupt gates and cascades). In placement/internship cycles it is auto-set to the cycle kind and not shown as a choice. In open cycles it is a mandatory creation-time choice; a company offering both through one drive gets two jobs.

### JOB-2 — Builder (full-pipeline jobs, i.e. in placement/internship cycles)
1. Basics/compensation: company, title, description, location, sector, CTC (LPA + breakdown text) and/or monthly stipend, per-program CTC rows, application deadline, optional offer-acceptance deadline (> application deadline).
2. Eligibility rule (ELG-2) with live impact preview ("N of M active members currently eligible", listable).
3. Rounds: ordered, typed from the round-type taxonomy, each with name, description, default venue/schedule/duration, instructions.
4. Questions: ordered; types = text, long text, single-select(+options), multi-select(+options), boolean, number, date, email, URL. **No file type.** Required flags.
5. Publish toggle (timestamped). Only published jobs are student-visible.

### JOB-3 — Editing after publish
**Existing applications are never affected by job edits.** Copy/comp/deadline edits are free (deadline moves notify applicants; shortening to the past is allowed, warned, and closes applying immediately). Moving the **offer-acceptance deadline** additionally updates the deadline on all of this job's open (unresponded, unterminated) offers and reschedules their expiry enforcement. Eligibility edits apply to future applications only — no re-evaluation, no deregistration machinery exists. Rounds: a round any application has entered cannot be deleted (rename/reschedule fine); inserting/appending rounds is allowed — applications keep their current-round pointer and "next" is whatever now follows by order; process changes notify in-flight applicants. Questions: adding ⇒ blank on old applications; removing/re-typing one with existing answers is blocked (rename/reorder allowed).

### JOB-4 — Student-facing listing
Students see **all published jobs in cycles where their membership is `active`** — eligible or not; ineligible ones are marked with the exact failing reasons plus their applied/status badge. Detail page: description, comp (per-program row if defined, else job CTC), deadline countdown, rounds overview (full-pipeline jobs), eligibility verdict with reasons, apply/edit/withdraw controls per state.

### JOB-5 — Cancellation
Staff "Cancel job": preview of every non-terminal application → all `rejected` (reason "job cancelled", batch audit, notifications), and every open (unresponded, unterminated) offer on those applications is **terminated** (`company_revoked`, reason job-cancelled) so no dangling offer remains for expiry automation to trip over; job unpublished + flagged cancelled. `accepted` applications are **not** touched by cancellation — the preview lists them separately with a pointer to `terminate_offer`. Per-application reinstatement remains available.

### JOB-6 — Open-cycle jobs (lightweight)
Everything in JOB-2 **except rounds** — no rounds, no attendance, no venue/timing, no round reminders. **Custom questions are present exactly as in JOB-2.** The **application deadline is optional**: when set, it gates applying/editing/withdrawal as usual and drives the deadline reminder; when absent, applications stay open for as long as the job is published (unpublish to close), students may edit/withdraw while still `in_progress`, and no reminder fires. There is **no offer-acceptance deadline field and no expiry automation**. Flow: publish → eligible students apply (same gates, snapshot, questions, resume link) → the placement team records final statuses directly. Permitted statuses: `in_progress` → `offered` → `accepted`/`declined`; `in_progress` → `rejected`; `withdrawn`/`auto_withdrawn` as usual; `pending_offer` unused. **Because the company's process runs off-portal, `accepted`/`declined` are staff-recorded** (confirmed): bulk-capable; "straight-to-accepted" (or straight-to-declined) is internally **composed** as extend-offer → accept/decline within one transaction — an Offer row plus two events — so the APP-4 status machine is never bypassed; student notified. The acceptance cascade (OFR-3) fires identically on staff-recorded acceptance — with the standard preview.

---

## 6. Eligibility

### ELG-1 — When it runs
Only ever against the **live profile at that instant**, never retroactively: (1) apply time — binding; (2) job list/detail — informational verdict + reasons; (3) deadline-reminder selection; (4) cycle join (`join_rule` only). Existing applications are never re-judged (your rule: whoever got in validly, stays in).

### ELG-2 — Rule grammar
Boolean tree — `all[…]` / `any[…]` / `not{…}` — over leaves:
- **Profile leaves** `{field, op, value}`: field ∈ registry (program, primary_branch, secondary_branch, graduating_year, cpi, active_backlogs, total_backlogs, tenth_percent, twelfth_percent, gender, minors, nationality, …); op ∈ `eq, ne, in, not_in, gte, lte, between`. Per-branch CPI floors = `any[ all[branch=X, cpi≥a], all[branch=Y, cpi≥b] ]`.
- **Context leaves**: `not_placement_placed` (global, DER-1) — rarely needed in rules since ELG-3 already gates placement universally, but available for special cases.
- **CPI contract:** student CPI rounds **half-up to one decimal** before any comparison (7.95 passes ≥8.0; 7.94 fails) — identically in evaluation, previews, and displayed reasons.
- Builder offers the common patterns compiling into the tree; the tree is canonical and directly editable; every rule stores an auto-generated plain-language summary. Evaluation returns `(verdict, failed leaves with human reasons)`.

### ELG-3 — Standing gates (before any job rule, in order; each consults overrides first — INT-2)
1. Membership `active` in the job's cycle;
2. Job published and not cancelled;
3. Application deadline, where one exists, not passed (open-cycle jobs may omit it — JOB-6);
4. No existing active application for (enrollment, job) — active = any status except `withdrawn`/`auto_withdrawn`;
5. No active penalty on the enrollment (only if the cycle's `penalty_blocks_applications`);
6. **Outcome gate — scope depends on the outcome:**
   - **Placement — hard and universal:** the enrollment holds no accepted, non-terminated placement-outcome offer *anywhere* (any cycle's job, or any external offer — attached or not). An accepted PPO blocks every placement job everywhere from the moment it is recorded.
   - **Internship — same-cycle, dedicated cycles only:** applies only when the job lives in an **internship-kind cycle**: the enrollment holds no accepted, non-terminated internship-outcome offer *within that same cycle* (its job offers + external offers attached to it). Internship offers in **other** cycles never gate — a second-year summer intern is free for the third-year cycle; summer, winter, and 6-month stints in different cycles coexist. **Open-cycle internship jobs carry no outcome gate at all, in either direction:** open cycles are rolling boards, so a student may take multiple internship opportunities from one over time, and holding an internship elsewhere never blocks open-cycle internship jobs. Cross-channel same-season conflicts (open vs dedicated) are a staff matter.
   The only per-student bypass in either case is an override;
7. Cycle offer cap: when the cycle's `max_accepted_offers` is set, accepted non-terminated offers counted in this cycle (job offers + attached external offers) must be below it; a **null cap means uncapped** (the open-cycle default).

### DER-1 — Placed dimensions & their scopes
Two derived facts, never hand-set, recomputed whenever any contributing offer changes:
- **placement-placed** (per enrollment, **global**): ∃ accepted, non-terminated placement-outcome offer from *any* source — any cycle's job or any external offer, attached or not. This is both the analytics flag and the gate input. PPOs are placement-outcome, so *accepting a PPO ⇒ placement-placed everywhere*; a declined or merely-offered PPO leaves the student fully eligible.
- **internship-placed** (per enrollment, **analytics flag only**): ∃ accepted, non-terminated internship-outcome offer anywhere — reported in dashboards. **Internship gating is narrower** (ELG-3.6): only accepted internship offers *within a given dedicated internship cycle* (its jobs + externals attached to it) block that same cycle's internship jobs; open cycles are never gated for internships.
The dimensions are independent: an intern with an accepted PPO is internship-placed *and* placement-placed; internship acceptances never gate placement jobs, and vice versa.

---

## 7. Applications

### APP-1 — Applying (student-only)
Atomic: run ELG-3 + job rule → snapshot profile (registry fields + chosen resume URL string) → create `in_progress` (full-pipeline jobs: positioned at round 1 with a `pending` round-state; open-cycle jobs: no round position) → `created` event → confirmation email. Duplicate races settled by the partial-unique index (one active application per enrollment+job). Form = job questions (typed validation; URL answers shape-checked) + resume choice (cycle default preselected; any library entry or a one-off pasted Drive URL passing PRO-3 checks).

### APP-2 — Re-application
Allowed **only** when every prior application for the pair is `withdrawn`/`auto_withdrawn`, through the normal gates. Any `rejected`/`declined`/`offer_terminated`/`accepted` history blocks re-applying — staff reinstatement of the existing application (INT-1) is the only path back.

### APP-3 — Editing & self-withdrawal
Edit (answers + resume choice): while `in_progress`, until the deadline unless `allow_edit_after_deadline`; wholesale answer replacement, re-validated, `edited` event, no notification. Self-withdraw: while `in_progress`, same window logic; frees the unique slot. INT-2 treats these as independent gates: an `edit_window` override never authorizes withdrawal, and a `withdraw_window` override never authorizes editing.

### APP-4 — Status machine (complete; nothing outside this table can happen)
Statuses: `in_progress`, `pending_offer`, `offered`, `accepted`, `declined`, `rejected`, `withdrawn`, `auto_withdrawn`, `offer_terminated`.

| # | From → To | Actor / trigger | Notes |
|---|---|---|---|
| 1 | ∅ → in_progress | Student applies | APP-1 |
| 2 | in_progress → in_progress | Staff round ops | Round-state changes only; full-pipeline jobs |
| 3 | in_progress → pending_offer | Staff advance past final round | Full-pipeline only |
| 4 | in_progress → rejected | Staff: eliminate / bulk reject / finalize-absent / job cancel / open-cycle final status | Reasoned event; email; + strike if absence-finalize & policy |
| 5 | pending_offer → rejected | Staff | As 4 |
| 6 | in_progress → offered | Staff direct/bulk offer | Offer row; email; expiry scheduled if deadline exists (dedicated cycles) |
| 7 | pending_offer → offered | Staff rollout | As 6 |
| 8 | offered → accepted | **Student** (dedicated cycles); **staff-recorded** (open cycles) | OFR-3 cascade |
| 9 | offered → declined | Student; staff-recorded (open); or **system on expiry** (`auto_decline`) | Event; email |
| 10 | offered → offer_terminated | Staff (company rescinds pre-acceptance) | OFR-5 |
| 11 | accepted → offer_terminated | Staff intervention (revoke / renege) | OFR-5 with choices |
| 12 | in_progress → withdrawn | Student, in window | APP-3 |
| 13 | in_progress, pending_offer → auto_withdrawn | System: acceptance cascade, membership exit, archival | CYC-4; position preserved |
| 14 | rejected, withdrawn, auto_withdrawn → in_progress (chosen round) | Staff **reinstate** | INT-1 |
| 15 | any non-accepted → offered | Staff **direct offer** | New Offer row |
| 16 | declined → offered | Staff re-extend | New Offer row |
| 17 | anything else | Staff **force transition**, reason mandatory | Previewed catch-all |

If `offer_expiry_behavior = auto_accept` is configured for a cycle, row 8 gains a system actor for that cycle only, cap-checked, falling back to decline + staff flag if the cap is already consumed.

---

## 8. Rounds & Operations (full-pipeline jobs only)

### RND-1 — Per-round state
One row per (application, round reached): **result** `pending`/`advanced`/`eliminated`/`waitlisted`; **attendance** `pending`/`present`/`absent`/`excused`; optional per-student venue/time overriding round defaults; notified-at stamps. Advancing creates the next round's `pending` row; from the final round ⇒ transition 3. Eliminating ⇒ transition 4. **Waitlist resolves only by manual promotion** (→ advanced, or eliminate). Results and notifications are **immediate** — no staging step.

### RND-2 — The universal bulk contract
Advance / eliminate / offer / reject / mark-present / assign venue+timing / approve memberships — every bulk operation accepts a checkbox selection, **a pasted list of roll numbers or emails**, or (venue/timing) CSV/XLSX. Always: **preview first** (resolved targets, unmatched identifiers listed never guessed, per-row planned effect including "will earn a strike"), idempotency-keyed (double-submit cannot double-apply), per-row results after commit, one batch audit entry + one event per affected row.

### RND-3 — Attendance & finalization
Staff mark attendance (bulk paste flips `pending→present`; individual toggle cycles states). **Finalize round** (explicit, previewed): `absent` ⇒ eliminated + rejected + one strike if `strike_on_absence`; `pending` at finalize ⇒ treated as absent; `excused` ⇒ eliminated + rejected, no strike; `present` ⇒ untouched, awaiting result decisions. Post-finalize remedies sit side by side: edit the attendance sheet then reinstate (INT-1), or leave it and revoke the strike (DIS-3).

### RND-4 — Venue & timing
Staff-assigned only (manual, bulk, or upload with per-row validation). Publishing/updating fires the venue-timing notification (flagged as update on repeat). Round reminders go once to students with a scheduled slot ~`round_reminder_offset` ahead.

---

## 9. Offers

### OFR-1 — The record
Extending creates an `Offer`: application, extended-at, acceptance deadline (from the job; absent ⇒ no expiry automation), response + timestamp, termination fields (at/by/kind ∈ `company_revoked`/`student_renege`/`admin_correction` + free text). Latest row is current; re-extensions accumulate as history.

### OFR-2 — Extension
Rollout (`pending_offer→offered`) or direct/bulk (`in_progress→offered`). Email includes the deadline; expiry scheduled when one exists.

### OFR-3 — Acceptance cascade (exact order, one transaction; identical whether the student clicks or staff record it)
1. Guards: status `offered`, ownership/authority, current offer unterminated and (dedicated cycles) not past deadline unless overridden.
2. Lock the enrollment's offers in the job's cycle; when the cycle has a cap, re-check `max_accepted_offers` **including attached external offers** — cap reached ⇒ reject with message (the concurrent-double-accept guard). Uncapped cycles skip this check; the outcome gates are re-checked here in either case.
3. Set `accepted`; event.
4. **Always-on cascade, scoped like the gate.** For a **placement**-outcome acceptance — across **all cycles, open included**: every other `offered` application of this enrollment on a placement-outcome job → `declined` (system event "accepted elsewhere", email each); every `in_progress`/`pending_offer` application on a placement-outcome job → `auto_withdrawn` (positions preserved, events, emails). For an **internship**-outcome acceptance — the same, but **only when the accepted job lives in a dedicated internship cycle, and only within that cycle**; internship applications in other cycles keep running, and **an open-cycle internship acceptance cascades nothing** (even its sibling open-cycle applications keep running). Different-outcome applications are never touched in either case.
5. Re-derive the enrollment's placed dimensions (DER-1); confirmation email.
Decline: guards 1; `declined`; event; email. No cascade.

### OFR-4 — Expiry
When a deadline passes unanswered, the cycle's `offer_expiry_behavior` runs as system actor: **default `auto_decline`** (offer lapses, transition 9, student notified "expired — declined") or `auto_accept` (full OFR-3, cap-checked with decline-fallback + staff flag). The task **re-validates at fire time**: the offer must still be `offered`, unterminated, with its deadline unchanged — responded/terminated meanwhile ⇒ no-op; deadline moved ⇒ reschedule. Events marked system-initiated. Open cycles: no expiry automation exists.

### OFR-5 — Termination (revoke / renege)
Staff terminate an `offered`/`accepted` offer with kind + reason. Preview shows the full cascade; staff choose the bracketed options: application → `offer_terminated`; termination fields set; placed dimensions re-derived; cycle cap slot released; **[choice]** restore each application auto-declined/auto-withdrawn by this acceptance (per-application checkboxes; auto-withdrawn apps return to their prior status & round; auto-**declined** apps return to `offered` via a **fresh Offer row** with a staff-set optional new deadline — the original offer stays declined in history); **[choice]** award a strike or direct penalty (the renege review); **[choice]** notify (default on). Everything remains editable afterward — penalty revocable, applications reinstatable, the offer re-extendable as a new row.

---

## 10. External Offers (PPOs & off-campus)

### EXT-1 — The record
Standalone, **cycle-independent at creation** — precisely because the corresponding placement cycle may not exist when a PPO lands. Fields: enrollment, company (directory), **outcome** (`internship`/`placement` — a PPO is placement-outcome by nature), **source** (`ppo`/`off_campus`/`other`), **its own compensation** (CTC for placement outcome / stipend for internship — a PPO's full-time CTC is never the internship stipend), status `offered`/`accepted`/`declined`, offer & response dates, optional link to the source internship application, notes. Full CRUD with audit.

### EXT-2 — Creation & visibility
Entry points: a staff CRUD surface, plus a **"Record PPO" button on any internship application** (pre-fills enrollment, company, source=ppo, outcome=placement, links the source application). Creators/editors: **admins and coordinators**. Status is **purely staff-recorded** — the student accepts a PPO over email with the office, and staff update the record (your C3); students see their external offers read-only on their dashboard (confirmed).

### EXT-3 — Cycle attachment (the "cycle doesn't exist yet" resolution)
An external offer may later be **attached to exactly one dedicated cycle whose kind matches its outcome** (PPO → a placement cycle; off-campus internship → an internship cycle; open cycles are not attachment targets). Attachment is manual — per-offer or bulk ("attach selected to Placements 2027–28") — detachable and re-attachable (CRUD), by admins or coordinators of the target cycle. Effects of attachment:
- An **accepted** attached offer **consumes the target cycle's `max_accepted_offers` cap** (ELG-3.7) and appears in that cycle's dashboards, funnels, and placed counts.
- If the enrollment has no membership in the target cycle, attachment **auto-creates an `active` membership** (bypassing approval and join rule — staff-initiated, event-stamped) so the cycle's placed/registered analytics stay coherent (confirmed).
**How attachment works when the cycle doesn't exist yet — it simply waits.** Recording and attaching are decoupled in time: (1) the PPO lands in June → staff record the external offer immediately, cycle-less; if accepted, the universal placement gate bites from that moment. (2) The offer sits in the **unattached pool** — the external-offers list filtered to *attached: none* — visible so nothing is forgotten. (3) Months later the admin creates "Placements 2027–28"; that cycle's page shows a panel of **unattached external offers of matching outcome** (filterable by graduating year) with per-offer or bulk attach. (4) Attachment then applies its effects — cap counting, analytics inclusion, auto-registration. Nothing ever anticipates a future cycle; the pool waits for it.

Gating vs attachment, per outcome: for **placement**-outcome externals (PPOs), gating never waits for attachment — an accepted PPO blocks placement applications everywhere from the moment it is recorded, cycle or no cycle; attachment is a cap-and-analytics concern only. For **internship**-outcome externals, the gate is same-cycle and dedicated-only, so an accepted external internship gates a cycle's internship jobs **only once attached to that (dedicated) cycle** — unattached, it is analytics-only; consistency across cycles or channels is a staff action.

### EXT-4 — Edits & consistency
Any edit that changes status or outcome re-derives DER-1 and re-evaluates cap effects. Recording status → `accepted` fires the **same OFR-3 cascade** (previewed to staff — "this will auto-withdraw these 3 placement applications"). Editing status *away from* `accepted` behaves like OFR-5: preview, placed re-derivation, cap release, per-application **[choice]** restoration of anything the acceptance cascaded, notification choice. Deleting an accepted external offer requires the same preview and choices; nothing re-derives silently.

---

## 11. Discipline (enrollment-scoped, unchanged)
Strikes/penalties attach to the **enrollment** (persist across its cycles; clean slate on rejoin; full history staff-visible). **Strikes:** auto on absence-finalize (per-cycle `strike_on_absence`) or manual admin award with reason; each carries reason, source, awarded-by, active flag, consumed-by link; student notified with running total. **Conversion:** active unconsumed strikes reaching the **global `strikes_per_penalty`** (default 2; blank disables) convert atomically into one penalty (`from_strikes`, reasons concatenated, strikes consumed). **Penalties:** block applying wherever the cycle's `penalty_blocks_applications` is on; direct award possible; no expiry timers. **Revocation:** strike revoke re-computes conversion against the current global threshold (unsupported auto-penalty dissolves, strikes un-consume); penalty revoke deactivates it (consumed strikes stay consumed unless also revoked). All audited, notified, reversible.

---

## 12. Interventions & Overrides

### INT-1 — Catalog (every one: authorization → dry-run preview of the full cascade → mandatory reason → transactional execution → events + audit; no raw-edit path exists)
| Intervention | Who | Summary |
|---|---|---|
| Reinstate application to round N | Staff (cycle) | APP-4 row 14; later round-states cleared/kept per preview; notify choice |
| Direct offer / re-extend | Staff (cycle) | Rows 15–16 |
| Terminate offer | Staff (cycle) | OFR-5 |
| Record / edit / attach / detach external offer | Staff (admin; coordinators per EXT-2/3) | EXT-2..4 |
| Cancel job | Staff (cycle) | JOB-5 |
| Approve / reject / restore membership | Staff (cycle) | CYC-3 |
| Force status transition | Staff (cycle) | Row 17 |
| Late-application override | Staff (cycle) | Creates INT-2 override; student applies normally |
| Award / revoke strike & penalty | **Admin** | DIS |
| Correct locked profile fields / bulk upsert | **Admin** | PRO-1/2 |
| Start new enrollment | **Admin** | IDN-2 |
| Company deactivate / merge | **Admin** | §4 |

The "Who" column above is confirmed.

### INT-2 — Overrides
Standing scoped exceptions are consulted **before** enforcement. The domains are `eligibility`, `application_deadline`, `edit_window`, `withdraw_window`, `outcome_gate`, `offer_cap`, `offer_deadline`, `cycle_registration_window`, and `cycle_join_rule`. The six legal target combinations, in precedence order, are `cycle < job < enrollment < (cycle, enrollment) < (job, enrollment) < application`; a job or application determines its cycle, so redundant combinations such as `(cycle, job)` are illegal. At equal precedence, deny wins over allow, then the newest row and UUID break ties deterministically.

Domain/scope legality follows the gate that can actually run. Eligibility and application-deadline grants are pre-application only and therefore cannot target an application; cycle-registration and cycle-join-rule grants target only cycle, enrollment, or `(cycle, enrollment)`; the other five domains may use all six combinations. Enrollment-wide grants remain administrator-only. There is deliberately **no** duplicate-application domain: one-active-application is a database constraint that cannot be overridden. Cycle active state, membership state, job-open state, duplicate applications, and disciplinary penalties remain non-overridable and use their sanctioned lifecycle remedies.

Every row records allow/deny, reason, grantor, optional expiry, and active flag. Expired or inactive rows are inert. Every influenced decision stamps the chosen override into its append-only event or audit evidence. The register is filterable with one-click deactivation, while job, student, and application pages show relevant active, expired, and shadowed rows.

---

## 13. Notifications
**Channel:** AWS SES (console in dev). Every event type maps to a DB-stored template (subject + body + named variables), admin-editable in-portal, per-event toggle, optional per-cycle override; a missing variable renders blank + logs a warning, never blocks the send. **Delivery:** transactional outbox — intent commits with the domain change; worker delivers with retries; SES outage delays, never loses or blocks. **Event catalog:** application submitted · advanced (+next-round details) · eliminated/rejected (+reason) · marked absent (+strike if any) · offer extended (+deadline) · accepted · auto-declined (accepted elsewhere) · auto-withdrawn (+trigger) · offer terminated (kind-specific) · offer expired · external offer recorded/updated · strike added/revoked (+total) · penalty added/revoked · venue/timing published/updated · process changed · job cancelled · **membership pending / approved / rejected (+reason) / removed / restored** · coordinator assigned/removed · deadline reminder · round reminder. Every send logged (recipient, event, status, attempts). **Reminders:** deadline nudges per cycle offset to active members currently eligible (live check) who haven't applied, once per (student, job); round reminders once per (student, round). **Nice-to-have after core:** in-portal feed of the same events with read/unread.

---

## 14. Analytics & Reports

### ANA-1 — Definitions (the single vocabulary)
Per (cycle, filters): *Registered* = `active` memberships. *Applied* = distinct enrollments with ≥1 application ever created. *Offered* = distinct enrollments with ≥1 Offer extended **or attached external offer in status ≥ offered**. *Placed* = distinct enrollments with ≥1 accepted, non-terminated offer **in this cycle's jobs or attached to this cycle** — with an on-portal vs external (PPO/off-campus) split available on every placed figure. *Placement rate* = placed ÷ registered. Compensation stats (mean/median/min/max) over placed students' accepted offers: per-program CTC row when defined, else job CTC, **external offers use their own recorded compensation**; stipend variants for internship outcomes. Portal-wide, the DER-1 dimensions give batch-level internship-placed / placement-placed regardless of attachment.

### ANA-2 — Dashboards (all behind login)
**Portal:** multi-cycle yearly trends — rates, comp trajectories, participation, sector/program mix, PPO share, off-campus share. **Cycle:** funnel (registered→applied→offered→placed), comp stats, breakdowns by program/branch/gender/sector, top companies, timeline, discipline counts, pending-approval queue size. **Job:** applicants; full-pipeline jobs add per-round entered/advanced/eliminated/absent/waitlisted + conversion + time-in-round; open-cycle jobs show applied→offered→accepted. **Company:** across cycles — jobs, applicants, offers, acceptance rate, comp history, hires by program/branch, external offers, cancellations. **Student (staff):** enrollment picker across the user's history; memberships, applications with full event timelines, offers + external offers, discipline, snapshot-vs-live diffs. **Student (self):** own applications & statuses, upcoming rounds with venue/time, offers awaiting action, external offers (read-only), strikes/penalties, cross-enrollment history.

### ANA-3 — Compliance & outcome tags
Memberships carry an optional staff-set **outcome tag**: `higher_studies` / `entrepreneurship` / `not_seeking` — used to build honest denominators. Canned per-batch/per-program reports ship with a **provisional standard column set** (batch registered, placed on-campus, placed via PPO/off-campus, median & mean CTC of placed, higher-studies count) — refined against the office's exact NIRF/RTI formats when those documents surface (not available today).

### ANA-4 — Spreadsheet exports
Per job (and per reached-round on full-pipeline jobs): column picker over the profile registry + application fields (status, current round, applied-at, **resume link**) + that job's questions; per-job saved presets; XLSX or CSV, honestly labeled; membership exports for cycles (including approval status and outcome tags); every export audited (who/what/columns/filters). No ZIPs — the links column is the resume delivery.

---

## 15. Taxonomies & Global Configuration
**Taxonomies (admin-editable, referenced by ID):** programs · branches (single canonical list) · program↔branch validity map · minors · sectors · round types. Deleting only when unreferenced (else deactivate); renames propagate. Cycle kinds and job outcomes are **system enums** (they carry hard semantics), not taxonomies. **Global settings:** `strikes_per_penalty` · session lifetime · SES sender/config · default templates. Every config/taxonomy change is versioned in the audit log.

---

## 16. Cross-Cutting Correctness

**The state-change consistency doctrine** — the general answer to "if staff change a state, what keeps everything downstream from still referring to the old state?" A state machine alone guarantees only *reachability* (illegal jumps can't happen); consequence-correctness comes from four rules that hold site-wide:
1. **Bare state writes do not exist.** Every status change — including the force-transition intervention — is a command whose transition-table row declares its effects; state and effects commit in **one transaction**, and the preview shows both. There is no path anywhere that flips a column and walks away from its consequences.
2. **Derive, don't duplicate.** Anything computable from source records *is* computed from them: placed flags are functions over offers, the cap is a count over offers, funnels and "eligible students" figures are evaluations over current rows. A derived value cannot be "left at the previous state" because it is not independently stored; the few stored copies (application status, current round) are re-derived in the same transaction as any mutation of their inputs.
3. **Deferred work re-validates; done work gets compensations.** Anything that runs later (expiry tasks, reminders, queued notifications) re-checks its preconditions at fire time and no-ops if the world has moved. Anything already materialized and not derivable (a sent email, an awarded strike, an executed cascade) is reversed only through explicit compensating choices surfaced in the intervention preview — restore these applications, waive that strike, notify or not.
4. **The checker is the backstop:** the periodic consistency pass re-derives everything derivable, asserts the invariants below, and turns any drift into an admin-visible finding with a suggested compensating command.
Worked example — staff terminate an accepted offer: in one previewed transaction the status changes; placed flags re-derive to false and the cap frees itself (both are derivations over offers); the three applications the acceptance had auto-withdrawn appear as per-row restoration checkboxes; and the offer's scheduled expiry task, if any, finds it terminated at fire time and no-ops.

- **Events everywhere:** append-only `application_events` for every APP-4 row and EXT-4 mutation; `audit_log` for staff/config/export/discipline/profile/membership actions. History is never rewritten.
- **Previews never lie:** every previewable command computes its plan with the same code path that executes it.
- **Concurrency:** partial-unique index = one active application per (enrollment, job); unique (enrollment, cycle) membership; acceptance locks the enrollment's offers in-cycle before the cap re-check; the outcome gate is re-checked inside the acceptance transaction (two placement-outcome accepts racing across different cycles: the second re-derives after the first commits and fails; internship accepts in different cycles are legitimately independent); idempotency keys on all bulk ops. Stale-view staff actions (two coordinators, different screens) are serialized by row locks — the later transaction re-reads post-commit state and fails or skips per row with a reason; single-row actions additionally carry an optimistic precondition (the UI sends the status it believed; mismatch ⇒ "state changed, refresh").
- **Consistency checker (periodic):** stored status ≡ latest event + offer rows; DER-1 flags ≡ derivation incl. external offers; per-cycle accepted count (jobs + attached external) ≤ cap where one is set; no `in_progress` application on a non-active membership; every `from_strikes` penalty supported by ≥ threshold consumed strikes; no expired override credited post-expiry; round-state rows exist for every reached round; external-offer attachments only on matching-kind cycles. Violations → admin-dashboard findings with a suggested compensating intervention.
- **Fail closed / fail open:** validation & authorization fail closed (unverifiable Drive link ⇒ rejected save); side effects fail open (SES down ⇒ queued, operation commits).

---

## 17. Explicitly Absent (verify nothing here is missed)
File storage of any kind · file-type questions · resume size/page validation · resume link accessibility probing · ZIP exports · per-cycle re-registration · eligibility re-evaluation / auto-deregistration on profile or rule changes · any limit on concurrently active cycles · per-cycle cascade toggles (cascade is invariant) · `ppo`/`off_campus` job kinds (external offers replaced them) · informational jobs · cycle-scoped strike thresholds · discipline expiry timers · dream-offer/upgrade policies · offer letters · result staging/announce · student self-booking of slots · student-recorded outcomes in open cycles · student accept/decline on external offers · recruiter accounts · legacy migration · password auth.

---

## 18. Status of confirmations
All resolved: **B** — external offers student-visible, read-only · **C** — profile field table as written · **D** — who-does-what as tabled · **F** — attachment auto-registers the student in the target cycle, and attachment is deferred until the cycle exists (EXT-3) · **G** — internship gating is same-cycle, dedicated internship cycles only; open cycles exempt in both directions; season groups rejected.

**One residual check (a ripple of G):** exempting open cycles from the internship gate only works if the offer cap doesn't re-block it, so `max_accepted_offers` is now **nullable (= uncapped)** and defaults to **uncapped for open cycles** (1 for placement/internship cycles, as before). Placement remains limited to one everywhere by the universal gate, whatever the caps. Say "cap ok" — or give open cycles a different default.
