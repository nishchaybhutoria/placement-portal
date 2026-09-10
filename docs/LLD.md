# Placement Portal — Low-Level Design

**Normativity:** [`BEHAVIOR.md`](BEHAVIOR.md) defines what the product does; this document defines how it is implemented. Where this document names a table, column, enum value, command, route, or convention, use that exact name. Anything not specified here follows the conventions in §4 rather than being invented ad hoc. Conflicts between this document, the behavior contract, and source code are defects to report and resolve explicitly.

---

## 1. Architecture & Guarantees (frozen from HLD discussion)

```
Internet ─443─▶ Caddy ─▶ FastAPI (uvicorn)          Worker (Procrastinate)
                 │            │                            │
                 │            └────────────┬───────────────┘
              [static SPA]          PostgreSQL 16
                                (data + sessions + queue + outbox
                                 + events + audit)  ← the ONLY state
External: Google OAuth (login only) · AWS SES (email only)
Backups: WAL → local archive volume → rclone → Google Drive (5-min sync)
         weekly pg_basebackup + nightly pg_dump → Drive
```

Every component is stateless except PostgreSQL. **Guarantees (G1–G7)** the code must uphold:

- **G1 Atomicity:** a business operation and all its consequences — state changes, events, audit rows, queued side-effect jobs — commit or vanish together. Enforced by §5.
- **G2 No lost side effects:** committed ⇒ the deferred jobs durably exist (Procrastinate rows in the same transaction) and eventually run. Handlers are idempotent (at-least-once execution).
- **G3 No phantom side effects:** rolled back ⇒ no job rows exist, nothing fires.
- **G4 Invariants under any interleaving:** row locks + partial-unique indexes + in-transaction gate re-checks. Stale staff screens fail loudly (optimistic `expected_status` on single-row commands).
- **G5 Durability:** WAL; disk loss recovers via PITR (base backup + WAL from Drive), RPO ≈ 10 min.
- **G6 Reconstructable history:** `application_events` + `audit_log` are append-only at the DB-grant level.
- **G7 Degradation order:** side effects delay first, availability next, correctness never. Late, never wrong.

Non-guarantees (accepted): no HA (single node), at-least-once email (never state), brief deploy blips, external outages degrade per HLD table.

---

## 2. Stack Pin

| Layer | Choice | Version pin |
|---|---|---|
| Language | Python | 3.14 |
| API | FastAPI + Pydantic v2 | latest stable |
| ORM/migrations | SQLAlchemy 2.x + Alembic | latest stable |
| DB | PostgreSQL | 16 |
| Queue/outbox/cron | Procrastinate | latest stable (PG-backed) |
| Auth | Authlib (Google OAuth) + server-side sessions | — |
| Frontend | React 18 + TypeScript + Vite + Tailwind + shadcn/ui + TanStack Query + React Router | — |
| API client | Generated from OpenAPI (`openapi-typescript` + a thin fetch wrapper) | regenerated in CI |
| Edge | Caddy (TLS, static, proxy) | 2.x |
| Tests | pytest + httpx + factory fns; Vitest; Playwright (3 E2E flows) | — |
| Packaging | uv (backend), pnpm (frontend) | — |
| Containers | Docker Compose | — |

---

## 3. Repository Layout (monorepo)

```
placement-portal/
├── CONTRIBUTING.md             # development rules and architecture invariants
├── docker-compose.yml          # caddy, api, worker, db, backup
├── Caddyfile
├── backend/
│   ├── pyproject.toml
│   ├── alembic/                # migrations (one per milestone)
│   ├── app/
│   │   ├── main.py             # FastAPI app assembly: routers from registries
│   │   ├── core/               # THE MACHINERY (M1) — never domain-specific
│   │   │   ├── db.py           # engine, sessionmaker (no autocommit), Base
│   │   │   ├── executor.py     # run_command / dry_run — ONLY commit point
│   │   │   ├── registry.py     # command + screen + effect + reminder registries
│   │   │   ├── plan.py         # Plan / Rejection / StateOp dataclasses
│   │   │   ├── authz.py        # role + cycle-scope dependencies; double-check helper
│   │   │   ├── idempotency.py
│   │   │   ├── errors.py       # RFC7807 problem responses; reason codes
│   │   │   └── audit.py
│   │   ├── domain/
│   │   │   ├── shared.py       # ALL enums (§6), reason codes, event keys
│   │   │   ├── transitions.py  # the declarative transition table (§7)
│   │   │   ├── rules.py        # rule-tree schema + evaluator (§9) — pure
│   │   │   ├── gates.py        # standing gates (§9.3) — pure over loaded state
│   │   │   └── policy.py       # settings/policy resolver with provenance
│   │   ├── modules/            # vertical slices; each: models.py, commands.py,
│   │   │   ├── identity/       #   screens.py, loaders.py, (logic.py if nontrivial)
│   │   │   ├── profiles/
│   │   │   ├── taxonomies/
│   │   │   ├── cycles/         # cycles, policy, memberships, coordinators
│   │   │   ├── companies/
│   │   │   ├── jobs/
│   │   │   ├── applications/   # + rounds ops
│   │   │   ├── offers/         # + external offers
│   │   │   ├── discipline/
│   │   │   ├── overrides/
│   │   │   ├── interventions/
│   │   │   ├── notifications/  # templates, delivery task, reminders
│   │   │   ├── analytics/      # read-only queries + canned reports + exports
│   │   │   └── admin/          # settings, bulk upsert, findings
│   │   └── worker.py           # procrastinate app + periodic task defs
│   └── tests/                  # mirrors modules/; + tests/core/ guarantee tests
└── frontend/
    ├── src/api/                # generated client + query hooks (one per screen)
    ├── src/screens/            # one folder per screen id (§11.3)
    ├── src/components/
    └── src/lib/
```

