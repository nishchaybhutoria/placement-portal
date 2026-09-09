/**
 * Mirror of the reason codes in `backend/app/core/errors.py`.
 *
 * The backend already sends a `human` string with every reason; this table is
 * the frontend's own copy, used when the UI wants to say something more
 * specific than the API's generic phrasing (inline field errors, recovery
 * hints, empty states). It exists mainly so the two sides can be proven equal:
 * `src/lib/reasons.test.ts` parses the Python module and asserts the code sets
 * match exactly, so a backend code added without a frontend entry fails CI.
 *
 * Keep the keys in the same order as the Python module.
 */
export const REASONS = {
  not_eligible: "You do not meet the eligibility rules for this job.",
  deadline_passed: "The deadline for this action has passed.",
  duplicate_application: "You have already applied to this job.",
  penalty_active: "An active penalty blocks this action.",
  outcome_gate_placement: "Your placement outcome blocks further applications.",
  outcome_gate_internship: "Your internship outcome blocks further applications.",
  offer_cap_reached: "The offer cap for this cycle has been reached.",
  membership_not_active: "Your membership in this cycle is not active.",
  job_not_found: "No such job.",
  job_not_open: "This job is not open for applications.",
  job_unpublished: "This job has not been published.",
  job_cancelled: "This job has been cancelled.",
  cycle_archived: "This cycle is archived and no longer accepts changes.",
  blocked_by_override: "A staff override blocks this action.",
  stale_view: "The data changed since this page loaded. Reload and try again.",
  window_closed: "The window for this action is closed.",
  not_offered: "There is no live offer to act on.",
  offer_terminated: "This offer has been terminated.",
  invalid_transition: "That status change is not allowed from the current state.",
  unmatched_identifier: "No record matched this identifier.",
  application_not_found: "You have no application to this job.",
  application_not_editable: "This application can no longer be changed.",
  answer_required: "This question must be answered.",
  answer_invalid: "That answer is not valid for this question.",
  unknown_question: "This form has changed. Reload it and answer again.",
  resume_required: "Choose a resume to apply with.",
  profile_incomplete: "Complete your profile before continuing.",
  join_rule_failed: "You do not meet this cycle's join rules.",
  idempotency_conflict: "This request was already submitted with different input.",
  invalid_request: "The request was not valid.",
  outside_allowed_domain: "That email address is outside the allowed domain.",
  inactive_user: "This account is inactive.",
  session_effect_idempotency: "This sign-in step was already completed.",
  oauth_state_invalid: "Sign-in failed a security check. Start again.",
  oauth_state_expired: "The sign-in attempt expired. Start again.",
  last_active_admin: "The last active administrator cannot be removed.",
  self_admin_mutation: "You cannot change your own administrator access.",
  user_not_found: "No such user.",
  oauth_claims_invalid: "The identity provider returned an unusable profile.",
  oauth_provider_error: "The identity provider returned an error.",
  taxonomy_item_not_found: "No such taxonomy item.",
  taxonomy_name_conflict: "Another item already uses this name.",
  enrollment_not_found: "No such enrollment.",
  profile_already_declared: "This profile has already been declared.",
  profile_not_declared: "Declare your profile before continuing.",
  field_not_editable: "This field can no longer be edited.",
  invalid_field_value: "That value is not valid for this field.",
  roll_number_taken: "Another student already uses this roll number.",
  roll_mismatch: "The roll number does not match this enrollment.",
  program_branch_mismatch: "That branch does not belong to the selected program.",
  unknown_taxonomy_value: "That value is not in the taxonomy.",
  invalid_drive_url: "That is not a valid Google Drive link.",
  resume_not_found: "No such resume.",
  last_resume: "Your last remaining resume cannot be deleted.",
  duplicate_row: "This row duplicates another in the same upload.",
  staged_row_not_found: "No such staged row.",
  staged_row_already_applied: "This staged row has already been applied.",
  unparsable_upload: "The uploaded file could not be read.",
  company_not_found: "No such company.",
  company_name_conflict: "Another company already uses this name.",
  company_name_conflict_inactive: "An inactive company already uses this name.",
  company_inactive: "This company is inactive.",
  contact_not_found: "No such contact.",
  contact_email_conflict: "Another contact already uses this email address.",
  merge_into_self: "A record cannot be merged into itself.",
  cycle_not_found: "No such cycle.",
  cycle_name_conflict: "Another cycle already uses this name.",
  cycle_inactive: "This cycle is not active.",
  registration_closed: "Registration for this cycle is closed.",
  coordinator_not_found: "No such coordinator.",
  coordinator_already_assigned: "This coordinator is already assigned to the cycle.",
  membership_not_found: "No such membership.",
  membership_exists: "A membership already exists for this student and cycle.",
  consent_required: "Consent is required before this action.",
  round_already_finalized: "This round has already been finalized.",
  strike_not_found: "No such strike.",
  strike_already_revoked: "This strike has already been revoked.",
  penalty_not_found: "No such penalty.",
  penalty_already_revoked: "This penalty has already been revoked.",
  override_not_found: "No such override.",
  override_already_inactive: "This override has already been deactivated.",
  round_not_found: "No such round.",
  finding_not_found: "No such consistency finding.",
  finding_not_open: "This consistency finding has already been closed.",
  unknown_export_column:
    "That column is not available for this export. Pick again from the list.",
  export_not_found: "That export no longer exists.",
  export_not_ready: "This export is still being built. Try again shortly.",
} as const;

export type ReasonCode = keyof typeof REASONS;

export const REASON_CODES = Object.keys(REASONS) as ReasonCode[];

export function isReasonCode(value: string): value is ReasonCode {
  return Object.prototype.hasOwnProperty.call(REASONS, value);
}

/**
 * Prefer the backend's `human` string; fall back to our own copy, then to the
 * raw code. The UI must never render an empty message.
 */
export function reasonText(code: string, human?: string): string {
  if (human) return human;
  if (isReasonCode(code)) return REASONS[code];
  return code;
}
