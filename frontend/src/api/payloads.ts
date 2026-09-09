/**
 * Hand-written shapes for the screen payloads.
 *
 * The generated client types every screen response as an open object, because
 * the handlers return `dict[str, object]` and FastAPI cannot describe that any
 * more precisely. Rather than cast at each use, every shape the UI reads is
 * declared once here and narrowed once through `payload`.
 *
 * These are a *description*, not a contract — the server is the authority, and
 * `backend/tests/test_screen_execution.py` is what proves a screen still
 * returns these keys. When a payload changes, this file changes with it; the
 * point is that there is exactly one place to change.
 */

export interface CycleHeader {
  id: string;
  name: string;
  kind: string;
  archived_at?: string | null;
}

export interface TaxonomyRef {
  id: string;
  name: string;
}

/* -------------------------------------------------------------- cycles --- */

export interface StudentCyclesPayload {
  enrollment_id: string;
  profile_complete: boolean;
  required_fields: string[];
  resumes: ResumeChoice[];
  cycles: {
    id: string;
    name: string;
    kind: string;
    description: string | null;
    starts_on: string | null;
    ends_on: string | null;
    registration_opens_at: string | null;
    registration_closes_at: string | null;
    is_active: boolean;
    archived_at: string | null;
    membership: {
      membership_id: string;
      status: string;
      rejection_reason: string | null;
    } | null;
    can_join: boolean;
    reasons: EligibilityReason[];
    requires_approval?: boolean;
  }[];
}

export interface StaffCyclesPayload {
  filters: { kind: string | null; include_archived: boolean };
  actions: { create: ActionPermission };
  cycles: {
    id: string;
    name: string;
    kind: string;
    description: string | null;
    registration_opens_at: string | null;
    registration_closes_at: string | null;
    is_active: boolean;
    archived_at: string | null;
    pending_count: number;
    active_count: number;
    job_count: number;
  }[];
}

/** A policy value plus where it came from — cycle override or code default. */
export interface PolicyValue<T> {
  value: T;
  source: string;
}

export interface StaffCyclePayload {
  actions: { manage: ActionPermission };
  cycle: CycleHeader & {
    description: string | null;
    is_active: boolean;
    // CYC-1: informational, for display and analytics year-grouping. Nothing
    // gates on them; the registration window and the active flag do that.
    starts_on: string | null;
    ends_on: string | null;
    registration_opens_at: string | null;
    registration_closes_at: string | null;
  };
  policy: {
    membership_requires_approval: PolicyValue<boolean>;
    join_rule: PolicyValue<Record<string, unknown> | null>;
    max_accepted_offers: PolicyValue<number | null>;
    penalty_blocks_applications: PolicyValue<boolean>;
    allow_withdrawal_after_deadline: PolicyValue<boolean>;
    allow_edit_after_deadline: PolicyValue<boolean>;
    strike_on_absence: PolicyValue<boolean>;
    offer_expiry_behavior: PolicyValue<string>;
    deadline_reminder_hours: PolicyValue<number>;
    round_reminder_hours: PolicyValue<number>;
  };
  coordinators: { user_id: string; full_name: string; email: string }[];
  /** Counts per membership status, not a roster — the roster is the approvals screen. */
  memberships: Record<string, number>;
  /** Counts per application status. Empty until M10 writes any. */
  applications: Record<string, number>;
  pending_approvals: number;
}

export interface ApprovalsPayload {
  cycle: CycleHeader & { archived: boolean };
  filters: { status: string };
  /** Every membership status, so the queue can also be read as the roster. */
  statuses: string[];
  rows: {
    membership_id: string;
    enrollment_id: string;
    full_name: string;
    email: string;
    roll_number: string | null;
    status: string;
    program: string | null;
    branch: string | null;
    cpi: string | null;
    graduating_year: number | null;
    consented_at: string | null;
    decided_at: string | null;
    rejection_reason: string | null;
    outcome_tag: string | null;
    resume: { label: string; drive_url: string } | null;
    actions: {
      set_outcome_tag: ActionPermission;
      remove_membership: ActionPermission;
      restore_membership: ActionPermission;
    };
  }[];
}