**Conventions (binding):** UUIDv4 PKs (`gen_random_uuid()`); `timestamptz` everywhere, UTC; `citext` for emails and company names; snake_case DB, camelCase only in TS; every table has `created_at` (and `updated_at` where mutable); money as `numeric(10,2)` (CTC in LPA, stipend in ₹/month); enums are PG enums named `<thing>_t`; no soft-delete flags except where specified (`is_active` on taxonomy/companies); FKs `ON DELETE RESTRICT` unless stated; all IDs in APIs are UUID strings; module code never imports another module's `models.py` — cross-module access goes through loaders/queries.

---

## 4. Where decisions come from

1. The behavior contract for product semantics.
2. This LLD for implementation contracts.
3. The conventions in §3.
4. If ambiguity remains, fail closed, leave a `# SPEC-GAP:` marker at the implementation site, and raise the policy question rather than inventing behavior.

---

## 5. The Write Path — executor contract (the G1 mechanism)

**Every mutation in the system is a command.** No router, task, or script touches the session directly.

```python
# core/plan.py
@dataclass(frozen=True)
class StateOp:      # applied in-order, in-transaction
    op: Literal["insert","update","delete"]; model: str; values: dict; where: dict|None
@dataclass(frozen=True)
class Event:        # application_events rows (or audit-only for non-pipeline)
    application_id: UUID|None; event_type: EventType; from_status: str|None
    to_status: str|None; from_round: UUID|None; to_round: UUID|None
    reason: str|None; payload: dict
@dataclass(frozen=True)
class Deferred:     # procrastinate jobs, same-tx
    task: str; args: dict; schedule_at: datetime|None = None
@dataclass(frozen=True)
class Plan:
    state_ops: list[StateOp]; events: list[Event]; deferred: list[Deferred]
    audit: dict|None; summary: dict            # summary = preview payload
@dataclass(frozen=True)
class Rejection:
    reasons: list[Reason]                       # machine codes + human text
```

```python
# core/executor.py — THE ONLY FILE THAT COMMITS. CI enforces this (§14).
async def run(cmd_name, input, actor, *, dry_run=False, idempotency_key=None):
    spec = registry.commands[cmd_name]
    authz.check(spec, actor, input)                        # 1. route-level authz
    async with sessionmaker.begin() as tx:                 # 2. one transaction
        if idempotency_key and (prev := await idem.lookup(tx, idempotency_key)):
            return prev                                    # 3. replay-safe
        state = await spec.loader(tx, input, lock=not dry_run)   # 4. SELECT..FOR UPDATE
        authz.check_scope(spec, actor, state)              # 5. domain-level authz (double check)
        ovr = await overrides.applicable(tx, spec.rule_domains, state)
        plan = spec.decide(input, state, policy.resolve(state), ovr, actor)  # 6. PURE
        if isinstance(plan, Rejection): raise DomainRejection(plan)
        if dry_run: return Preview(plan.summary, plan.events)               # 7. no writes
        await apply_state_ops(tx, plan.state_ops)          # 8.
        await append_events(tx, plan.events, actor)        # 9.
        await audit.write(tx, actor, cmd_name, plan.audit) # 10.
        for d in plan.deferred:                            # 11. outbox: same connection
            await procrastinate_app.configure(d.task, schedule_at=d.schedule_at)\
                                   .defer_async(connector=tx.connection(), **d.args)
        if idempotency_key: await idem.record(tx, idempotency_key, plan.summary)
    return Result(plan.summary)                            # 12. commit happened at ctx exit
```

Rules the executor enforces globally: **preview ≡ execution** (same `decide`, dry_run just skips 8–11); **cascades are `state_ops`** (in-tx), never `deferred`; **`deferred` may only carry idempotent, non-state-authoritative work** (notifications, schedules, export builds); optimistic `expected_status` field accepted by all single-row transition commands (mismatch ⇒ Rejection `stale_view`).

**Per-enrollment mutex (G4-critical):** any command that can change an enrollment's accepted-offer state — `accept_offer`, `record_open_outcome`, `update_external_offer`/`delete_external_offer` on status paths, `terminate_offer`, expiry auto-accept — has its loader lock the **`enrollments` row itself** (`SELECT id FROM enrollments WHERE id=… FOR UPDATE`) *before* reading offers or evaluating gates. This single mutex serializes placed-state mutations across cycles and across job-offers vs external-offers; without it, two placement-outcome accepts in different cycles have disjoint lock sets and both pass the gate. In-cycle offer rows are additionally locked for cap counting.

**Transactional defer mechanism:** Procrastinate jobs are enqueued via its in-SQL defer (the documented `defer` SQL function / direct insert into its jobs table) executed **on the current session**, which is what makes the job row share the domain transaction. Do not enqueue through a separate connector pool — that breaks G2/G3. Verify the exact function name against the installed Procrastinate version at M2 and pin it in a comment.

**Bulk commands** wrap the executor: chunk input into ≤500-row chunks; each chunk is one `run()` call (one atomic tx) with idempotency key `f"{batch_key}:{chunk_no}"`; return per-row results (`applied|skipped(reason)|error(reason)`); one batch `audit` row plus per-row events. A crash mid-batch resumes safely by replaying the same batch key.

