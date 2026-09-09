import type { CommandName, ScreenId } from "./client";

/**
 * Which screens a command can invalidate — LLD §16: "mutations invalidate their
 * screen key(s) listed in a `SCREEN_DEPS` map".
 *
 * The map is deliberately coarse: over-invalidating costs one refetch, while
 * under-invalidating shows the user stale data after their own write. Entries
 * are typed against the generated client, so a renamed command or screen is a
 * compile error rather than a silent no-op.
 */
export const SCREEN_DEPS: Record<CommandName, readonly ScreenId[]> = {
  // Analytics / exports. An export request writes an export_jobs row and
  // nothing a screen renders, so it invalidates nothing: the file is fetched
  // from its own route, not from a screen.
  request_export: [],
  // Identity / session
  logout: [],
  deactivate_user: ["admin/users"],
  set_user_role: ["admin/users"],

  // Profiles
  declare_profile: ["me/profile", "cycles/joinable"],
  // An admin field is the student's to supply while it is still blank, and the
  // join checklist reads exactly those fields — so filling one can make a cycle
  // joinable (the design review §4.33).
  update_student_fields: ["me/profile", "cycles/joinable"],
  // An admin correction changes the record staff read it from, the student's
  // own form, and the join checklist that gates every cycle they are not yet
  // in — clearing a required field is exactly what makes one unjoinable again.
  admin_update_profile: [
    "me/profile",
    "cycles/joinable",
    "staff/student/{enrollment_id}",
  ],
  start_new_enrollment: ["me/profile", "cycles/joinable", "admin/users"],
  add_resume: ["me/profile"],
  update_resume: ["me/profile"],
  delete_resume: ["me/profile"],
  set_default_resume: ["me/profile"],
  // The tag shows on the two screens that render a membership row, and feeds
  // ANA-3's seeking-adjusted denominator on the cycle's analytics.
  set_outcome_tag: [
    "staff/cycle/{id}/approvals",
    "staff/student/{enrollment_id}",
    "staff/cycle/{id}/analytics",
  ],

  // Bulk upsert staging
  bulk_upsert_profiles: ["admin/bulk-upsert"],
  delete_staged_row: ["admin/bulk-upsert"],

  // Taxonomies & settings
  upsert_taxonomy_item: ["admin/taxonomies", "staff/taxonomies", "me/profile"],
  set_setting: ["admin/settings", "admin/discipline"],
  update_template: ["admin/templates"],
  resend_notification: ["admin/templates"],

  // M14 administrative registers. Overrides can alter gate verdicts wherever a
  // student or coordinator sees them; finding verdicts only close register rows.
  create_override: [
    "admin/overrides",
    "cycle/{id}/jobs",
    "job/{id}",
    "me/applications",
    "me/dashboard",
    "staff/job/{id}/board",
    "staff/job/{id}/offers",
    "staff/student/{enrollment_id}",
  ],
  deactivate_override: [
    "admin/overrides",
    "cycle/{id}/jobs",
    "job/{id}",
    "me/applications",
    "me/dashboard",
    "staff/job/{id}/board",
    "staff/job/{id}/offers",
    "staff/student/{enrollment_id}",
  ],
  resolve_finding: ["admin/findings"],
  dismiss_finding: ["admin/findings"],
  run_consistency_checker: ["admin/findings"],

  // Companies & contacts
  create_company: ["staff/companies"],
  update_company: ["staff/companies", "staff/company/{id}"],
  activate_company: ["staff/companies", "staff/company/{id}"],
  deactivate_company: ["staff/companies", "staff/company/{id}"],
  merge_companies: ["staff/companies", "staff/company/{id}"],
  contact_create: ["staff/company/{id}"],
  contact_update: ["staff/company/{id}"],
  contact_delete: ["staff/company/{id}"],

  // Cycles
  create_cycle: ["staff/cycles", "cycles/joinable"],
  update_cycle: ["staff/cycles", "staff/cycle/{id}", "cycles/joinable"],
  update_cycle_policy: ["staff/cycle/{id}", "cycles/joinable"],
  set_cycle_active: ["staff/cycles", "staff/cycle/{id}", "cycles/joinable"],
  archive_cycle: ["staff/cycles", "staff/cycle/{id}", "cycles/joinable", "me/profile"],
  assign_coordinator: ["staff/cycle/{id}"],
  remove_coordinator: ["staff/cycle/{id}"],

  // Memberships
  join_cycle: ["cycles/joinable", "staff/cycle/{id}/approvals", "me/profile"],
  rerequest_membership: ["cycles/joinable", "staff/cycle/{id}/approvals"],
  withdraw_membership: ["cycles/joinable", "staff/cycle/{id}", "me/profile"],
  approve_memberships: ["staff/cycle/{id}/approvals", "staff/cycle/{id}"],
  reject_membership: ["staff/cycle/{id}/approvals", "staff/cycle/{id}"],
  remove_membership: ["staff/cycle/{id}", "staff/cycle/{id}/approvals"],
  restore_membership: ["staff/cycle/{id}", "staff/cycle/{id}/approvals"],

  // Jobs and the builder. A job's own screens are the staff list and the
  // builder; the two student screens go stale too, because a job's visibility
  // and its eligibility verdict are both read straight off the job row.
  create_job: ["staff/cycle/{id}/jobs"],
  update_job_basics: [
    "staff/cycle/{id}/jobs",
    "staff/job/{id}/builder",
    "cycle/{id}/jobs",
    "job/{id}",
  ],
  publish_job: [
    "staff/cycle/{id}/jobs",
    "staff/job/{id}/builder",
    "cycle/{id}/jobs",
    "job/{id}",
  ],
  unpublish_job: [
    "staff/cycle/{id}/jobs",
    "staff/job/{id}/builder",
    "cycle/{id}/jobs",
    "job/{id}",
  ],
  // The rule decides every student verdict, so both student screens go with it.
  update_job_eligibility: [
    "staff/job/{id}/builder",
    "cycle/{id}/jobs",
    "job/{id}",
  ],
  // Applications
  // The card the student applied from, and the job page they applied on, both
  // carry an application chip and a verdict that this write has just changed.
  apply: [
    "cycle/{id}/jobs",
    "job/{id}",
    "staff/cycle/{id}/jobs",
    "me/applications",
    "staff/job/{id}/board",
  ],

  // Round operations
  advance_applications: ["staff/job/{id}/board", "me/applications"],
  eliminate_applications: ["staff/job/{id}/board", "me/applications"],
  waitlist_applications: ["staff/job/{id}/board", "me/applications"],
  promote_waitlisted: ["staff/job/{id}/board", "me/applications"],
  // Attendance and slots are board facts; the student's own screen does not
  // render them yet, so the board is the only key that goes stale.
  mark_attendance: ["staff/job/{id}/board"],
  bulk_mark_present: ["staff/job/{id}/board"],
  bulk_mark_absent: ["staff/job/{id}/board"],
  assign_venue_timing: ["staff/job/{id}/board"],

  // Offers change both the application timeline and the live outcome/cap
  // verdict shown on every other job card. M12f adds the dedicated offer
  // screens to these entries when those screen IDs enter the registry.
  extend_offers: [
    "staff/job/{id}/board",
    "staff/job/{id}/offers",
    "me/applications",
    "me/dashboard",
  ],
  accept_offer: [
    "staff/job/{id}/board",
    "me/applications",
    "cycle/{id}/jobs",
    "job/{id}",
    "staff/job/{id}/offers",
    "me/dashboard",
  ],
  decline_offer: [
    "staff/job/{id}/board",
    "staff/job/{id}/offers",
    "me/applications",
    "me/dashboard",
  ],
  terminate_offer: [
    "staff/job/{id}/board",
    "me/applications",
    "cycle/{id}/jobs",
    "job/{id}",
    "admin/discipline",
    "staff/job/{id}/offers",
    "me/dashboard",
  ],
  re_extend_offer: [
    "staff/job/{id}/board",
    "staff/job/{id}/offers",
    "me/applications",
    "me/dashboard",
  ],
  record_open_outcome: [
    "staff/job/{id}/board",
    "me/applications",
    "cycle/{id}/jobs",
    "job/{id}",
  ],
  create_external_offer: [
    "staff/external",
    "staff/cycle/{id}/external",
    "me/dashboard",
    "me/applications",
    "cycle/{id}/jobs",
    "job/{id}",
  ],
  update_external_offer: [
    "staff/external",
    "staff/cycle/{id}/external",
    "staff/job/{id}/offers",
    "me/dashboard",
    "me/applications",
    "cycle/{id}/jobs",
    "job/{id}",
  ],
  delete_external_offer: [
    "staff/external",
    "staff/cycle/{id}/external",
    "staff/job/{id}/offers",
    "me/dashboard",
    "me/applications",
    "cycle/{id}/jobs",
    "job/{id}",
  ],
  attach_external_offer: [
    "staff/external",
    "staff/cycle/{id}/external",
    "staff/cycle/{id}",
    "me/dashboard",
  ],
  attach_external_offers: [
    "staff/external",
    "staff/cycle/{id}/external",
    "staff/cycle/{id}",
    "me/dashboard",
  ],
  detach_external_offer: [
    "staff/external",
    "staff/cycle/{id}/external",
    "staff/cycle/{id}",
    "me/dashboard",
  ],
  // Finalization closes the round, settles attendance failures, and can award
  // strikes/penalties, so both read models move together.
  finalize_round: ["staff/job/{id}/board", "me/applications", "admin/discipline"],
  edit_application: ["me/applications", "job/{id}", "staff/job/{id}/board"],
  // Withdrawing frees the unique slot, so the job card can offer Apply again.
  withdraw_application: [
    "me/applications",
    "cycle/{id}/jobs",
    "job/{id}",
    "staff/cycle/{id}/jobs",
    "staff/job/{id}/board",
  ],

  upsert_job_rounds: ["staff/job/{id}/builder", "job/{id}", "cycle/{id}/jobs"],
  upsert_job_questions: ["staff/job/{id}/builder", "job/{id}", "cycle/{id}/jobs"],
  // Cancelling unpublishes the job and rejects its applications, so it reaches
  // every screen either side reads.
  cancel_job: [
    "staff/cycle/{id}/jobs",
    "staff/job/{id}/builder",
    "cycle/{id}/jobs",
    "job/{id}",
  ],
  // The preset is builder-local: no student screen shows it.
  save_export_preset: ["staff/job/{id}/builder", "staff/job/{id}/board"],

  // M14 interventions change both the pipeline and the dispute record.
  reinstate_application: [
    "staff/student/{enrollment_id}",
    "staff/job/{id}/board",
    "me/applications",
  ],
  force_transition: [
    "staff/student/{enrollment_id}",
    "staff/job/{id}/board",
    "me/applications",
  ],

  // Enrollment-scoped discipline. The screen includes both roster totals and
  // the selected student's full record, so every write invalidates both keys.
  award_strike: ["admin/discipline", "staff/student/{enrollment_id}"],
  revoke_strike: ["admin/discipline", "staff/student/{enrollment_id}"],
  award_penalty: ["admin/discipline", "staff/student/{enrollment_id}"],
  revoke_penalty: ["admin/discipline", "staff/student/{enrollment_id}"],
};

/** Screens to invalidate after `name` succeeds. Unknown commands invalidate nothing. */
export function screenDeps(name: CommandName): readonly ScreenId[] {
  return SCREEN_DEPS[name] ?? [];
}