export interface MyNotificationsPayload {
  notifications: {
    id: string;
    event_key: string;
    subject: string;
    status: string;
    /** Null until delivery succeeds; the row exists from the moment it queues. */
    sent_at: string | null;
    recorded_at: string;
  }[];
}

/* ----------------------------------------------------------- companies --- */

export interface CompaniesPayload {
  filters: { q: string | null; sector_id: string | null; include_inactive: boolean };
  sectors: TaxonomyRef[];
  companies: {
    id: string;
    name: string;
    description: string | null;
    website_url: string | null;
    is_active: boolean;
    sector: TaxonomyRef | null;
    contact_count: number;
    job_count: number;
    primary_contact: { name: string; email: string } | null;
  }[];
}

export interface CompanyPayload {
  actions: { manage_activity: ActionPermission; merge: ActionPermission };
  company: {
    id: string;
    name: string;
    description: string | null;
    website_url: string | null;
    is_active: boolean;
    sector: TaxonomyRef | null;
  };
  contacts: {
    id: string;
    name: string;
    email: string;
    phone: string | null;
    designation: string | null;
    is_primary: boolean;
  }[];
  jobs: {
    id: string;
    title: string;
    outcome: string;
    is_published: boolean;
    is_cancelled: boolean;
    cycle: CycleHeader;
  }[];
  external_offer_count: number;
  /** M15: ANA-2's cross-cycle view, on the same screen per LLD §11.3. */
  analytics: CompanyAnalytics;
}

/* ---------------------------------------------------------------- jobs --- */

export interface JobSummaryRow {
  id: string;
  cycle_id: string;
  company: TaxonomyRef;
  outcome: string;
  title: string;
  description: string | null;
  location: string | null;
  sector: string | null;
  sector_id: string | null;
  ctc_lpa: string | null;
  ctc_breakdown: string | null;
  stipend_month: string | null;
  application_deadline: string | null;
  offer_acceptance_deadline: string | null;
  is_published: boolean;
  published_at: string | null;
  cancelled_at: string | null;
  eligibility_summary: string | null;
}

export interface StaffCycleJobsPayload {
  cycle: CycleHeader;
  filters: { include_cancelled: boolean };
  jobs: (JobSummaryRow & {
    round_count: number;
    question_count: number;
    application_count: number;
  })[];
}

export interface JobRound {
  round_id: string;
  round_type_id: string;
  round_type: string;
  name: string;
  ord: number;
  venue: string | null;
  scheduled_at: string | null;
  duration_min: number | null;
  instructions: string | null;
  deletable?: boolean;
}

export interface JobQuestion {
  question_id: string;
  text: string;
  qtype: string;
  required: boolean;
  ord: number;
  options: string[];
  answer_count?: number;
  removable?: boolean;
  retypable?: boolean;
}

export interface EligibilityReason {
  code: string;
  human: string;
  path?: string | null;
}

export interface SubjectOverride {
  id: string;
  rule_domain: string;
  allow: boolean;
  scope: string;
  state: "active" | "expired" | "shadowed";
  reason: string;
  expires_at: string | null;
  subject_label: string | null;
}

export interface BuilderPayload {
  cycle: CycleHeader & {
    supports_rounds: boolean;
    supports_offer_deadline: boolean;
    outcome_is_fixed: boolean;
  };
  job: JobSummaryRow & {
    rounds: JobRound[];
    questions: JobQuestion[];
    program_ctc: { program_id: string; program: string; ctc_lpa: string }[];
  };
  override_domains: string[];
  overrides: SubjectOverride[];
  eligibility: {
    rule: Record<string, unknown> | null;
    summary: string;
    impact: {
      eligible_count: number;
      member_count: number;
      members: {
        enrollment_id: string;
        full_name: string;
        roll_number: string | null;
        eligible: boolean;
        reasons: EligibilityReason[];
      }[];
    };
  };
  cancellation_preview: {
    targets: {
      application_id: string;
      full_name: string;
      status: string;
      open_offers: number;
    }[];
    untouched: {
      application_id: string;
      full_name: string;
      status: string;
      open_offers: number;
      suggested_command: string;
    }[];
  };
}

/* ------------------------------------------------------------- student --- */