---

## 6. Domain Enums (PG enum name → values)

```
role_t: student | admin      -- 'coordinator' is NOT a role value: coordinator capability is
                             -- derived from cycle_coordinators rows, because a coordinator may
                             -- simultaneously act as a student (apply, hold offers). Authz:
                             -- student actions require a current enrollment; staff(cycle) :=
                             -- role=admin OR a cycle_coordinators row for that cycle.
gender_t: male | female | other
cycle_kind_t: placement | internship | open
membership_status_t: pending | active | rejected | withdrawn | removed
outcome_t: internship | placement
application_status_t: in_progress | pending_offer | offered | accepted | declined
                      | rejected | withdrawn | auto_withdrawn | offer_terminated
round_result_t: pending | advanced | eliminated | waitlisted
attendance_t: pending | present | absent | excused
offer_response_t: accepted | declined
termination_kind_t: company_revoked | student_renege | admin_correction
external_source_t: ppo | off_campus | other
external_status_t: offered | accepted | declined
question_type_t: text | longtext | single | multi | boolean | number | date | email | url
strike_source_t: auto_absence | manual
rule_domain_t: eligibility | application_deadline | edit_window | withdraw_window
             | outcome_gate | offer_cap | offer_deadline
             | cycle_registration_window | cycle_join_rule
offer_expiry_t: auto_decline | auto_accept
outcome_tag_t: higher_studies | entrepreneurship | not_seeking
event_type_t: created | advanced | eliminated | waitlisted | attendance_marked
            | round_finalized | offer_extended | accepted | declined | auto_declined
            | withdrawn | auto_withdrawn | offer_terminated | reinstated | edited
            | forced_transition | overridden | external_recorded | external_updated
finding_status_t: open | resolved | dismissed
notif_status_t: queued | sent | failed | dead
```

Reason codes (`errors.py`, string constants, non-exhaustive but canonical): `not_eligible`, `deadline_passed`, `duplicate_application`, `penalty_active`, `outcome_gate_placement`, `outcome_gate_internship`, `offer_cap_reached`, `membership_not_active`, `job_not_open`, `stale_view`, `window_closed`, `not_offered`, `offer_terminated`, `invalid_transition`, `unmatched_identifier`, `profile_incomplete`, `join_rule_failed`.

---

## 7. Transitions & Effects — declarative table (`domain/transitions.py`)

Transitions are a code-level constant (versioned in git; the Behavior Spec fixes them, admins never edit live — "force transition" is the flexibility valve). Shape:

```python
Transition(name, from_statuses, to_status, actors, requires_reason,
           in_tx=[...state consequences...], deferred=[...notif/schedule...], spec="APP-4.n")
```

| name | from → to | actor | in_tx consequences | deferred |
|---|---|---|---|---|
| apply | ∅ → in_progress | student | snapshot; round-1 state (pipeline jobs); event created | notify application_submitted |
| advance | in_progress → in_progress | staff | current round result=advanced; create next round state pending; event advanced | notify advanced (+venue if set) |
| advance_final | in_progress → pending_offer | staff | final round advanced; event | — |
| eliminate | in_progress → rejected | staff | round result=eliminated; event | notify rejected |
| bulk_reject / reject_pending_offer | in_progress,pending_offer → rejected | staff | event, reason | notify rejected |
| cancel_job (per app) | any non-terminal → rejected | staff | event reason=job_cancelled; **terminate any open offer row** (company_revoked, job-cancelled); accepted apps excluded & listed in preview | notify job_cancelled |
| extend_offer | in_progress,pending_offer → offered | staff | Offer row; event offer_extended | notify offer_extended; schedule enforce_offer_expiry(deadline) if any |
| accept | offered → accepted | student (dedicated) / staff (open) / system (expiry auto_accept) | set response; **cascade** per §7.1; event accepted (+auto events) | notify accepted; notify each cascaded |
| decline | offered → declined | student / staff (open) / system (expiry auto_decline) | set response; event declined | notify declined_confirm or offer_expired |
| withdraw | in_progress → withdrawn | student | event | — |
| auto_withdraw | in_progress,pending_offer → auto_withdrawn | system | event(payload.trigger ∈ acceptance/membership_exit/archival) | notify auto_withdrawn |
| terminate_offer | offered,accepted → offer_terminated | staff | Offer.termination_*; **[choice] restore ops** (per-app back to prior status+round from event history); event offer_terminated | [choice] notify; [choice] strike/penalty via discipline command chained in same plan |
| reinstate | rejected,withdrawn,auto_withdrawn → in_progress | staff | current_round := chosen; round states ≥ chosen reset per preview; event reinstated | [choice] notify |
| direct_offer / re_extend | any non-accepted → offered | staff | new Offer row; event offer_extended | notify; schedule expiry if deadline |
| force | any → any (whitelist = full matrix minus self) | staff | event forced_transition (reason required); NO implicit consequences — preview lists none, staff use targeted interventions when consequences are wanted | [choice] notify |

**Composed transitions (open cycles):** `record_open_outcome` targeting `accepted`/`declined` from `in_progress` executes extend_offer → accept/decline as two table rows in one transaction (Offer row + two events). The machine is never bypassed. **Reinstate guard:** `reinstate` is rejected with `duplicate_application` if any *other* active application (partial-unique predicate) exists for the same (enrollment, job) — e.g. the student withdrew and re-applied; reinstating the old row would violate the index.