export interface StudentJobsPayload {
  cycle: CycleHeader;
  membership_status: string;
  eligible_count: number;
  jobs: (JobSummaryRow & {
    round_count: number;
    question_count: number;
    eligible: boolean;
    reasons: EligibilityReason[];
    application: { application_id: string; status: string } | null;
  })[];
}

export interface ResumeChoice {
  id: string;
  label: string;
  drive_url: string;
  is_default: boolean;
  is_cycle_default?: boolean;
}

export interface StudentJobPayload {
  enrollment_id: string;
  cycle: CycleHeader;
  job: JobSummaryRow;
  compensation: {
    ctc_lpa: string | null;
    source: string;
    ctc_breakdown: string | null;
    stipend_month: string | null;
  };
  eligibility: { eligible: boolean; summary: string; reasons: EligibilityReason[] };
  rounds: JobRound[];
  apply_form: { questions: JobQuestion[]; resumes: ResumeChoice[] };
  application: { application_id: string; status: string } | null;
}

export interface RestorationCandidate {
  application_id: string;
  job_id: string;
  job: string;
  company: string;
  cycle_id: string;
  cycle: string;
  current_status: string;
  restore_status: string;
  target_round_id: string | null;
  requires_fresh_offer: boolean;
  deadline_editable: boolean;
  can_restore: boolean;
  blocked_reason: string | null;
  selected: boolean;
  deadline_at: string | null;
}

export interface StaffJobOffersPayload {
  job: {
    id: string;
    title: string;
    company: string;
    outcome: string;
    cancelled: boolean;
    offer_acceptance_deadline: string | null;
  };
  cycle: { id: string; name: string; kind: string; archived: boolean };
  applications: {
    application_id: string;
    enrollment_id: string;
    full_name: string;
    email: string;
    roll_number: string | null;
    status: string;
    current_round_id: string | null;
    offer: {
      id: string;
      deadline_at: string | null;
      response: string | null;
      terminated: boolean;
    } | null;
    offer_count: number;
    restoration_candidates: RestorationCandidate[];
    actions: {
      extend: ActionPermission;
      terminate: ActionPermission;
      re_extend: ActionPermission;
    };
  }[];
  counts: Record<string, number>;
  actions: { extend: ActionPermission; record_open_outcome: ActionPermission };
}

export interface ExternalOfferScreenRow {
  id: string;
  enrollment_id: string;
  student: string;
  email: string;
  roll_number: string | null;
  company: TaxonomyRef;
  outcome: string;
  source: string;
  ctc_lpa: string | null;
  stipend_month: string | null;
  status: string;
  offered_on: string | null;
  responded_on: string | null;
  source_application_id: string | null;
  attached_cycle: CycleHeader | null;
  notes: string | null;
  read_only: boolean;
  restoration_candidates?: RestorationCandidate[];
  actions: Record<string, ActionPermission>;
}

export interface StaffExternalPayload {
  filters: {
    q: string | null;
    status: string | null;
    outcome: string | null;
    attached: boolean | null;
  };
  actions: { create: ActionPermission };
  companies: TaxonomyRef[];
  enrollments: {
    id: string;
    full_name: string;
    email: string;
    roll_number: string | null;
  }[];
  offers: ExternalOfferScreenRow[];
}

export interface StaffCycleExternalPayload {
  cycle: CycleHeader & { archived: boolean };
  policy: { max_accepted_offers: number | null };
  attached: ExternalOfferScreenRow[];
  unattached_pool: ExternalOfferScreenRow[];
}

export interface DashboardPayload {
  enrollment_id: string;
  memberships: {
    id: string;
    status: string;
    auto_created: boolean;
    cycle: CycleHeader;
  }[];
  applications: {
    id: string;
    job: string;
    company: string;
    cycle: string;
    status: string;
  }[];
  upcoming_rounds: {
    application_id: string;
    job: string;
    cycle: string;
    round: string;
    scheduled_at: string | null;
    venue: string | null;
  }[];
  offers: {
    offer_id: string;
    application_id: string;
    cycle_id: string;
    cycle: string;
    job_id: string;
    job: string;
    company: string;
    outcome: string;
    status: string;
    deadline_at: string | null;
    response: string | null;
    terminated: boolean;
    actions: { accept: ActionPermission; decline: ActionPermission };
  }[];
  external_offers: ExternalOfferScreenRow[];
  discipline: { active_strikes: number; active_penalties: number };
}

/* --------------------------------------------------------------- admin --- */

export interface TaxonomyItem {
  id: string;
  name: string;
  is_active: boolean;
}

export interface TaxonomiesPayload {
  programs: TaxonomyItem[];
  branches: TaxonomyItem[];
  minors: TaxonomyItem[];
  sectors: TaxonomyItem[];
  round_types: TaxonomyItem[];
  program_branches: { program_id: string; branch_id: string }[];
}

export interface SettingsPayload {
  settings: {
    key: string;
    value: unknown;
    updated_by: string | null;
    updated_at: string;
  }[];
}

export interface TemplatesPayload {
  templates: {
    event_key: string;
    variables: string[];
    global: {
      id: string;
      cycle_id: null;
      cycle_name: null;
      subject: string;
      body: string;
      enabled: boolean;
      updated_at: string;
    } | null;
    overrides: {
      id: string;
      cycle_id: string;
      cycle_name: string;
      subject: string;
      body: string;
      enabled: boolean;
      updated_at: string;
    }[];
  }[];
  cycles: (CycleHeader & { archived_at: string | null })[];
  dead_letters: {
    id: string;
    recipient: string;
    event_key: string;
    subject: string;
    attempts: number;
    last_error: string | null;
    created_at: string;
    updated_at: string;
  }[];
}

export interface ActionPermission {
  allowed: boolean;
  reason: string | null;
  human: string | null;
}

export interface DisciplinePayload {
  threshold: PolicyValue<number | null>;
  roster: {
    enrollment_id: string;
    full_name: string;
    email: string;
    roll_number: string | null;
    is_current: boolean;
    active_strikes: number;
    active_penalties: number;
    blocked: boolean;
  }[];
  student: {
    enrollment_id: string;
    full_name: string;
    email: string;
    roll_number: string | null;
    active_strikes: number;
    active_penalties: number;
    unconsumed_strikes: number;
    strikes_to_next_penalty: number | null;
    strikes: {
      id: string;
      reason: string;
      source: string;
      created_at: string | null;
      updated_at: string | null;
      awarded_by: { id: string; name: string | null } | null;
      is_active: boolean;
      consumed_by_penalty_id: string | null;
      actions: { revoke: ActionPermission };
    }[];
    penalties: {
      id: string;
      reasons: string;
      from_strikes: boolean;
      created_at: string | null;
      created_by: { id: string; name: string | null } | null;
      is_active: boolean;
      revoked_at: string | null;
      revoked_by: { id: string; name: string | null } | null;
      actions: { revoke: ActionPermission };
    }[];
  } | null;
}

/**
 * Narrow a screen response to its declared shape.
 *
 * One cast, named, rather than one per field access. It asserts nothing at
 * runtime on purpose: the server already validated what it sent, and a client
 * that re-checks would only be able to blank the screen when the two drift.
 */
/* --------------------------------------------------------- applications --- */

export interface MeApplicationsPayload {
  /** Whose applications these are — the id the commands here must name. */
  enrollment_id: string;
  resumes: ResumeChoice[];
  applications: {
    id: string;
    status: string;
    applied_at: string | null;
    resume_url: string;
    answer_count: number;
    job: {
      id: string;
      title: string;
      outcome: string;
      company: string;
      application_deadline: string | null;
      cancelled: boolean;
    };
    cycle: { id: string; name: string; kind: string; archived: boolean };
    /** Null for an open-cycle application, which holds no position (JOB-6). */
    round: { name: string; ord: number; of: number } | null;
    can_edit: boolean;
    can_withdraw: boolean;
    edit_form: {
      questions: JobQuestion[];
      answers: { question_id: string; value: unknown }[];
    };
    window_reasons: { code: string; human: string; path: string | null }[];
    timeline: {
      event_type: string;
      from_status: string | null;
      to_status: string | null;
      reason: string | null;
      at: string | null;
    }[];
  }[];
  counts: { total: number; in_progress: number };
}