**7.1 Acceptance cascade (in_tx, computed in `decide`):** lock enrollment's offers in the job's cycle (`FOR UPDATE`); cap check if cycle cap set; then per Behavior OFR-3: outcome=placement ⇒ across ALL cycles: other `offered` placement-outcome apps → declined (event auto_declined), `in_progress|pending_offer` placement-outcome apps → auto_withdrawn; outcome=internship ⇒ same but only if job's cycle kind = internship, scoped to that cycle; open-cycle internship acceptance ⇒ no cascade. Placement gate re-check inside tx: `EXISTS(accepted, unterminated, placement)` including external_offers.

**Effect handler registry** (`deferred` task names): `deliver_notification(event_key, recipient, ctx)`, `enforce_offer_expiry(offer_id)`, `build_export(export_id)` — that's all. Everything else is in_tx.

---

## 8. Database Schema (normative; Alembic models must match exactly)

Notation: `col type` flags: `!`=not null, `U`=unique, `→t`=FK. All tables: `id uuid pk default gen_random_uuid()`, `created_at timestamptz! default now()`; mutable tables add `updated_at`.

```
users(email citext !U, full_name text!, role role_t! default 'student',
      is_active bool! default true)
sessions(token_hash text !U, user_id →users!, expires_at !, revoked_at)
enrollments(user_id →users!, is_current bool!, roll_number citext)
  IDX partial-unique (roll_number) WHERE is_current AND roll_number IS NOT NULL
  IDX partial-unique (user_id) WHERE is_current
profiles(enrollment_id →enrollments !U, program_id →programs, primary_branch_id →branches,
      secondary_branch_id →branches, graduating_year int, cpi numeric(4,2),
      active_backlogs int, total_backlogs int, gender gender_t, personal_email citext,
      contact_number text, nationality text default 'IN', tenth_percent numeric(5,2),
      tenth_year int, twelfth_percent numeric(5,2), twelfth_year int,
      minor1_id →minors, minor2_id →minors, github_url text, linkedin_url text,
      portfolio_url text, declared_at timestamptz)      -- null until first save
resumes(enrollment_id →enrollments!, label text!, drive_url text!, is_default bool!)
  IDX partial-unique (enrollment_id) WHERE is_default
staged_profile_rows(institute_email citext!, payload jsonb!, uploaded_by →users!,
      applied_at, error text)

programs(name text !U, is_active bool!)      branches(name text !U, is_active bool!)
program_branches(program_id →programs!, branch_id →branches!, UNIQUE pair)
minors(name text !U, is_active bool!)        sectors(name text !U, is_active bool!)
round_types(name text !U, is_active bool!)
settings(key text pk, value jsonb!, updated_by →users, updated_at)
   -- keys: strikes_per_penalty(int|null), session_hours(int), ses_sender(str), dev seeds…

cycles(name citext !U, kind cycle_kind_t!, description text, starts_on date, ends_on date,
      registration_opens_at timestamptz, registration_closes_at timestamptz,
      is_active bool! default false, archived_at timestamptz)
  CHECK (starts_on IS NULL OR ends_on IS NULL OR starts_on <= ends_on)
cycle_policies(cycle_id →cycles !U, membership_requires_approval bool!,
      join_rule jsonb, max_accepted_offers int,            -- NULL = uncapped
      penalty_blocks_applications bool!, allow_withdrawal_after_deadline bool!,
      allow_edit_after_deadline bool!, strike_on_absence bool!,
      offer_expiry_behavior offer_expiry_t! default 'auto_decline',
      deadline_reminder_hours int! default 6, round_reminder_hours int! default 24)
cycle_coordinators(cycle_id →cycles!, user_id →users!, UNIQUE pair)
cycle_memberships(cycle_id →cycles!, enrollment_id →enrollments!, UNIQUE pair,
      status membership_status_t!, default_resume_id →resumes ON DELETE SET NULL,
      consented_at, decided_by →users, decided_at, rejection_reason text,
      outcome_tag outcome_tag_t, auto_created bool! default false)

companies(name citext !U, description text, website_url text, sector_id →sectors,
      is_active bool! default true)
company_contacts(company_id →companies!, name text!, email citext!, phone text,
      designation text, is_primary bool!, UNIQUE(company_id,email))
  IDX partial-unique (company_id) WHERE is_primary

jobs(cycle_id →cycles!, company_id →companies!, outcome outcome_t!, title text!,
      description text!, location text, sector_id →sectors, ctc_lpa numeric(10,2),
      ctc_breakdown text, stipend_month numeric(10,2), application_deadline timestamptz,
      offer_acceptance_deadline timestamptz, is_published bool! default false,
      published_at, cancelled_at, eligibility_rule jsonb, eligibility_summary text)
  CHECK (offer_acceptance_deadline IS NULL OR application_deadline IS NULL
         OR offer_acceptance_deadline > application_deadline)
  -- application_deadline NULL permitted only when cycle.kind='open' (command-enforced + checker)
job_program_ctc(job_id →jobs!, program_id →programs!, ctc_lpa numeric(10,2)!, UNIQUE pair)
job_rounds(job_id →jobs!, round_type_id →round_types!, name text!, ord int!,
      venue text, scheduled_at timestamptz, duration_min int, instructions text,
      UNIQUE(job_id, ord) DEFERRABLE INITIALLY DEFERRED)
job_questions(job_id →jobs!, ord int!, text text!, qtype question_type_t!, required bool!)
job_question_options(question_id →job_questions!, ord int!, text text!)

applications(job_id →jobs!, enrollment_id →enrollments!, status application_status_t!,
      current_round_id →job_rounds ON DELETE RESTRICT, resume_url text!,
      profile_snapshot jsonb!, applied_at timestamptz!)
  IDX partial-unique (job_id, enrollment_id)
      WHERE status NOT IN ('withdrawn','auto_withdrawn')
  IDX (enrollment_id, status), (job_id, status)
application_answers(application_id →applications!, question_id →job_questions!,
      value jsonb!, UNIQUE pair)
application_round_states(application_id →applications!, round_id →job_rounds!,
      result round_result_t! default 'pending', attendance attendance_t! default 'pending',
      venue_override text, scheduled_at_override timestamptz, notified_at, UNIQUE pair)
application_events(application_id →applications!, event_type event_type_t!,
      from_status application_status_t, to_status application_status_t,
      from_round_id →job_rounds, to_round_id →job_rounds, actor_user_id →users,
      reason text, payload jsonb! default '{}', batch_id uuid)
  -- APPEND-ONLY: app role gets INSERT+SELECT only (migration revokes UPDATE/DELETE)

offers(application_id →applications!, extended_at timestamptz!, deadline_at timestamptz,
      response offer_response_t, responded_at, terminated_at, terminated_by →users,
      termination_kind termination_kind_t, termination_reason text)
  IDX (application_id, extended_at DESC)
external_offers(enrollment_id →enrollments!, company_id →companies!, outcome outcome_t!,
      source external_source_t!, ctc_lpa numeric(10,2), stipend_month numeric(10,2),
      status external_status_t!, offered_on date, responded_on date,
      source_application_id →applications, attached_cycle_id →cycles, notes text,
      created_by →users!)

strikes(enrollment_id →enrollments!, reason text!, source strike_source_t!,
      awarded_by →users, is_active bool! default true, consumed_by_penalty_id →penalties)
penalties(enrollment_id →enrollments!, reasons text!, from_strikes bool!,
      is_active bool! default true, created_by →users, revoked_at, revoked_by →users)
overrides(rule_domain rule_domain_t!, allow bool! default true, cycle_id →cycles,
      job_id →jobs, enrollment_id →enrollments, application_id →applications,
      reason text!, granted_by →users!, expires_at, is_active bool! default true,
      CHECK scope is exactly one of: cycle; job; enrollment; cycle+enrollment;
            job+enrollment; application)

notification_templates(event_key text!, cycle_id →cycles, subject text!, body text!,
      enabled bool! default true, UNIQUE(event_key, cycle_id) NULLS NOT DISTINCT)
notification_log(recipient citext!, event_key text!, subject text!, status notif_status_t!,
      attempts int! default 0, last_error text, sent_at, context jsonb!)
reminder_sends(kind text!, dedup_key text !U)     -- e.g. 'deadline:job:enr', 'round:rnd:app'
audit_log(actor_user_id →users, action text!, subject_type text, subject_id uuid,
      details jsonb!)                              -- APPEND-ONLY like events
idempotency_keys(key text !U, command text!, result jsonb!, created_at)
consistency_findings(invariant text!, subject jsonb!, detail text!,
      status finding_status_t! default 'open', suggested_fix text, resolved_at)
export_presets(job_id →jobs !U, columns jsonb!)
export_jobs(kind text!, params jsonb!, status text!, requested_by →users!,
      result_meta jsonb, error text)
(+ Procrastinate's own tables via its schema migration)
```