export interface StaffJobBoardPayload {
  job: {
    id: string;
    title: string;
    company: string;
    company_id: string;
    outcome: string;
    is_published: boolean;
    cancelled: boolean;
    /** False for an open-cycle job (JOB-6): no rounds, so no pipeline. */
    has_rounds: boolean;
  };
  cycle: { id: string; name: string; kind: string; archived: boolean };
  rounds: {
    id: string;
    ord: number;
    name: string;
    finalized_at: string | null;
    finalized_by: { id: string; name: string | null } | null;
    actions: { finalize: ActionPermission };
  }[];
  columns: {
    id: string;
    ord: number;
    name: string;
    finalized_at: string | null;
    finalized_by: { id: string; name: string | null } | null;
    actions: { finalize: ActionPermission };
    count: number;
    rows: BoardRowPayload[];
  }[];
  export_columns: ExportColumnOption[];
  export_preset: string[] | null;
  /** Live applicants holding no round position at all (JOB-6). */
  unrouted: BoardRowPayload[];
  /** Out of the pipeline: offered, rejected, withdrawn, accepted. */
  settled: BoardRowPayload[];
  counts: { total: number; in_pipeline: number; unrouted: number; settled: number };
}

export interface BoardRowPayload {
  application_id: string;
  enrollment_id: string;
  full_name: string;
  roll_number: string | null;
  email: string;
  status: string;
  /** True only while the applicant is presently sitting in this round. */
  is_current_round: boolean;
  round: { id: string; name: string | null; ord: number | null } | null;
  result: string | null;
  attendance: string | null;
  /** The slot this student actually has: their override, else the round's. */
  venue: string | null;
  scheduled_at: string | null;
  slot_is_override: boolean;
  slot_notified_at: string | null;
  /** What each operation would do — the server's answer, not a client guess. */
  actions: Record<
    string,
    {
      allowed: boolean;
      reason: string | null;
      human?: string | null;
      to_status?: string | null;
      to_round?: string | null;
    }
  >;
}

/* ------------------------------------------------------------ profiles --- */

export interface MeProfilePayload {
  enrollment: {
    id: string;
    is_current: boolean;
    institute_email: string | null;
  };
  declared_at: string | null;
  /**
   * `editable` is the server's own verdict, not a rule to re-derive here: an
   * admin-managed field is the student's to supply until it first holds a
   * value, and only the server knows whether it does (the design review §4.33).
   */
  fields: {
    key: string;
    label: string;
    owner: "student" | "admin";
    home: string;
    editable: boolean;
  }[];
  values: Record<string, unknown>;
  resumes: (ResumeChoice & { preview_url: string })[];
  taxonomies: Record<"programs" | "branches" | "minors", TaxonomyRef[]>;
  program_branches: { program_id: string; branch_id: string }[];
}

export interface ProfileUploadRow {
  row_number: number;
  institute_email: string;
  fields: Record<string, unknown>;
}

export interface AdminBulkUpsertPayload {
  columns: { key: string; label: string; owner: string; home: string }[];
  email_column: string;
  staged: Record<"pending" | "errored" | "applied", {
    id: string;
    institute_email: string;
    raw: Record<string, unknown>;
    fields: Record<string, unknown>;
    batch_key: string | null;
    row_number: number | null;
    uploaded_by_email: string | null;
    created_at: string;
    applied_at: string | null;
    error: string | null;
  }[]>;
}

export interface AdminUsersPayload {
  filters: { q: string | null; include_inactive: boolean };
  counts: { total: number; active: number; admins: number };
  users: {
    id: string;
    email: string;
    full_name: string;
    role: "student" | "admin";
    is_active: boolean;
    created_at: string;
    current_enrollment: {
      id: string;
      roll_number: string | null;
      profile_declared: boolean;
    } | null;
    enrollment_count: number;
    enrollments: {
      id: string;
      roll_number: string | null;
      is_current: boolean;
      created_at: string;
    }[];
    actions: {
      start_new_enrollment: ActionPermission;
      set_role: ActionPermission;
      deactivate: ActionPermission;
    };
  }[];
}

/* ------------------------------------------------- M14: overrides --- */