**Derivations are queries, never columns** (G-doctrine): `placement_placed(enrollment)` = `EXISTS accepted-unterminated placement offer (offers⋈applications⋈jobs) OR EXISTS external_offers(status='accepted', outcome='placement')`. `internship gate(cycle)` = same, filtered to the cycle's jobs + externals `attached_cycle_id = cycle`. `cap_used(enrollment, cycle)` = count of both sources in that cycle. Provide these as named SQL fragments in `modules/offers/derivations.py`; the checker (§12) re-asserts them.

---

## 9. Rules, Gates, Policy

**9.1 Rule tree JSON** (`eligibility_rule`, `join_rule`):
```json
{"all":[ {"field":"program_id","op":"in","value":["<uuid>","<uuid>"]},
         {"any":[ {"field":"cpi","op":"gte","value":8.0},
                  {"all":[{"field":"primary_branch_id","op":"eq","value":"<uuid>"},
                           {"field":"cpi","op":"gte","value":7.5}]}]},
         {"criterion":"not_placement_placed"},
         {"field":"active_backlogs","op":"lte","value":0} ]}
```
Nodes: `all|any|not` (nested arbitrarily), leaf `{"field",op,value}` or `{"criterion":name}`. Ops: `eq ne in not_in gte lte between`. Fields = the profile registry (exact `profiles` columns + `graduating_year` etc.); the builder UI compiles presets to this. Validation: Pydantic discriminated union; unknown field/op ⇒ 422 at save.

**9.2 Evaluator** (`domain/rules.py`, pure): `evaluate(tree, profile_row, ctx) -> (bool, failed: [{path, code, human}])`. **CPI contract:** `Decimal(cpi).quantize(0.1, ROUND_HALF_UP)` before any cpi comparison — the ONLY rounding, used identically in previews/reasons. `ctx` supplies criterion results (`not_placement_placed` precomputed by loader). Table-driven tests are mandatory (each op × edge; 7.95→pass ≥8.0; 7.94→fail).