export interface OverrideRow {
  id: string;
  rule_domain: string;
  allow: boolean;
  scope: string;
  subject_id: string;
  subject_label: string;
  cycle_id: string | null;
  cycle_name: string | null;
  reason: string;
  granted_by: { id: string; name: string };
  created_at: string | null;
  expires_at: string | null;
  /** active | expired | deactivated — computed by the server, not the client. */
  state: string;
  is_active: boolean;
  actions: { deactivate: ActionPermission };
}

export interface AdminOverridesPayload {
  overrides: OverrideRow[];
  filters: {
    rule_domain: string | null;
    scope: string | null;
    cycle_id: string | null;
    state: string | null;
  };
  rule_domains: string[];
  scopes: string[];
  states: string[];
  cycles: { id: string; name: string; kind: string; archived: boolean }[];
  counts: Record<string, number>;
}

/* -------------------------------------------------- M14: findings --- */

export interface FindingRow {
  id: string;
  invariant: string;
  description: string;
  subject: Record<string, unknown>;
  /**
   * A human name for each subject id the server could resolve, keyed the same
   * as `subject`. Present only for id-shaped keys; a status or a count in the
   * subject has no entry here and reads as itself.
   */
  subject_labels: Record<string, string>;
  detail: string;
  status: string;
  created_at: string | null;
  resolved_at: string | null;
  /**
   * The compensating command, and the input it needs — both built by the same
   * catalog entry the checker wrote the suggestion from. A null `input` means
   * the repair needs a decision the subject cannot supply, so the row names the
   * command without offering to run it.
   */
  suggested_fix: { command: string; input: Record<string, unknown> | null } | null;
  actions: { resolve: ActionPermission; dismiss: ActionPermission };
}

export interface AdminFindingsPayload {
  findings: FindingRow[];
  filters: { status: string | null; invariant: string | null };
  statuses: string[];
  invariants: { id: string; description: string }[];
  counts: Record<string, number>;
  /** the design review §4.36: the nightly pass is also an on-demand admin control. */
  actions: { run_checker: ActionPermission };
}

/* ------------------------------------------ M14: student drill-down --- */

export interface TimelineEvent {
  id: string;
  application_id?: string;
  event_type: string;
  from_status: string | null;
  to_status: string | null;
  from_round: string | null;
  to_round: string | null;
  /** Null means the system did it — an expiry, a cascade, an archival. */
  actor: string | null;
  actor_role: string | null;
  reason: string | null;
  payload: Record<string, unknown>;
  /**
   * The ids in `payload`, resolved on read. Parallel to it, never a
   * replacement: the payload stays the authoritative append-only record and
   * this is what the screen reads out (the design review §4.35).
   */
  payload_labels?: { applied_override_ids?: AppliedOverride[] };
  created_at: string | null;
}

/** One INT-2 grant that influenced the decision this event records. */
export interface AppliedOverride {
  id: string;
  /** Null on all five when the grant itself is no longer there. */
  rule_domain: string | null;
  allow: boolean | null;
  reason: string | null;
  granted_by: string | null;
  granted_at: string | null;
}