**9.3 Standing gates** (`domain/gates.py`, run in order, with only the domains declared by the command available to override-aware gates; ordering per Behavior ELG-3): membership_active → job_open (published, not cancelled, **cycle not archived** — the same archived check guards every cycle-scoped staff command in `check_scope`) → deadline (skip if NULL) → duplicate_active → penalty (if cycle policy) → outcome_gate (placement: global derivation; internship: dedicated-cycle-scoped derivation; open-cycle internship jobs: skip) → offer_cap (skip if NULL cap). Each returns `Reason` on failure; the whole list returns for display (job cards show all failing reasons, not just first). Membership state, job-open state, duplicate applications, penalties, and `cycles.is_active` are non-overridable. Cycle joining separately applies `cycle_registration_window` to the registration dates and `cycle_join_rule` to the profile rule; both `join_cycle` and re-request use those same pure gates.

**9.4 Policy resolver** (`domain/policy.py`): `resolve(state) -> Policy` merging settings + cycle_policies; every resolved value carries provenance `{"value":…, "source":"cycle_policy|setting|default"}`; provenance goes into event payloads when a policy influenced a decision.

---

## 10. Command Catalog (registry entries; each = Pydantic input + loader + decide)

Columns: **Command** (registry name = route) · **Actor/scope** · **Notes (gates/plan highlights)**. All staff commands are cycle-scoped for coordinators unless marked ADMIN. `spec=` ties to Behavior IDs.