export interface StudentRecordPayload {
  enrollment: {
    id: string;
    user_id: string;
    full_name: string;
    email: string;
    role: string;
    is_active: boolean;
    roll_number: string | null;
    is_current: boolean;
  } | null;
  enrollments: {
    id: string;
    roll_number: string | null;
    is_current: boolean;
    created_at: string | null;
    selected: boolean;
  }[];
  memberships: {
    id: string;
    cycle: { id: string; name: string; kind: string; archived: boolean };
    status: string;
    consented_at: string | null;
    decided_at: string | null;
    decided_by: string | null;
    rejection_reason: string | null;
    outcome_tag: string | null;
    auto_created: boolean;
    actions: {
      set_outcome_tag: ActionPermission;
      remove_membership: ActionPermission;
      restore_membership: ActionPermission;
    };
  }[];
  applications: {
    id: string;
    job_id: string;
    job_title: string;
    company_name: string;
    outcome: string;
    cycle: { id: string; name: string; kind: string; archived: boolean };
    status: string;
    applied_at: string | null;
    resume_url: string;
    current_round: { id: string; name: string; ord: number } | null;
    rounds: { id: string; name: string; ord: number }[];
    round_states: {
      round_id: string;
      round_name: string;
      ord: number;
      result: string;
      attendance: string;
      venue_override: string | null;
      scheduled_at_override: string | null;
    }[];
    events: TimelineEvent[];
    offers: StudentRecordOffer[];
    snapshot_diff: {
      key: string;
      label: string;
      owner: string;
      snapshot: unknown;
      live: unknown;
      /** changed | unchanged | absent — absent is not the same as empty. */
      state: string;
    }[];
    override_domains: string[];
    overrides: SubjectOverride[];
    actions: {
      reinstate: ActionPermission;
      force_transition: ActionPermission;
      grant_override: ActionPermission;
    };
  }[];
  offers: StudentRecordOffer[];
  external_offers: {
    id: string;
    company_name: string;
    outcome: string;
    source: string;
    status: string;
    ctc_lpa: unknown;
    stipend_month: unknown;
    offered_on: string | null;
    responded_on: string | null;
    attached_cycle_id: string | null;
    attached_cycle_name: string | null;
    source_application_id: string | null;
    notes: string | null;
    created_by: string | null;
    created_at: string | null;
  }[];
  discipline: {
    strikes: {
      id: string;
      reason: string;
      source: string;
      is_active: boolean;
      awarded_by: string | null;
      created_at: string | null;
      consumed_by_penalty_id: string | null;
      /** the design review §4.25: `strikes` records no revoker, so this is audit_log. */
      revocation: {
        actor: string | null;
        at: string | null;
        reason: unknown;
        source: string;
      } | null;
    }[];
    penalties: {
      id: string;
      reasons: string;
      from_strikes: boolean;
      is_active: boolean;
      created_by: string | null;
      created_at: string | null;
      revoked_at: string | null;
      revoked_by: string | null;
    }[];
    revoker_source: { strikes: string; penalties: string };
  };
  audit: {
    id: string;
    action: string;
    subject_type: string | null;
    subject_id: string | null;
    actor: string | null;
    actor_role: string | null;
    details: Record<string, unknown>;
    created_at: string | null;
  }[];
  timeline: TimelineEvent[];
  profile: {
    /** `admin_editable` is INT-1's verdict, not a rule the client re-derives. */
    fields: { key: string; label: string; owner: string; admin_editable: boolean }[];
    live: Record<string, unknown>;
    taxonomies: Record<string, TaxonomyRef[]>;
    program_branches: { program_id: string; branch_id: string }[];
  };
  override_domains: string[];
  overrides: SubjectOverride[];
  override_targets: {
    cycle_domains: string[];
    job_domains: string[];
    cycles: { id: string; name: string; kind: string }[];
    jobs: {
      id: string;
      title: string;
      company_name: string;
      cycle: { id: string; name: string };
    }[];
  };
  actions: {
    edit_profile: ActionPermission;
    grant_enrollment_override: ActionPermission;
  };
}

export interface StudentRecordOffer {
  id: string;
  application_id: string;
  job_title: string;
  company_name: string;
  outcome: string;
  cycle_id: string;
  cycle_name: string;
  extended_at: string | null;
  deadline_at: string | null;
  response: string | null;
  responded_at: string | null;
  terminated_at: string | null;
  termination_kind: string | null;
  termination_reason: string | null;
  terminated_by: string | null;
}

export function payload<T>(data: unknown): T {
  return data as T;
}

/* --------------------------------------------------------------------------
 * M15 — analytics (ANA-1..4).
 *
 * These mirror the ANA-1 vocabulary exactly, including the shapes that exist to
 * stop a number being misread: a rate carries its own numerator and denominator
 * so nothing here recomputes it, a compensation block carries the coverage that
 * qualifies it, and `placed` nests two levels that each sum to their parent.
 * ------------------------------------------------------------------------ */

/** A rate that ships its arithmetic. `ratio` is null over an empty denominator. */
export interface Rate {
  numerator: number;
  denominator: number;
  ratio: string | null;
}

/** ANA-1's placed figure: on-portal versus external, external broken out. */
export interface PlacedFigure {
  total: number;
  split: { portal: number; external: number };
  external_sources: { ppo: number; off_campus: number; other: number };
  discarded_acceptances: number;
}

/** Compensation for one outcome, never pooled across units. */
export interface CompensationBlock {
  unit: string;
  placed: number;
  /** Placed students with a recorded figure — the median's honest denominator. */
  covered: number;
  mean: string | null;
  median: string | null;
  min: string | null;
  max: string | null;
}

export interface Funnel {
  registered: number;
  registered_seeking: number;
  applied: number;
  offered: number;
  placed: PlacedFigure;
  placement_rate: Rate;
  placement_rate_seeking: Rate;
}

export interface BreakdownRow {
  key: string;
  label: string;
  registered: number;
  registered_seeking: number;
  applied: number;
  offered: number;
  placed: number;
  placed_split: Record<string, number>;
  placement_rate: Rate;
  placement_rate_seeking: Rate;
}

export interface SectorRow {
  key: string;
  label: string;
  applied: number;
  offered: number;
  placed: number;
  placed_split: Record<string, number>;
}

export type Compensation = Record<"placement" | "internship", CompensationBlock>;

/** One selectable export column, offered by the screen the picker sits on. */
export interface ExportColumnOption {
  key: string;
  label: string;
  family: string;
}

export interface CycleAnalyticsPayload {
  cycle: { id: string; name: string; kind: string; archived: boolean };
  funnel: Funnel;
  compensation: Compensation;
  breakdowns: {
    program: BreakdownRow[];
    branch: BreakdownRow[];
    gender: BreakdownRow[];
    sector: SectorRow[];
  };
  top_companies: { company_id: string; name: string; placed: number }[];
  timeline: { day: string; applications: number; offers: number; acceptances: number }[];
  discipline: { active_strikes: number; active_penalties: number };
  pending_approvals: number;
  /** the design review §4.22: the picker offers exactly what request_export accepts. */
  export_columns: ExportColumnOption[];
}

export interface CannedReport {
  provisional: boolean;
  note: string;
  columns: { key: string; label: string }[];
  rows: Record<string, unknown>[];
  total: Record<string, unknown>;
}

export interface PortalAnalyticsPayload {
  years: (Funnel & { year: string; cycle_count: number; compensation: Compensation })[];
  overall: Funnel;
  participation: { cycle_id: string; name: string; kind: string; starts_on: string | null }[];
  program_mix: BreakdownRow[];
  sector_mix: SectorRow[];
  portal_wide_placed: PlacedFigure;
  canned_report: CannedReport;
}

export interface RoundRow {
  round_id: string;
  name: string;
  ord: number;
  entered: number;
  advanced: number;
  eliminated: number;
  waitlisted: number;
  pending: number;
  absent: number;
  /** RND-3 treats excused differently from absent, so it is never folded in. */
  excused: number;
  present: number;
  conversion: Rate;
  closed_passages: number;
  median_hours: string | null;
}

export interface JobAnalyticsPayload {
  job: {
    id: string;
    title: string;
    outcome: string;
    published: boolean;
    cancelled: boolean;
    company: { id: string; name: string };
    cycle: { id: string; name: string; kind: string };
  };
  /** "pipeline" for a dedicated cycle, "open" where outcomes are recorded direct. */
  shape: "pipeline" | "open";
  funnel: { applied: number; offered: number; accepted: number; offer_conversion: Rate };
  statuses: Record<string, number>;
  compensation: Compensation;
  rounds: RoundRow[];
  export_columns: ExportColumnOption[];
}

export interface CompanyAnalytics {
  company: { id: string; name: string; is_active: boolean; sector: string | null };
  totals: {
    jobs: number;
    cancelled_jobs: number;
    applicants: number;
    offered: number;
    placed: PlacedFigure;
    offers_extended: number;
    offers_accepted: number;
    acceptance_rate: Rate;
  };
  jobs: {
    id: string;
    title: string;
    outcome: string;
    published: boolean;
    cancelled: boolean;
    cycle_id: string;
    cycle_name: string;
  }[];
  hires_by_program: { key: string; label: string; count: number }[];
  hires_by_branch: { key: string; label: string; count: number }[];
  compensation_history: {
    cycle_id: string;
    cycle_name: string;
    placed: PlacedFigure;
    compensation: Compensation;
  }[];
  external_offers: { status: string; source: string; total: number }[];
}