**identity/** `dev_login`(dev-flag only) · `logout` · `start_new_enrollment` ADMIN (creates enrollment, flips is_current; spec IDN-2) · `set_user_role` ADMIN · `deactivate_user` ADMIN
**profiles/** `declare_profile` student, once (sets declared_at; validates program↔branch map) · `update_student_fields` student (whitelist in code: the student-managed columns, plus admin-managed ones still blank, plus the student-maintained academic four — graduating year, CPI, both backlog counts) · `admin_update_profile` ADMIN (any field, audited) · `bulk_upsert_profiles` ADMIN (CSV/XLSX parse → chunked; email key; roll cross-check ⇒ row error; unmatched ⇒ staged_profile_rows; preview per PRO-2) · `add_resume|update_resume|delete_resume|set_default_resume` student (URL-shape validation only; delete blocked if referenced by a membership default → SET NULL is allowed, just warn)
**taxonomies/** `upsert_taxonomy_item` ADMIN (per kind; deactivate instead of delete when referenced) · `set_setting` ADMIN
**cycles/** `create_cycle|update_cycle` ADMIN (create inserts the `cycle_policies` row in the same plan, defaults keyed by kind: approval on/on/off, cap 1/1/NULL) · `set_cycle_active` ADMIN · `archive_cycle` ADMIN (preview lists non-terminal apps; executes bulk auto_withdraw trigger=archival; spec CYC-1) · `update_cycle_policy` ADMIN · `assign_coordinator|remove_coordinator` ADMIN (+notify)
**memberships/** `join_cycle` student (profile-complete check, join_rule, consent, default resume; → pending|active per policy) · `approve_memberships` staff BULK · `reject_membership` staff (reason!) · `rerequest_membership` student · `withdraw_membership` student (cascades auto_withdraw same cycle) · `remove_membership` staff (reason; cascades) · `restore_membership` staff · `set_outcome_tag` staff
**companies/** `create_company|update_company` staff · `contact_create|update|delete` staff · `deactivate_company` ADMIN · `merge_companies` ADMIN (repoint jobs/contacts/external_offers; preview counts)
**jobs/** `create_job` staff (outcome forced by cycle kind; open ⇒ required choice; deadline required unless open) · `update_job_basics` staff (deadline-move ⇒ deferred notify applicants) · `update_job_eligibility` staff (validate tree; regenerate summary; impact preview = count+list of currently-eligible members; NO effect on existing apps) · `upsert_job_rounds` staff (delete blocked if any round_state exists; insert ok ⇒ deferred process_changed notify to in-flight) · `upsert_job_questions` staff (remove/retype blocked if answers exist) · `publish_job|unpublish_job` staff · `cancel_job` staff (bulk per-app transition; spec JOB-5) · `save_export_preset` staff
**applications/** `apply` student (gates §9.3 + rule; snapshot; spec APP-1) · `edit_application` student (window per policy; replaces answers; resume swap) · `withdraw_application` student (window)
**rounds/** `advance_applications` staff BULK (selection|pasted identifiers) · `eliminate_applications` staff BULK · `waitlist_applications` staff BULK · `promote_waitlisted` staff BULK · `mark_attendance` staff (single toggle) · `bulk_mark_present` staff BULK (pasted rolls) · `finalize_round` staff (preview: absents→rejected+strike?, excused→rejected, pending→absent; spec RND-3) · `assign_venue_timing` staff BULK (rows|CSV/XLSX upload; per-row validation; sets overrides + deferred venue notify)
**offers/** `extend_offers` staff BULK (from in_progress or pending_offer; schedules expiry) · `accept_offer` student (dedicated cycles; expected_status) · `decline_offer` student · `record_open_outcome` staff BULK (open cycles: →offered|accepted|declined|rejected directly; spec JOB-6) · `terminate_offer` staff (choices: restore-list, discipline, notify; spec OFR-5) · `re_extend_offer` staff
**external/** `create_external_offer` staff (also via source_application prefill) · `update_external_offer` staff (status→accepted fires cascade preview; away-from-accepted fires restore choices; spec EXT-4) · `delete_external_offer` staff (same preview rules) · `attach_external_offer|detach_external_offer` staff-of-target-cycle (kind must match outcome; attach may auto-create membership `auto_created=true`; bulk variant `attach_external_offers`)
**discipline/** ADMIN: `award_strike` (manual) · `revoke_strike` (recompute conversion vs global threshold) · `award_penalty` · `revoke_penalty` (spec DIS)
**overrides/** staff(cycle)/ADMIN: `create_override` · `deactivate_override`
**interventions/** staff: `reinstate_application` (choose round; preview round-state resets) · `force_transition` (reason!) · ADMIN: `resolve_finding|dismiss_finding`
**notifications/** ADMIN: `update_template` · staff: `resend_notification`
**analytics/exports** staff: `request_export` (spreadsheet build → export_jobs + deferred build_export)

Every command's `decide` cites its Behavior IDs in a docstring; tests reference the same IDs.

---

## 11. API Surface

**11.1 Writes:** routes generated from the registry at startup: `POST /api/v1/commands/{name}` with body `{"input": {...}, "dry_run": bool, "idempotency_key": str|null}` → `200 {summary}` | `200 {preview}` | `4xx problem+json {type, title, reasons:[{code,human,path?}]}`. FastAPI `add_api_route` per command with its Pydantic models ⇒ OpenAPI enumerates every command with full typing ⇒ the TS client gets one typed function per command. Rate limits: bulk commands 10/min/user, exports 5/min/user (in-process limiter, fail-open).

**11.2 Reads:** screen-shaped: `GET /api/v1/screens/{screen_id}` (+query params) returning exactly what the screen renders, one authz check. Plus small resource reads where reuse demands (`GET /taxonomies`, `GET /me`).

**11.3 Screen catalog** (screen_id · role · content):
`me/dashboard` student — memberships, apps+statuses, upcoming rounds w/ venue, offers awaiting action, external offers RO, discipline, enrollment history · `me/profile` · `cycles/joinable` · `cycle/{id}/jobs` student — all published, eligibility verdict + ALL failing reasons per card · `job/{id}` student — detail + apply-form schema (questions) · `me/applications` · `staff/cycles` · `staff/cycle/{id}` — funnel, pending-approvals count, policy · `staff/cycle/{id}/approvals` — queue + bulk UI · `staff/cycle/{id}/jobs` · `staff/job/{id}/builder` (basics|eligibility w/ live impact preview|rounds|questions, plus a dedicated job-override panel) · `staff/job/{id}/board` — ATS board: per-round columns, attendance, bulk selection state · `staff/job/{id}/offers` · `staff/job/{id}/analytics` · `staff/cycle/{id}/external` — attached + matching unattached pool · `staff/external` — global pool CRUD · `staff/student/{enrollment_id}` — full drill-down, event timelines, snapshot-vs-live diff · `admin/taxonomies` · `admin/settings` · `admin/users` · `admin/bulk-upsert` (preview/commit) · `admin/discipline` · `admin/overrides` · `admin/findings` · `admin/templates` · `admin/analytics/portal` · `staff/cycle/{id}/analytics` · `staff/company/{id}` · `staff/companies`.
Interventions surface inside the relevant screens (student drill-down, ATS board, offers panel) — every destructive button = dry_run first, render `preview.summary` + choices, then execute with same input + `confirm:true` choice payload.

**11.4 Auth:** `GET /auth/google/login|callback` (Authlib; server-side verify `hd`/domain); `POST /commands/dev_login` only when `DEV_LOGIN=1`. Session cookie `cds_session` httpOnly Secure SameSite=Lax; CSRF: custom header `X-CSRF` double-submit token on all POSTs.

---

## 12. Background Jobs (worker.py — all handlers idempotent)

| Task | Trigger | Behavior |
|---|---|---|
| `deliver_notification` | deferred | render template (cycle override → global; missing var ⇒ blank + warn), SES send, notification_log upsert; retry backoff ×5 then status=dead (admin re-send) |
| `enforce_offer_expiry` | scheduled at deadline | **fire-time re-validation**: offer is the application's latest, response NULL, unterminated, **application still `offered`**, and `offers.deadline_at` (the authority; job-deadline edits propagate here per JOB-3) unchanged vs the fire argument (moved ⇒ reschedule, else no-op); then run `decline` or `accept` transition as system per cycle policy (spec OFR-4) |
| `send_deadline_reminders` | cron hourly | jobs w/ deadline in [now+offset−30m, now+offset+30m]; active members, currently eligible (live gates+rule), not applied; dedup via reminder_sends |
| `send_round_reminders` | cron every 6h | round_states with effective schedule in [offset window], relevance re-check (app still in_progress at that round); dedup |
| `run_consistency_checker` | cron 03:00 | assert: stored status ≡ last event; partial-unique holds; cap≤policy where set; placement-gate derivation vs accepted rows; **≤1 accepted unterminated placement offer per enrollment globally**; **no open (unresponded, unterminated) offer on an application whose status ≠ offered**; from_strikes penalties supported ≥ global threshold; no in_progress app on non-active membership; round_states exist ≤ current; external attachments kind-match; no NULL-deadline jobs outside open cycles; **no offer_acceptance_deadline on open-cycle jobs**; expired overrides uncredited post-expiry ⇒ findings rows |
| `build_export` | deferred | openpyxl/csv build per preset/params → export_jobs.result_meta (bytes stored? NO files ⇒ stream: build on request instead? decision: exports are built synchronously streamed for ≤5k rows, deferred+poll only if >5k; result held 24h in export_jobs.result_meta as base64 ≤10MB, else re-run) |

---

## 13. Notification event keys (template variables in parentheses)
`application_submitted(student,job,company)` · `advanced(next_round,venue?,time?)` · `rejected(round?,reason)` · `absent_marked(round,strike_total?)` · `offer_extended(deadline?)` · `offer_accepted` · `auto_declined(accepted_job)` · `auto_withdrawn(trigger)` · `offer_terminated(kind,reason)` · `offer_expired(behavior)` · `external_recorded(source,outcome)` · `external_updated` · `strike_added(reason,total)` · `strike_revoked(total)` · `penalty_added(reasons)` · `penalty_revoked` · `venue_timing(round,venue,time,is_update)` · `process_changed(job)` · `job_cancelled` · `membership_pending` · `membership_approved` · `membership_rejected(reason)` · `membership_removed(reason)` · `membership_restored` · `coordinator_assigned(cycle)` · `coordinator_removed(cycle)` · `deadline_reminder(hours_left)` · `round_reminder(round,venue?,time?)`. Seed migration inserts default templates for all keys.

---

## 14. Testing Strategy & CI gates

Layers: **(a) pure** — rules evaluator table tests; gates; every transition's `decide` incl. cascade matrices; policy resolver provenance. **(b) executor/guarantee** — G1: raise inside apply_state_ops ⇒ assert 0 rows, 0 procrastinate jobs; G3: same via decide-then-fail; preview parity: `dry_run.events == executed events` for a sample of every command; idempotent replay returns cached result, 0 new rows; append-only: UPDATE on events as app role ⇒ permission error. **(c) concurrency** — two parallel `accept_offer` same enrollment/cycle cap=1 ⇒ exactly one accepted (real threads, real PG); duplicate `apply` race ⇒ unique-violation surfaced as `duplicate_application`; `expected_status` stale ⇒ `stale_view`. **(d) API/authz matrix** — generated: every command+screen × {anon, student, wrong-cycle coordinator, right-cycle coordinator, admin} asserting allow/deny per registry metadata. **(e) E2E (Playwright)** — student happy path; terminate-accepted-offer intervention with restore; bulk advance via pasted rolls with preview.
**CI:** ruff + pyright(strict on domain/, core/) + forbidden-pattern gate (regex: `\.commit\(|\.begin\(` outside core/executor.py & alembic; `session\.` inside routers) + pytest + client-gen + `tsc --noEmit` + vitest. Merge blocked on red.

---

## 15. Ops & Deployment

**Compose services:** `caddy` (443/80; Caddyfile: domain → auto-TLS, `/api/*` → api:8000, else static `frontend/dist`), `api` (uvicorn, 2 workers), `worker` (`procrastinate worker` + periodic), `db` (postgres:16; volumes: data + `wal_archive`; `archive_mode=on`, `archive_command='/opt/cds/archive-wal %p %f'` (atomic gzip)), `backup` (alpine+rclone+pg tools; cron: `*/5 * * * *` gzip immutable WAL and sync it to `gdrive:cds/wal` · `0 2 * * * pg_basebackup → tar → rclone gdrive:cds/base` · `0 3 * * * pg_dump -Fc → rclone gdrive:cds/dumps`; retention: newest seven bases, WAL from the oldest retained base, dumps 7d — `BASE_RETENTION_COUNT` is the recovery reach). rclone remote `gdrive` via service-account/OAuth token in env.
**Restore drill (documented in repo, rehearsed once):** fresh volume → restore latest base → replay WAL from Drive with `restore_command` → `recovery_target_time` → verify counts vs checker; fallback: latest pg_dump.
**Env:** `DATABASE_URL, SESSION_SECRET, GOOGLE_CLIENT_ID/SECRET, ALLOWED_DOMAIN=<institution-domain>, SES_*, DEV_LOGIN=0/1, BASE_URL`. Migrations run as release gate (`alembic upgrade head` before api starts; compose `depends_on` + entry script).
**Seed:** `python -m app.seed` — taxonomies, admin user, demo cycles(3 kinds), companies, jobs incl. rules, 40 students with profiles, applications across states, external offers. Idempotent.

---

## 16. Frontend architecture (brief, binding)
Generated client in `src/api/gen/`; wrapper `api.command(name, input, {dryRun})` + `api.screen(id, params)`. One TanStack Query hook per screen (`useScreen(screenId, params)`); mutations invalidate their screen key(s) listed in a `SCREEN_DEPS` map. Destructive-action pattern (single shared component `<PreviewConfirm>`): dry_run → render summary/choices → confirm. Reason codes → human strings via a single `reasons.ts` map (mirrors backend constants). No client-side authz logic beyond hiding — server decides. Vite proxy in dev; `pnpm gen` regenerates client from `/openapi.json`.

---

## 17. Traceability map (Behavior ID → module)
IDN-1/2/3 → identity · PRO-1/2/3 → profiles · CYC-1..4 → cycles · CMP → companies · JOB-1..6 → jobs · ELG-1..3, DER-1 → domain/rules+gates + offers/derivations · APP-1..4 → applications + domain/transitions · RND-1..4 → applications (rounds) · OFR-1..5 → offers · EXT-1..4 → offers/external · DIS → discipline · INT-1/2 → interventions + overrides · NTF → notifications · ANA-1..4 → analytics · TAX → taxonomies/admin · §16-doctrine → core/executor + checker. Every test file header cites the IDs it proves.

---

## 18. Explicitly deferred from v1 build
In-portal notification feed (schema-ready: notification_log has context) · Playwright beyond 3 flows · Prometheus/Grafana · NIRF exact formats (provisional columns per ANA-3) · multi-node anything.
