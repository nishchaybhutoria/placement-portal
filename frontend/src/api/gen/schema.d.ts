/**
 * GENERATED FILE — DO NOT EDIT.
 * Run `pnpm gen` to regenerate from the backend OpenAPI schema.
 * Source: backend/app.main:app (offline)
 */

export interface paths {
    "/api/v1/commands/accept_offer": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Accept Offer */
        post: operations["command_accept_offer_api_v1_commands_accept_offer_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/activate_company": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Activate Company */
        post: operations["command_activate_company_api_v1_commands_activate_company_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/add_resume": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Add Resume */
        post: operations["command_add_resume_api_v1_commands_add_resume_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/admin_update_profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Admin Update Profile */
        post: operations["command_admin_update_profile_api_v1_commands_admin_update_profile_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/advance_applications": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Advance Applications */
        post: operations["command_advance_applications_api_v1_commands_advance_applications_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/apply": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Apply */
        post: operations["command_apply_api_v1_commands_apply_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/approve_memberships": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Approve Memberships */
        post: operations["command_approve_memberships_api_v1_commands_approve_memberships_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/archive_cycle": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Archive Cycle */
        post: operations["command_archive_cycle_api_v1_commands_archive_cycle_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/assign_coordinator": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Assign Coordinator */
        post: operations["command_assign_coordinator_api_v1_commands_assign_coordinator_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/assign_venue_timing": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Assign Venue Timing */
        post: operations["command_assign_venue_timing_api_v1_commands_assign_venue_timing_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/attach_external_offer": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Attach External Offer */
        post: operations["command_attach_external_offer_api_v1_commands_attach_external_offer_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/attach_external_offers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Attach External Offers */
        post: operations["command_attach_external_offers_api_v1_commands_attach_external_offers_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/award_penalty": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Award Penalty */
        post: operations["command_award_penalty_api_v1_commands_award_penalty_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/award_strike": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Award Strike */
        post: operations["command_award_strike_api_v1_commands_award_strike_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/bulk_mark_absent": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Bulk Mark Absent */
        post: operations["command_bulk_mark_absent_api_v1_commands_bulk_mark_absent_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/bulk_mark_present": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Bulk Mark Present */
        post: operations["command_bulk_mark_present_api_v1_commands_bulk_mark_present_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/bulk_upsert_profiles": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Bulk Upsert Profiles */
        post: operations["command_bulk_upsert_profiles_api_v1_commands_bulk_upsert_profiles_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/cancel_job": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Cancel Job */
        post: operations["command_cancel_job_api_v1_commands_cancel_job_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/contact_create": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Contact Create */
        post: operations["command_contact_create_api_v1_commands_contact_create_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/contact_delete": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Contact Delete */
        post: operations["command_contact_delete_api_v1_commands_contact_delete_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/contact_update": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Contact Update */
        post: operations["command_contact_update_api_v1_commands_contact_update_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/create_company": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Create Company */
        post: operations["command_create_company_api_v1_commands_create_company_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/create_cycle": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Create Cycle */
        post: operations["command_create_cycle_api_v1_commands_create_cycle_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/create_external_offer": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Create External Offer */
        post: operations["command_create_external_offer_api_v1_commands_create_external_offer_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/create_job": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Create Job */
        post: operations["command_create_job_api_v1_commands_create_job_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/create_override": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Create Override */
        post: operations["command_create_override_api_v1_commands_create_override_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/deactivate_company": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Deactivate Company */
        post: operations["command_deactivate_company_api_v1_commands_deactivate_company_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/deactivate_override": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Deactivate Override */
        post: operations["command_deactivate_override_api_v1_commands_deactivate_override_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/deactivate_user": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Deactivate User */
        post: operations["command_deactivate_user_api_v1_commands_deactivate_user_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/declare_profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Declare Profile */
        post: operations["command_declare_profile_api_v1_commands_declare_profile_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/decline_offer": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Decline Offer */
        post: operations["command_decline_offer_api_v1_commands_decline_offer_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/delete_external_offer": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Delete External Offer */
        post: operations["command_delete_external_offer_api_v1_commands_delete_external_offer_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/delete_resume": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Delete Resume */
        post: operations["command_delete_resume_api_v1_commands_delete_resume_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/delete_staged_row": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Delete Staged Row */
        post: operations["command_delete_staged_row_api_v1_commands_delete_staged_row_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/detach_external_offer": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Detach External Offer */
        post: operations["command_detach_external_offer_api_v1_commands_detach_external_offer_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/dismiss_finding": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Dismiss Finding */
        post: operations["command_dismiss_finding_api_v1_commands_dismiss_finding_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/edit_application": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Edit Application */
        post: operations["command_edit_application_api_v1_commands_edit_application_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/eliminate_applications": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Eliminate Applications */
        post: operations["command_eliminate_applications_api_v1_commands_eliminate_applications_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/extend_offers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Extend Offers */
        post: operations["command_extend_offers_api_v1_commands_extend_offers_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/finalize_round": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Finalize Round */
        post: operations["command_finalize_round_api_v1_commands_finalize_round_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/force_transition": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Force Transition */
        post: operations["command_force_transition_api_v1_commands_force_transition_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/join_cycle": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Join Cycle */
        post: operations["command_join_cycle_api_v1_commands_join_cycle_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Logout */
        post: operations["command_logout_api_v1_commands_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/mark_attendance": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Mark Attendance */
        post: operations["command_mark_attendance_api_v1_commands_mark_attendance_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/merge_companies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Merge Companies */
        post: operations["command_merge_companies_api_v1_commands_merge_companies_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/promote_waitlisted": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Promote Waitlisted */
        post: operations["command_promote_waitlisted_api_v1_commands_promote_waitlisted_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/publish_job": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Publish Job */
        post: operations["command_publish_job_api_v1_commands_publish_job_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/re_extend_offer": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Re Extend Offer */
        post: operations["command_re_extend_offer_api_v1_commands_re_extend_offer_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/record_open_outcome": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Record Open Outcome */
        post: operations["command_record_open_outcome_api_v1_commands_record_open_outcome_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/reinstate_application": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Reinstate Application */
        post: operations["command_reinstate_application_api_v1_commands_reinstate_application_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/reject_membership": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Reject Membership */
        post: operations["command_reject_membership_api_v1_commands_reject_membership_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/remove_coordinator": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Remove Coordinator */
        post: operations["command_remove_coordinator_api_v1_commands_remove_coordinator_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/remove_membership": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Remove Membership */
        post: operations["command_remove_membership_api_v1_commands_remove_membership_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/request_export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Request Export */
        post: operations["command_request_export_api_v1_commands_request_export_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/rerequest_membership": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Rerequest Membership */
        post: operations["command_rerequest_membership_api_v1_commands_rerequest_membership_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/resend_notification": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Resend Notification */
        post: operations["command_resend_notification_api_v1_commands_resend_notification_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/resolve_finding": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Resolve Finding */
        post: operations["command_resolve_finding_api_v1_commands_resolve_finding_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/restore_membership": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Restore Membership */
        post: operations["command_restore_membership_api_v1_commands_restore_membership_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/revoke_penalty": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Revoke Penalty */
        post: operations["command_revoke_penalty_api_v1_commands_revoke_penalty_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/revoke_strike": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Revoke Strike */
        post: operations["command_revoke_strike_api_v1_commands_revoke_strike_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/run_consistency_checker": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Run Consistency Checker */
        post: operations["command_run_consistency_checker_api_v1_commands_run_consistency_checker_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/save_export_preset": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Save Export Preset */
        post: operations["command_save_export_preset_api_v1_commands_save_export_preset_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/set_cycle_active": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Set Cycle Active */
        post: operations["command_set_cycle_active_api_v1_commands_set_cycle_active_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/set_default_resume": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Set Default Resume */
        post: operations["command_set_default_resume_api_v1_commands_set_default_resume_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/set_outcome_tag": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Set Outcome Tag */
        post: operations["command_set_outcome_tag_api_v1_commands_set_outcome_tag_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/set_setting": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Set Setting */
        post: operations["command_set_setting_api_v1_commands_set_setting_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/set_user_role": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Set User Role */
        post: operations["command_set_user_role_api_v1_commands_set_user_role_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/start_new_enrollment": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Start New Enrollment */
        post: operations["command_start_new_enrollment_api_v1_commands_start_new_enrollment_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/terminate_offer": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Terminate Offer */
        post: operations["command_terminate_offer_api_v1_commands_terminate_offer_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/unpublish_job": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Unpublish Job */
        post: operations["command_unpublish_job_api_v1_commands_unpublish_job_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/update_company": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Update Company */
        post: operations["command_update_company_api_v1_commands_update_company_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/update_cycle": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Update Cycle */
        post: operations["command_update_cycle_api_v1_commands_update_cycle_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/update_cycle_policy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Update Cycle Policy */
        post: operations["command_update_cycle_policy_api_v1_commands_update_cycle_policy_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/update_external_offer": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Update External Offer */
        post: operations["command_update_external_offer_api_v1_commands_update_external_offer_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/update_job_basics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Update Job Basics */
        post: operations["command_update_job_basics_api_v1_commands_update_job_basics_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/update_job_eligibility": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Update Job Eligibility */
        post: operations["command_update_job_eligibility_api_v1_commands_update_job_eligibility_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/update_resume": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Update Resume */
        post: operations["command_update_resume_api_v1_commands_update_resume_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/update_student_fields": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Update Student Fields */
        post: operations["command_update_student_fields_api_v1_commands_update_student_fields_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/update_template": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Update Template */
        post: operations["command_update_template_api_v1_commands_update_template_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/upsert_job_questions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Upsert Job Questions */
        post: operations["command_upsert_job_questions_api_v1_commands_upsert_job_questions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/upsert_job_rounds": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Upsert Job Rounds */
        post: operations["command_upsert_job_rounds_api_v1_commands_upsert_job_rounds_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/upsert_taxonomy_item": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Upsert Taxonomy Item */
        post: operations["command_upsert_taxonomy_item_api_v1_commands_upsert_taxonomy_item_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/waitlist_applications": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Waitlist Applications */
        post: operations["command_waitlist_applications_api_v1_commands_waitlist_applications_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/withdraw_application": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Withdraw Application */
        post: operations["command_withdraw_application_api_v1_commands_withdraw_application_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/withdraw_membership": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Command Withdraw Membership */
        post: operations["command_withdraw_membership_api_v1_commands_withdraw_membership_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/exports/{export_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Export Status */
        get: operations["export_status_api_v1_exports__export_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/exports/{export_id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Export Download */
        get: operations["export_download_api_v1_exports__export_id__download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/admin/analytics/portal": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Portal Analytics Screen */
        get: operations["_portal_analytics_screen_api_v1_screens_admin_analytics_portal_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/admin/bulk-upsert": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Admin Bulk Upsert Screen */
        get: operations["_admin_bulk_upsert_screen_api_v1_screens_admin_bulk_upsert_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/admin/discipline": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Admin Discipline Screen */
        get: operations["_admin_discipline_screen_api_v1_screens_admin_discipline_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/admin/findings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Admin Findings Screen */
        get: operations["_admin_findings_screen_api_v1_screens_admin_findings_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/admin/overrides": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Admin Overrides */
        get: operations["screen_admin_overrides_api_v1_screens_admin_overrides_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/admin/settings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Settings Screen */
        get: operations["_settings_screen_api_v1_screens_admin_settings_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/admin/taxonomies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Taxonomies Screen */
        get: operations["_taxonomies_screen_api_v1_screens_admin_taxonomies_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/admin/templates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Templates Screen */
        get: operations["_templates_screen_api_v1_screens_admin_templates_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/admin/users": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Admin Users */
        get: operations["screen_admin_users_api_v1_screens_admin_users_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/cycle/{id}/jobs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Cycle {Id} Jobs */
        get: operations["screen_cycle__id__jobs_api_v1_screens_cycle__id__jobs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/cycles/joinable": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Cycles Joinable */
        get: operations["screen_cycles_joinable_api_v1_screens_cycles_joinable_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/job/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Job {Id} */
        get: operations["screen_job__id__api_v1_screens_job__id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/me/applications": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Me Applications */
        get: operations["screen_me_applications_api_v1_screens_me_applications_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/me/dashboard": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Me Dashboard */
        get: operations["screen_me_dashboard_api_v1_screens_me_dashboard_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/me/notifications": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Me Notifications */
        get: operations["screen_me_notifications_api_v1_screens_me_notifications_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/me/profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Me Profile */
        get: operations["screen_me_profile_api_v1_screens_me_profile_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/staff/companies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Companies Screen */
        get: operations["_companies_screen_api_v1_screens_staff_companies_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/staff/company/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Staff Company {Id} */
        get: operations["screen_staff_company__id__api_v1_screens_staff_company__id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/staff/cycle/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Staff Cycle {Id} */
        get: operations["screen_staff_cycle__id__api_v1_screens_staff_cycle__id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/staff/cycle/{id}/analytics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Staff Cycle {Id} Analytics */
        get: operations["screen_staff_cycle__id__analytics_api_v1_screens_staff_cycle__id__analytics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/staff/cycle/{id}/approvals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Staff Cycle {Id} Approvals */
        get: operations["screen_staff_cycle__id__approvals_api_v1_screens_staff_cycle__id__approvals_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/staff/cycle/{id}/external": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Staff Cycle {Id} External */
        get: operations["screen_staff_cycle__id__external_api_v1_screens_staff_cycle__id__external_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/staff/cycle/{id}/jobs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Staff Cycle {Id} Jobs */
        get: operations["screen_staff_cycle__id__jobs_api_v1_screens_staff_cycle__id__jobs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/staff/cycles": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Staff Cycles */
        get: operations["screen_staff_cycles_api_v1_screens_staff_cycles_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/staff/external": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Staff External Screen */
        get: operations["_staff_external_screen_api_v1_screens_staff_external_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/staff/job/{id}/analytics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Staff Job {Id} Analytics */
        get: operations["screen_staff_job__id__analytics_api_v1_screens_staff_job__id__analytics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/staff/job/{id}/board": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Staff Job {Id} Board */
        get: operations["screen_staff_job__id__board_api_v1_screens_staff_job__id__board_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/staff/job/{id}/builder": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Staff Job {Id} Builder */
        get: operations["screen_staff_job__id__builder_api_v1_screens_staff_job__id__builder_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/staff/job/{id}/offers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Staff Job {Id} Offers */
        get: operations["screen_staff_job__id__offers_api_v1_screens_staff_job__id__offers_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/staff/student/{enrollment_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen Staff Student {Enrollment Id} */
        get: operations["screen_staff_student__enrollment_id__api_v1_screens_staff_student__enrollment_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screens/staff/taxonomies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Taxonomies Screen */
        get: operations["_taxonomies_screen_api_v1_screens_staff_taxonomies_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/uploads/profile-rows": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Parse Profile Upload */
        post: operations["parse_profile_upload_api_v1_uploads_profile_rows_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/uploads/venue-rows": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Parse Venue Upload */
        post: operations["parse_venue_upload_api_v1_uploads_venue_rows_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/google/callback": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Google Callback */
        get: operations["google_callback_auth_google_callback_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/google/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Google Login */
        get: operations["google_login_auth_google_login_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/healthz": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Healthz */
        get: operations["healthz_healthz_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Me */
        get: operations["me_me_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/readyz": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Readyz */
        get: operations["readyz_readyz_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AcceptOfferCommandPreview */
        AcceptOfferCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["OfferActionSummary"];
        };
        /** AcceptOfferCommandRequest */
        AcceptOfferCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["OfferResponseInput"];
        };
        /** AcceptOfferCommandResult */
        AcceptOfferCommandResult: {
            summary: components["schemas"]["OfferActionSummary"];
        };
        /** ActivateCompanyCommandPreview */
        ActivateCompanyCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["CompanySummary"];
        };
        /** ActivateCompanyCommandRequest */
        ActivateCompanyCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["CompanyIdInput"];
        };
        /** ActivateCompanyCommandResult */
        ActivateCompanyCommandResult: {
            summary: components["schemas"]["CompanySummary"];
        };
        /** AddResumeCommandPreview */
        AddResumeCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ResumeSummary"];
        };
        /** AddResumeCommandRequest */
        AddResumeCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["AddResumeInput"];
        };
        /** AddResumeCommandResult */
        AddResumeCommandResult: {
            summary: components["schemas"]["ResumeSummary"];
        };
        /** AddResumeInput */
        AddResumeInput: {
            /** Drive Url */
            drive_url: string;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /**
             * Is Default
             * @default false
             */
            is_default: boolean;
            /** Label */
            label: string;
        };
        /** AdminUpdateProfileCommandPreview */
        AdminUpdateProfileCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["UpdateProfileSummary"];
        };
        /** AdminUpdateProfileCommandRequest */
        AdminUpdateProfileCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["AdminUpdateProfileInput"];
        };
        /** AdminUpdateProfileCommandResult */
        AdminUpdateProfileCommandResult: {
            summary: components["schemas"]["UpdateProfileSummary"];
        };
        /** AdminUpdateProfileInput */
        AdminUpdateProfileInput: {
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /** Fields */
            fields: {
                [key: string]: unknown;
            };
        };
        /** AdvanceApplicationsCommandPreview */
        AdvanceApplicationsCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["BulkRoundSummary"];
        };
        /** AdvanceApplicationsCommandRequest */
        AdvanceApplicationsCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["BulkRoundInput"];
        };
        /** AdvanceApplicationsCommandResult */
        AdvanceApplicationsCommandResult: {
            summary: components["schemas"]["BulkRoundSummary"];
        };
        /** AnswerInput */
        AnswerInput: {
            /**
             * Question Id
             * Format: uuid
             */
            question_id: string;
            /** Value */
            value?: unknown;
        };
        /**
         * ApplicationStatus
         * @enum {string}
         */
        ApplicationStatus: "in_progress" | "pending_offer" | "offered" | "accepted" | "declined" | "rejected" | "withdrawn" | "auto_withdrawn" | "offer_terminated";
        /** ApplicationSummary */
        ApplicationSummary: {
            /** Answer Count */
            answer_count: number;
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            /** Current Round Id */
            current_round_id: string | null;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Resume Url */
            resume_url: string;
            status: components["schemas"]["ApplicationStatus"];
        };
        /** ApplyCommandPreview */
        ApplyCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ApplicationSummary"];
        };
        /** ApplyCommandRequest */
        ApplyCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["ApplyInput"];
        };
        /** ApplyCommandResult */
        ApplyCommandResult: {
            summary: components["schemas"]["ApplicationSummary"];
        };
        /** ApplyInput */
        ApplyInput: {
            /**
             * Answers
             * @default []
             */
            answers: components["schemas"]["AnswerInput"][];
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Resume Id */
            resume_id?: string | null;
            /** Resume Url */
            resume_url?: string | null;
        };
        /** ApproveMembershipsCommandPreview */
        ApproveMembershipsCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["BulkMembershipSummary"];
        };
        /** ApproveMembershipsCommandRequest */
        ApproveMembershipsCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["ApproveMembershipsInput"];
        };
        /** ApproveMembershipsCommandResult */
        ApproveMembershipsCommandResult: {
            summary: components["schemas"]["BulkMembershipSummary"];
        };
        /** ApproveMembershipsInput */
        ApproveMembershipsInput: {
            /** Batch Key */
            batch_key: string;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Rows */
            rows: {
                [key: string]: string;
            }[];
        };
        /** ArchiveCycleCommandPreview */
        ArchiveCycleCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ArchiveCycleSummary"];
        };
        /** ArchiveCycleCommandRequest */
        ArchiveCycleCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["ArchiveCycleInput"];
        };
        /** ArchiveCycleCommandResult */
        ArchiveCycleCommandResult: {
            summary: components["schemas"]["ArchiveCycleSummary"];
        };
        /** ArchiveCycleInput */
        ArchiveCycleInput: {
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
        };
        /** ArchiveCycleSummary */
        ArchiveCycleSummary: {
            /** Archived At */
            archived_at: string | null;
            /** Auto Withdrawn */
            auto_withdrawn: {
                [key: string]: unknown;
            }[];
            /** Changed */
            changed: boolean;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Untouched */
            untouched: {
                [key: string]: unknown;
            }[];
        };
        /** AssignCoordinatorCommandPreview */
        AssignCoordinatorCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["CoordinatorSummary"];
        };
        /** AssignCoordinatorCommandRequest */
        AssignCoordinatorCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["CoordinatorInput"];
        };
        /** AssignCoordinatorCommandResult */
        AssignCoordinatorCommandResult: {
            summary: components["schemas"]["CoordinatorSummary"];
        };
        /** AssignVenueTimingCommandPreview */
        AssignVenueTimingCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["AssignVenueTimingSummary"];
        };
        /** AssignVenueTimingCommandRequest */
        AssignVenueTimingCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["AssignVenueTimingInput"];
        };
        /** AssignVenueTimingCommandResult */
        AssignVenueTimingCommandResult: {
            summary: components["schemas"]["AssignVenueTimingSummary"];
        };
        /**
         * AssignVenueTimingInput
         * @description A venue, a time, or both, for each named applicant.
         */
        AssignVenueTimingInput: {
            /** Batch Key */
            batch_key: string;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /**
             * Round Id
             * Format: uuid
             */
            round_id: string;
            /** Rows */
            rows: {
                [key: string]: string;
            }[];
        };
        /** AssignVenueTimingSummary */
        AssignVenueTimingSummary: {
            /** Rows */
            rows: {
                [key: string]: unknown;
            }[];
        };
        /** AttachExternalOfferCommandPreview */
        AttachExternalOfferCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["AttachmentSummary"];
        };
        /** AttachExternalOfferCommandRequest */
        AttachExternalOfferCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["AttachExternalOfferInput"];
        };
        /** AttachExternalOfferCommandResult */
        AttachExternalOfferCommandResult: {
            summary: components["schemas"]["AttachmentSummary"];
        };
        /** AttachExternalOfferInput */
        AttachExternalOfferInput: {
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Expected Attached Cycle Id */
            expected_attached_cycle_id?: string | null;
            /**
             * External Offer Id
             * Format: uuid
             */
            external_offer_id: string;
            /** Reason */
            reason: string;
        };
        /** AttachExternalOffersCommandPreview */
        AttachExternalOffersCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["BulkAttachmentSummary"];
        };
        /** AttachExternalOffersCommandRequest */
        AttachExternalOffersCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["AttachExternalOffersInput"];
        };
        /** AttachExternalOffersCommandResult */
        AttachExternalOffersCommandResult: {
            summary: components["schemas"]["BulkAttachmentSummary"];
        };
        /** AttachExternalOffersInput */
        AttachExternalOffersInput: {
            /** Batch Key */
            batch_key: string;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Reason */
            reason: string;
            /** Rows */
            rows: components["schemas"]["AttachRow"][];
        };
        /** AttachmentSummary */
        AttachmentSummary: {
            /** Applied Override Ids */
            applied_override_ids: string[];
            /** Attached Cycle Id */
            attached_cycle_id: string | null;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /**
             * External Offer Id
             * Format: uuid
             */
            external_offer_id: string;
            /** Membership Auto Created */
            membership_auto_created: boolean;
            /** Membership Left In Place */
            membership_left_in_place: boolean;
            status: components["schemas"]["ExternalStatus"];
        };
        /** AttachRow */
        AttachRow: {
            /** Expected Attached Cycle Id */
            expected_attached_cycle_id?: string | null;
            /**
             * External Offer Id
             * Format: uuid
             */
            external_offer_id: string;
        };
        /**
         * Attendance
         * @enum {string}
         */
        Attendance: "pending" | "present" | "absent" | "excused";
        /** AwardPenaltyCommandPreview */
        AwardPenaltyCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["PenaltySummary"];
        };
        /** AwardPenaltyCommandRequest */
        AwardPenaltyCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["AwardPenaltyInput"];
        };
        /** AwardPenaltyCommandResult */
        AwardPenaltyCommandResult: {
            summary: components["schemas"]["PenaltySummary"];
        };
        /** AwardPenaltyInput */
        AwardPenaltyInput: {
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /** Reasons */
            reasons: string;
        };
        /** AwardStrikeCommandPreview */
        AwardStrikeCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["StrikeSummary"];
        };
        /** AwardStrikeCommandRequest */
        AwardStrikeCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["AwardStrikeInput"];
        };
        /** AwardStrikeCommandResult */
        AwardStrikeCommandResult: {
            summary: components["schemas"]["StrikeSummary"];
        };
        /** AwardStrikeInput */
        AwardStrikeInput: {
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /** Reason */
            reason: string;
        };
        /** Body_parse_profile_upload_api_v1_uploads_profile_rows_post */
        Body_parse_profile_upload_api_v1_uploads_profile_rows_post: {
            /** File */
            file: string;
        };
        /** Body_parse_venue_upload_api_v1_uploads_venue_rows_post */
        Body_parse_venue_upload_api_v1_uploads_venue_rows_post: {
            /** File */
            file: string;
        };
        /** BulkAttachmentSummary */
        BulkAttachmentSummary: {
            /** Rows */
            rows: {
                [key: string]: unknown;
            }[];
        };
        /** BulkMarkAbsentCommandPreview */
        BulkMarkAbsentCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["BulkPresentSummary"];
        };
        /** BulkMarkAbsentCommandRequest */
        BulkMarkAbsentCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["BulkPresentInput"];
        };
        /** BulkMarkAbsentCommandResult */
        BulkMarkAbsentCommandResult: {
            summary: components["schemas"]["BulkPresentSummary"];
        };
        /** BulkMarkPresentCommandPreview */
        BulkMarkPresentCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["BulkPresentSummary"];
        };
        /** BulkMarkPresentCommandRequest */
        BulkMarkPresentCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["BulkPresentInput"];
        };
        /** BulkMarkPresentCommandResult */
        BulkMarkPresentCommandResult: {
            summary: components["schemas"]["BulkPresentSummary"];
        };
        /** BulkMembershipSummary */
        BulkMembershipSummary: {
            /** Rows */
            rows: {
                [key: string]: unknown;
            }[];
        };
        /** BulkOfferSummary */
        BulkOfferSummary: {
            /** Rows */
            rows: {
                [key: string]: unknown;
            }[];
        };
        /** BulkPresentInput */
        BulkPresentInput: {
            /** Batch Key */
            batch_key: string;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /**
             * Round Id
             * Format: uuid
             */
            round_id: string;
            /** Rows */
            rows: {
                [key: string]: string;
            }[];
        };
        /** BulkPresentSummary */
        BulkPresentSummary: {
            /** Rows */
            rows: {
                [key: string]: unknown;
            }[];
        };
        /** BulkProfileRow */
        BulkProfileRow: {
            /**
             * Fields
             * @default {}
             */
            fields: {
                [key: string]: unknown;
            };
            /** Institute Email */
            institute_email: string;
            /** Row Number */
            row_number: number;
        };
        /**
         * BulkRoundInput
         * @description The RND-2 contract: a selection, or pasted identifiers, never both.
         */
        BulkRoundInput: {
            /** Batch Key */
            batch_key: string;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Reason */
            reason?: string | null;
            /** Rows */
            rows: {
                [key: string]: string;
            }[];
        };
        /** BulkRoundSummary */
        BulkRoundSummary: {
            /** Rows */
            rows: {
                [key: string]: unknown;
            }[];
        };
        /** BulkUpsertProfilesCommandPreview */
        BulkUpsertProfilesCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["BulkUpsertProfilesSummary"];
        };
        /** BulkUpsertProfilesCommandRequest */
        BulkUpsertProfilesCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["BulkUpsertProfilesInput"];
        };
        /** BulkUpsertProfilesCommandResult */
        BulkUpsertProfilesCommandResult: {
            summary: components["schemas"]["BulkUpsertProfilesSummary"];
        };
        /** BulkUpsertProfilesInput */
        BulkUpsertProfilesInput: {
            /** Batch Key */
            batch_key: string;
            /** Rows */
            rows: components["schemas"]["BulkProfileRow"][];
        };
        /** BulkUpsertProfilesSummary */
        BulkUpsertProfilesSummary: {
            /** Rows */
            rows: {
                [key: string]: unknown;
            }[];
        };
        /** CancelJobCommandPreview */
        CancelJobCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["CancelJobSummary"];
        };
        /** CancelJobCommandRequest */
        CancelJobCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["CancelJobInput"];
        };
        /** CancelJobCommandResult */
        CancelJobCommandResult: {
            summary: components["schemas"]["CancelJobSummary"];
        };
        /** CancelJobInput */
        CancelJobInput: {
            /** Batch Key */
            batch_key: string;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /**
             * Reason
             * @default The job was cancelled
             */
            reason: string;
            /** Rows */
            rows: {
                [key: string]: string;
            }[];
        };
        /** CancelJobSummary */
        CancelJobSummary: {
            /** Rows */
            rows: {
                [key: string]: unknown;
            }[];
        };
        /** CompanyIdInput */
        CompanyIdInput: {
            /**
             * Company Id
             * Format: uuid
             */
            company_id: string;
        };
        /** CompanySummary */
        CompanySummary: {
            /** Changed */
            changed: boolean;
            /**
             * Company Id
             * Format: uuid
             */
            company_id: string;
            /** Is Active */
            is_active: boolean;
            /** Name */
            name: string;
        };
        /** ConsistencyRunSummary */
        ConsistencyRunSummary: {
            /** By Invariant */
            by_invariant: {
                [key: string]: unknown;
            }[];
            /** Checked Invariants */
            checked_invariants: number;
            /** Findings Auto Resolved */
            findings_auto_resolved: number;
            /** Findings Opened */
            findings_opened: number;
            /** Findings Reopened */
            findings_reopened: number;
            /** Reminder Sends Purged */
            reminder_sends_purged: number;
            /** Sessions Purged */
            sessions_purged: number;
            /** Violations */
            violations: number;
        };
        /** ContactCreateCommandPreview */
        ContactCreateCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ContactSummary"];
        };
        /** ContactCreateCommandRequest */
        ContactCreateCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["ContactCreateInput"];
        };
        /** ContactCreateCommandResult */
        ContactCreateCommandResult: {
            summary: components["schemas"]["ContactSummary"];
        };
        /** ContactCreateInput */
        ContactCreateInput: {
            /**
             * Company Id
             * Format: uuid
             */
            company_id: string;
            /** Designation */
            designation?: string | null;
            /** Email */
            email: string;
            /**
             * Is Primary
             * @default false
             */
            is_primary: boolean;
            /** Name */
            name: string;
            /** Phone */
            phone?: string | null;
        };
        /** ContactDeleteCommandPreview */
        ContactDeleteCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ContactSummary"];
        };
        /** ContactDeleteCommandRequest */
        ContactDeleteCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["ContactIdInput"];
        };
        /** ContactDeleteCommandResult */
        ContactDeleteCommandResult: {
            summary: components["schemas"]["ContactSummary"];
        };
        /** ContactIdInput */
        ContactIdInput: {
            /**
             * Company Id
             * Format: uuid
             */
            company_id: string;
            /**
             * Contact Id
             * Format: uuid
             */
            contact_id: string;
        };
        /** ContactSummary */
        ContactSummary: {
            /** Changed */
            changed: boolean;
            /**
             * Company Id
             * Format: uuid
             */
            company_id: string;
            /**
             * Contact Id
             * Format: uuid
             */
            contact_id: string;
            /** Is Primary */
            is_primary: boolean;
        };
        /** ContactUpdateCommandPreview */
        ContactUpdateCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ContactSummary"];
        };
        /** ContactUpdateCommandRequest */
        ContactUpdateCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["ContactUpdateInput"];
        };
        /** ContactUpdateCommandResult */
        ContactUpdateCommandResult: {
            summary: components["schemas"]["ContactSummary"];
        };
        /** ContactUpdateInput */
        ContactUpdateInput: {
            /**
             * Company Id
             * Format: uuid
             */
            company_id: string;
            /**
             * Contact Id
             * Format: uuid
             */
            contact_id: string;
            /** Designation */
            designation?: string | null;
            /** Email */
            email?: string | null;
            /** Is Primary */
            is_primary?: boolean | null;
            /** Name */
            name?: string | null;
            /** Phone */
            phone?: string | null;
        };
        /** CoordinatorInput */
        CoordinatorInput: {
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
        };
        /** CoordinatorSummary */
        CoordinatorSummary: {
            /** Assigned */
            assigned: boolean;
            /** Changed */
            changed: boolean;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
        };
        /** CreateCompanyCommandPreview */
        CreateCompanyCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["CompanySummary"];
        };
        /** CreateCompanyCommandRequest */
        CreateCompanyCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["CreateCompanyInput"];
        };
        /** CreateCompanyCommandResult */
        CreateCompanyCommandResult: {
            summary: components["schemas"]["CompanySummary"];
        };
        /** CreateCompanyInput */
        CreateCompanyInput: {
            /** Description */
            description?: string | null;
            /** Name */
            name: string;
            /** Sector Id */
            sector_id?: string | null;
            /** Website Url */
            website_url?: string | null;
        };
        /** CreateCycleCommandPreview */
        CreateCycleCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["CycleSummary"];
        };
        /** CreateCycleCommandRequest */
        CreateCycleCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["CreateCycleInput"];
        };
        /** CreateCycleCommandResult */
        CreateCycleCommandResult: {
            summary: components["schemas"]["CycleSummary"];
        };
        /** CreateCycleInput */
        CreateCycleInput: {
            /** Description */
            description?: string | null;
            /** Ends On */
            ends_on?: string | null;
            /**
             * Is Active
             * @default false
             */
            is_active: boolean;
            kind: components["schemas"]["CycleKind"];
            /** Name */
            name: string;
            /** Registration Closes At */
            registration_closes_at?: string | null;
            /** Registration Opens At */
            registration_opens_at?: string | null;
            /** Starts On */
            starts_on?: string | null;
        };
        /** CreateExternalOfferCommandPreview */
        CreateExternalOfferCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ExternalOfferSummary"];
        };
        /** CreateExternalOfferCommandRequest */
        CreateExternalOfferCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["CreateExternalOfferInput"];
        };
        /** CreateExternalOfferCommandResult */
        CreateExternalOfferCommandResult: {
            summary: components["schemas"]["ExternalOfferSummary"];
        };
        /** CreateExternalOfferInput */
        CreateExternalOfferInput: {
            /**
             * Company Id
             * Format: uuid
             */
            company_id: string;
            /** Ctc Lpa */
            ctc_lpa?: number | string | null;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /** Notes */
            notes?: string | null;
            /**
             * Notify
             * @default true
             */
            notify: boolean;
            /** Offered On */
            offered_on?: string | null;
            outcome: components["schemas"]["Outcome"];
            /** Reason */
            reason: string;
            /** Responded On */
            responded_on?: string | null;
            source: components["schemas"]["ExternalSource"];
            /** Source Application Id */
            source_application_id?: string | null;
            /** @default offered */
            status: components["schemas"]["ExternalStatus"];
            /** Stipend Month */
            stipend_month?: number | string | null;
        };
        /** CreateJobCommandPreview */
        CreateJobCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["JobSummary"];
        };
        /** CreateJobCommandRequest */
        CreateJobCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["CreateJobInput"];
        };
        /** CreateJobCommandResult */
        CreateJobCommandResult: {
            summary: components["schemas"]["JobSummary"];
        };
        /** CreateJobInput */
        CreateJobInput: {
            /** Application Deadline */
            application_deadline?: string | null;
            /**
             * Company Id
             * Format: uuid
             */
            company_id: string;
            /** Ctc Breakdown */
            ctc_breakdown?: string | null;
            /** Ctc Lpa */
            ctc_lpa?: number | string | null;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Description */
            description: string;
            /** Location */
            location?: string | null;
            /** Offer Acceptance Deadline */
            offer_acceptance_deadline?: string | null;
            outcome?: components["schemas"]["Outcome"] | null;
            /**
             * Program Ctc
             * @default []
             */
            program_ctc: components["schemas"]["ProgramCtcRow"][];
            /** Sector Id */
            sector_id?: string | null;
            /** Stipend Month */
            stipend_month?: number | string | null;
            /** Title */
            title: string;
        };
        /** CreateOverrideCommandPreview */
        CreateOverrideCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["OverrideSummary"];
        };
        /** CreateOverrideCommandRequest */
        CreateOverrideCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["CreateOverrideInput"];
        };
        /** CreateOverrideCommandResult */
        CreateOverrideCommandResult: {
            summary: components["schemas"]["OverrideSummary"];
        };
        /** CreateOverrideInput */
        CreateOverrideInput: {
            /**
             * Allow
             * @default true
             */
            allow: boolean;
            /** Application Id */
            application_id?: string | null;
            /** Cycle Id */
            cycle_id?: string | null;
            /** Enrollment Id */
            enrollment_id?: string | null;
            /** Expires At */
            expires_at?: string | null;
            /** Job Id */
            job_id?: string | null;
            /** Reason */
            reason: string;
            rule_domain: components["schemas"]["RuleDomain"];
        };
        /**
         * CycleKind
         * @enum {string}
         */
        CycleKind: "placement" | "internship" | "open";
        /** CyclePolicySummary */
        CyclePolicySummary: {
            /** Changed */
            changed: boolean;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Policy */
            policy: {
                [key: string]: unknown;
            };
        };
        /** CycleSummary */
        CycleSummary: {
            /** Archived At */
            archived_at: string | null;
            /** Changed */
            changed: boolean;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Is Active */
            is_active: boolean;
            kind: components["schemas"]["CycleKind"];
            /** Name */
            name: string;
        };
        /** DeactivateCompanyCommandPreview */
        DeactivateCompanyCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["CompanySummary"];
        };
        /** DeactivateCompanyCommandRequest */
        DeactivateCompanyCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["CompanyIdInput"];
        };
        /** DeactivateCompanyCommandResult */
        DeactivateCompanyCommandResult: {
            summary: components["schemas"]["CompanySummary"];
        };
        /** DeactivateOverrideCommandPreview */
        DeactivateOverrideCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["OverrideSummary"];
        };
        /** DeactivateOverrideCommandRequest */
        DeactivateOverrideCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["DeactivateOverrideInput"];
        };
        /** DeactivateOverrideCommandResult */
        DeactivateOverrideCommandResult: {
            summary: components["schemas"]["OverrideSummary"];
        };
        /** DeactivateOverrideInput */
        DeactivateOverrideInput: {
            /**
             * Override Id
             * Format: uuid
             */
            override_id: string;
            /** Reason */
            reason?: string | null;
        };
        /** DeactivateUserCommandPreview */
        DeactivateUserCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["DeactivateUserSummary"];
        };
        /** DeactivateUserCommandRequest */
        DeactivateUserCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["DeactivateUserInput"];
        };
        /** DeactivateUserCommandResult */
        DeactivateUserCommandResult: {
            summary: components["schemas"]["DeactivateUserSummary"];
        };
        /** DeactivateUserInput */
        DeactivateUserInput: {
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
        };
        /** DeactivateUserSummary */
        DeactivateUserSummary: {
            /** Changed */
            changed: boolean;
            /** Revoked Sessions */
            revoked_sessions: number;
        };
        /** DeclareProfileCommandPreview */
        DeclareProfileCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["DeclareProfileSummary"];
        };
        /** DeclareProfileCommandRequest */
        DeclareProfileCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["DeclareProfileInput"];
        };
        /** DeclareProfileCommandResult */
        DeclareProfileCommandResult: {
            summary: components["schemas"]["DeclareProfileSummary"];
        };
        /** DeclareProfileInput */
        DeclareProfileInput: {
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /** Fields */
            fields: {
                [key: string]: unknown;
            };
        };
        /** DeclareProfileSummary */
        DeclareProfileSummary: {
            /** Applied Fields */
            applied_fields: string[];
            /** Declared At */
            declared_at: string;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /** Retained Fields */
            retained_fields: string[];
        };
        /** DeclineOfferCommandPreview */
        DeclineOfferCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["OfferActionSummary"];
        };
        /** DeclineOfferCommandRequest */
        DeclineOfferCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["OfferResponseInput"];
        };
        /** DeclineOfferCommandResult */
        DeclineOfferCommandResult: {
            summary: components["schemas"]["OfferActionSummary"];
        };
        /** DeleteExternalOfferCommandPreview */
        DeleteExternalOfferCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ExternalOfferSummary"];
        };
        /** DeleteExternalOfferCommandRequest */
        DeleteExternalOfferCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["DeleteExternalOfferInput"];
        };
        /** DeleteExternalOfferCommandResult */
        DeleteExternalOfferCommandResult: {
            summary: components["schemas"]["ExternalOfferSummary"];
        };
        /** DeleteExternalOfferInput */
        DeleteExternalOfferInput: {
            expected_status: components["schemas"]["ExternalStatus"];
            /**
             * External Offer Id
             * Format: uuid
             */
            external_offer_id: string;
            /**
             * Notify
             * @default true
             */
            notify: boolean;
            /** Reason */
            reason: string;
            /**
             * Restore
             * @default []
             */
            restore: components["schemas"]["RestoreSelection"][];
        };
        /** DeleteResumeCommandPreview */
        DeleteResumeCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["DeleteResumeSummary"];
        };
        /** DeleteResumeCommandRequest */
        DeleteResumeCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["ResumeIdInput"];
        };
        /** DeleteResumeCommandResult */
        DeleteResumeCommandResult: {
            summary: components["schemas"]["DeleteResumeSummary"];
        };
        /** DeleteResumeSummary */
        DeleteResumeSummary: {
            /**
             * Deleted Resume Id
             * Format: uuid
             */
            deleted_resume_id: string;
            /** Memberships Default Cleared */
            memberships_default_cleared: number;
            /** Promoted Resume Id */
            promoted_resume_id: string | null;
        };
        /** DeleteStagedRowCommandPreview */
        DeleteStagedRowCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["DeleteStagedRowSummary"];
        };
        /** DeleteStagedRowCommandRequest */
        DeleteStagedRowCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["DeleteStagedRowInput"];
        };
        /** DeleteStagedRowCommandResult */
        DeleteStagedRowCommandResult: {
            summary: components["schemas"]["DeleteStagedRowSummary"];
        };
        /** DeleteStagedRowInput */
        DeleteStagedRowInput: {
            /**
             * Staged Row Id
             * Format: uuid
             */
            staged_row_id: string;
        };
        /** DeleteStagedRowSummary */
        DeleteStagedRowSummary: {
            /** Institute Email */
            institute_email: string;
            /**
             * Staged Row Id
             * Format: uuid
             */
            staged_row_id: string;
        };
        /** DetachExternalOfferCommandPreview */
        DetachExternalOfferCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["AttachmentSummary"];
        };
        /** DetachExternalOfferCommandRequest */
        DetachExternalOfferCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["DetachExternalOfferInput"];
        };
        /** DetachExternalOfferCommandResult */
        DetachExternalOfferCommandResult: {
            summary: components["schemas"]["AttachmentSummary"];
        };
        /** DetachExternalOfferInput */
        DetachExternalOfferInput: {
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Expected Attached Cycle Id
             * Format: uuid
             */
            expected_attached_cycle_id: string;
            /**
             * External Offer Id
             * Format: uuid
             */
            external_offer_id: string;
            /** Reason */
            reason: string;
        };
        /** DismissFindingCommandPreview */
        DismissFindingCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["FindingVerdictSummary"];
        };
        /** DismissFindingCommandRequest */
        DismissFindingCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["ResolveFindingInput"];
        };
        /** DismissFindingCommandResult */
        DismissFindingCommandResult: {
            summary: components["schemas"]["FindingVerdictSummary"];
        };
        /** EditApplicationCommandPreview */
        EditApplicationCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["EditApplicationSummary"];
        };
        /** EditApplicationCommandRequest */
        EditApplicationCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["EditApplicationInput"];
        };
        /** EditApplicationCommandResult */
        EditApplicationCommandResult: {
            summary: components["schemas"]["EditApplicationSummary"];
        };
        /** EditApplicationInput */
        EditApplicationInput: {
            /**
             * Answers
             * @default []
             */
            answers: components["schemas"]["AnswerInput"][];
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /** Resume Id */
            resume_id?: string | null;
            /** Resume Url */
            resume_url?: string | null;
        };
        /** EditApplicationSummary */
        EditApplicationSummary: {
            /** Answer Count */
            answer_count: number;
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            /** Resume Changed */
            resume_changed: boolean;
            /** Resume Url */
            resume_url: string;
        };
        /** EliminateApplicationsCommandPreview */
        EliminateApplicationsCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["BulkRoundSummary"];
        };
        /** EliminateApplicationsCommandRequest */
        EliminateApplicationsCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["BulkRoundInput"];
        };
        /** EliminateApplicationsCommandResult */
        EliminateApplicationsCommandResult: {
            summary: components["schemas"]["BulkRoundSummary"];
        };
        /** ExportPresetSummary */
        ExportPresetSummary: {
            /** Changed */
            changed: boolean;
            /** Columns */
            columns: string[];
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
        };
        /** ExportSummary */
        ExportSummary: {
            /** Columns */
            columns: string[];
            /**
             * Export Id
             * Format: uuid
             */
            export_id: string;
            /** Format */
            format: string;
            /** Kind */
            kind: string;
            /** Mode */
            mode: string;
            /** Row Count */
            row_count: number;
            /** Status */
            status: string;
        };
        /** ExtendOffersCommandPreview */
        ExtendOffersCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["BulkOfferSummary"];
        };
        /** ExtendOffersCommandRequest */
        ExtendOffersCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["ExtendOffersInput"];
        };
        /** ExtendOffersCommandResult */
        ExtendOffersCommandResult: {
            summary: components["schemas"]["BulkOfferSummary"];
        };
        /** ExtendOffersInput */
        ExtendOffersInput: {
            /** Batch Key */
            batch_key: string;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Rows */
            rows: {
                [key: string]: string;
            }[];
        };
        /** ExternalOfferSummary */
        ExternalOfferSummary: {
            /** Attached Cycle Id */
            attached_cycle_id: string | null;
            /** Automatic Effects */
            automatic_effects: {
                [key: string]: unknown;
            }[];
            /** Cascade */
            cascade: {
                [key: string]: unknown;
            }[];
            /**
             * Company Id
             * Format: uuid
             */
            company_id: string;
            /** Deleted */
            deleted: boolean;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /**
             * External Offer Id
             * Format: uuid
             */
            external_offer_id: string;
            /** Notify */
            notify: boolean;
            outcome: components["schemas"]["Outcome"];
            /** Restoration Candidates */
            restoration_candidates: {
                [key: string]: unknown;
            }[];
            /** Restored */
            restored: {
                [key: string]: unknown;
            }[];
            status: components["schemas"]["ExternalStatus"];
        };
        /**
         * ExternalSource
         * @enum {string}
         */
        ExternalSource: "ppo" | "off_campus" | "other";
        /**
         * ExternalStatus
         * @enum {string}
         */
        ExternalStatus: "offered" | "accepted" | "declined";
        /** FinalizeRoundCommandPreview */
        FinalizeRoundCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["FinalizeRoundSummary"];
        };
        /** FinalizeRoundCommandRequest */
        FinalizeRoundCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["FinalizeRoundInput"];
        };
        /** FinalizeRoundCommandResult */
        FinalizeRoundCommandResult: {
            summary: components["schemas"]["FinalizeRoundSummary"];
        };
        /** FinalizeRoundInput */
        FinalizeRoundInput: {
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /**
             * Round Id
             * Format: uuid
             */
            round_id: string;
        };
        /** FinalizeRoundSummary */
        FinalizeRoundSummary: {
            /** Finalized */
            finalized: number;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Penalties */
            penalties: number;
            /**
             * Round Id
             * Format: uuid
             */
            round_id: string;
            /** Round Name */
            round_name: string;
            /** Rows */
            rows: {
                [key: string]: unknown;
            }[];
            /** Strike On Absence */
            strike_on_absence: boolean;
            /** Strikes */
            strikes: number;
        };
        /**
         * FindingStatus
         * @enum {string}
         */
        FindingStatus: "open" | "resolved" | "dismissed";
        /** FindingVerdictSummary */
        FindingVerdictSummary: {
            /**
             * Finding Id
             * Format: uuid
             */
            finding_id: string;
            /** Invariant */
            invariant: string;
            status: components["schemas"]["FindingStatus"];
        };
        /** ForceTransitionCommandPreview */
        ForceTransitionCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ForceTransitionSummary"];
        };
        /** ForceTransitionCommandRequest */
        ForceTransitionCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["ForceTransitionInput"];
        };
        /** ForceTransitionCommandResult */
        ForceTransitionCommandResult: {
            summary: components["schemas"]["ForceTransitionSummary"];
        };
        /** ForceTransitionInput */
        ForceTransitionInput: {
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            expected_status?: components["schemas"]["ApplicationStatus"] | null;
            /** Reason */
            reason: string;
            to_status: components["schemas"]["ApplicationStatus"];
        };
        /** ForceTransitionSummary */
        ForceTransitionSummary: {
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            /** Consequences */
            consequences: string;
            from_status: components["schemas"]["ApplicationStatus"];
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            to_status: components["schemas"]["ApplicationStatus"];
            /** Unperformed */
            unperformed: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** JobEligibilitySummary */
        JobEligibilitySummary: {
            /** Changed */
            changed: boolean;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Eligibility Summary */
            eligibility_summary: string;
            /** Eligible Count */
            eligible_count: number;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Member Count */
            member_count: number;
            /** Members */
            members: {
                [key: string]: unknown;
            }[];
        };
        /** JobQuestionRow */
        JobQuestionRow: {
            /**
             * Options
             * @default []
             */
            options: string[];
            qtype: components["schemas"]["QuestionType"];
            /** Question Id */
            question_id?: string | null;
            /**
             * Required
             * @default false
             */
            required: boolean;
            /** Text */
            text: string;
        };
        /** JobQuestionsSummary */
        JobQuestionsSummary: {
            /** Added */
            added: number;
            /** Changed */
            changed: boolean;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Question Count */
            question_count: number;
            /** Removed */
            removed: number;
        };
        /** JobRoundRow */
        JobRoundRow: {
            /** Duration Min */
            duration_min?: number | null;
            /** Instructions */
            instructions?: string | null;
            /** Name */
            name: string;
            /** Round Id */
            round_id?: string | null;
            /**
             * Round Type Id
             * Format: uuid
             */
            round_type_id: string;
            /** Scheduled At */
            scheduled_at?: unknown | null;
            /** Venue */
            venue?: string | null;
        };
        /** JobRoundsSummary */
        JobRoundsSummary: {
            /** Added */
            added: number;
            /** Changed */
            changed: boolean;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Notified Applicants */
            notified_applicants: number;
            /** Removed */
            removed: number;
            /** Reordered */
            reordered: boolean;
            /** Rescheduled Applicants */
            rescheduled_applicants: number;
            /** Round Count */
            round_count: number;
        };
        /** JobSummary */
        JobSummary: {
            /** Changed */
            changed: boolean;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Is Published */
            is_published: boolean;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /**
             * Notified Applicants
             * @default 0
             */
            notified_applicants: number;
            outcome: components["schemas"]["Outcome"];
            /**
             * Scheduled Offer Expiries
             * @default 0
             */
            scheduled_offer_expiries: number;
            /** Title */
            title: string;
            /**
             * Updated Offer Deadlines
             * @default 0
             */
            updated_offer_deadlines: number;
        };
        /** JoinCycleCommandPreview */
        JoinCycleCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["MembershipSummary"];
        };
        /** JoinCycleCommandRequest */
        JoinCycleCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["JoinCycleInput"];
        };
        /** JoinCycleCommandResult */
        JoinCycleCommandResult: {
            summary: components["schemas"]["MembershipSummary"];
        };
        /** JoinCycleInput */
        JoinCycleInput: {
            /**
             * Consent
             * @default false
             */
            consent: boolean;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Default Resume Id
             * Format: uuid
             */
            default_resume_id: string;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
        };
        /** LogoutCommandPreview */
        LogoutCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["LogoutSummary"];
        };
        /** LogoutCommandRequest */
        LogoutCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["LogoutInput"];
        };
        /** LogoutCommandResult */
        LogoutCommandResult: {
            summary: components["schemas"]["LogoutSummary"];
        };
        /** LogoutInput */
        LogoutInput: Record<string, never>;
        /** LogoutSummary */
        LogoutSummary: {
            /** Logged Out */
            logged_out: boolean;
        };
        /** MarkAttendanceCommandPreview */
        MarkAttendanceCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["MarkAttendanceSummary"];
        };
        /** MarkAttendanceCommandRequest */
        MarkAttendanceCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["MarkAttendanceInput"];
        };
        /** MarkAttendanceCommandResult */
        MarkAttendanceCommandResult: {
            summary: components["schemas"]["MarkAttendanceSummary"];
        };
        /**
         * MarkAttendanceInput
         * @description One row, one named value, and the value the board was displaying.
         */
        MarkAttendanceInput: {
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            attendance: components["schemas"]["Attendance"];
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            expected_attendance: components["schemas"]["Attendance"];
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Reason */
            reason?: string | null;
            /**
             * Round Id
             * Format: uuid
             */
            round_id: string;
        };
        /** MarkAttendanceSummary */
        MarkAttendanceSummary: {
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            attendance: components["schemas"]["Attendance"];
            /** Full Name */
            full_name: string;
            previous: components["schemas"]["Attendance"];
            /**
             * Round Id
             * Format: uuid
             */
            round_id: string;
        };
        /** MembershipExitSummary */
        MembershipExitSummary: {
            /** Auto Withdrawn */
            auto_withdrawn: {
                [key: string]: unknown;
            }[];
            /** Changed */
            changed: boolean;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /**
             * Membership Id
             * Format: uuid
             */
            membership_id: string;
            status: components["schemas"]["MembershipStatus"];
            /** Untouched */
            untouched: {
                [key: string]: unknown;
            }[];
        };
        /**
         * MembershipStatus
         * @enum {string}
         */
        MembershipStatus: "pending" | "active" | "rejected" | "withdrawn" | "removed";
        /** MembershipSummary */
        MembershipSummary: {
            /** Changed */
            changed: boolean;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /**
             * Membership Id
             * Format: uuid
             */
            membership_id: string;
            status: components["schemas"]["MembershipStatus"];
        };
        /** MergeCompaniesCommandPreview */
        MergeCompaniesCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["MergeCompaniesSummary"];
        };
        /** MergeCompaniesCommandRequest */
        MergeCompaniesCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["MergeCompaniesInput"];
        };
        /** MergeCompaniesCommandResult */
        MergeCompaniesCommandResult: {
            summary: components["schemas"]["MergeCompaniesSummary"];
        };
        /** MergeCompaniesInput */
        MergeCompaniesInput: {
            /**
             * Duplicate Id
             * Format: uuid
             */
            duplicate_id: string;
            /**
             * Survivor Id
             * Format: uuid
             */
            survivor_id: string;
        };
        /** MergeCompaniesSummary */
        MergeCompaniesSummary: {
            /** Contacts Dropped */
            contacts_dropped: {
                [key: string]: unknown;
            }[];
            /** Contacts Repointed */
            contacts_repointed: number;
            /**
             * Duplicate Id
             * Format: uuid
             */
            duplicate_id: string;
            /** External Offers */
            external_offers: number;
            /** Jobs */
            jobs: number;
            /** Primary Kept */
            primary_kept: string | null;
            /**
             * Survivor Id
             * Format: uuid
             */
            survivor_id: string;
        };
        /** OfferActionSummary */
        OfferActionSummary: {
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            /** Applied Override Ids */
            applied_override_ids: string[];
            /** Cascade */
            cascade: {
                [key: string]: unknown;
            }[];
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /**
             * Offer Id
             * Format: uuid
             */
            offer_id: string;
            status: components["schemas"]["ApplicationStatus"];
        };
        /**
         * OfferExpiry
         * @enum {string}
         */
        OfferExpiry: "auto_decline" | "auto_accept";
        /** OfferResponseInput */
        OfferResponseInput: {
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            expected_status: components["schemas"]["ApplicationStatus"];
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /**
             * Offer Id
             * Format: uuid
             */
            offer_id: string;
        };
        /**
         * Outcome
         * @enum {string}
         */
        Outcome: "internship" | "placement";
        /**
         * OutcomeTag
         * @enum {string}
         */
        OutcomeTag: "higher_studies" | "entrepreneurship" | "not_seeking";
        /** OutcomeTagSummary */
        OutcomeTagSummary: {
            /** Changed */
            changed: boolean;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Membership Id
             * Format: uuid
             */
            membership_id: string;
            outcome_tag: components["schemas"]["OutcomeTag"] | null;
        };
        /** OverrideSummary */
        OverrideSummary: {
            /** Allow */
            allow: boolean;
            /** Expires At */
            expires_at: string | null;
            /** Is Active */
            is_active: boolean;
            /**
             * Override Id
             * Format: uuid
             */
            override_id: string;
            rule_domain: components["schemas"]["RuleDomain"];
            /** Scope */
            scope: string;
            /**
             * Subject Id
             * Format: uuid
             */
            subject_id: string;
        };
        /** PenaltySummary */
        PenaltySummary: {
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /** Full Name */
            full_name: string;
            /** Penalty Active */
            penalty_active: boolean;
        };
        /** ProgramCtcRow */
        ProgramCtcRow: {
            /** Ctc Lpa */
            ctc_lpa: number | string;
            /**
             * Program Id
             * Format: uuid
             */
            program_id: string;
        };
        /** PromoteWaitlistedCommandPreview */
        PromoteWaitlistedCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["BulkRoundSummary"];
        };
        /** PromoteWaitlistedCommandRequest */
        PromoteWaitlistedCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["BulkRoundInput"];
        };
        /** PromoteWaitlistedCommandResult */
        PromoteWaitlistedCommandResult: {
            summary: components["schemas"]["BulkRoundSummary"];
        };
        /** PublishJobCommandPreview */
        PublishJobCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["JobSummary"];
        };
        /** PublishJobCommandRequest */
        PublishJobCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["PublishJobInput"];
        };
        /** PublishJobCommandResult */
        PublishJobCommandResult: {
            summary: components["schemas"]["JobSummary"];
        };
        /** PublishJobInput */
        PublishJobInput: {
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
        };
        /**
         * QuestionType
         * @enum {string}
         */
        QuestionType: "text" | "longtext" | "single" | "multi" | "boolean" | "number" | "date" | "email" | "url";
        /** RecordOpenOutcomeCommandPreview */
        RecordOpenOutcomeCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["BulkOfferSummary"];
        };
        /** RecordOpenOutcomeCommandRequest */
        RecordOpenOutcomeCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["RecordOpenOutcomeInput"];
        };
        /** RecordOpenOutcomeCommandResult */
        RecordOpenOutcomeCommandResult: {
            summary: components["schemas"]["BulkOfferSummary"];
        };
        /** RecordOpenOutcomeInput */
        RecordOpenOutcomeInput: {
            /** Batch Key */
            batch_key: string;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Reason */
            reason?: string | null;
            /** Rows */
            rows: {
                [key: string]: string;
            }[];
            /**
             * Target Status
             * @enum {string}
             */
            target_status: "offered" | "accepted" | "declined" | "rejected";
        };
        /** ReExtendOfferCommandPreview */
        ReExtendOfferCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ReExtendOfferSummary"];
        };
        /** ReExtendOfferCommandRequest */
        ReExtendOfferCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["ReExtendOfferInput"];
        };
        /** ReExtendOfferCommandResult */
        ReExtendOfferCommandResult: {
            summary: components["schemas"]["ReExtendOfferSummary"];
        };
        /** ReExtendOfferInput */
        ReExtendOfferInput: {
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Deadline At */
            deadline_at?: string | null;
            expected_status: components["schemas"]["ApplicationStatus"];
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /**
             * Notify
             * @default true
             */
            notify: boolean;
            /**
             * Offer Id
             * Format: uuid
             */
            offer_id: string;
            /** Reason */
            reason: string;
        };
        /** ReExtendOfferSummary */
        ReExtendOfferSummary: {
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Deadline At */
            deadline_at: string | null;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Notify */
            notify: boolean;
            /**
             * Offer Id
             * Format: uuid
             */
            offer_id: string;
            /**
             * Previous Offer Id
             * Format: uuid
             */
            previous_offer_id: string;
            status: components["schemas"]["ApplicationStatus"];
        };
        /** ReinstateApplicationCommandPreview */
        ReinstateApplicationCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ReinstateSummary"];
        };
        /** ReinstateApplicationCommandRequest */
        ReinstateApplicationCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["ReinstateApplicationInput"];
        };
        /** ReinstateApplicationCommandResult */
        ReinstateApplicationCommandResult: {
            summary: components["schemas"]["ReinstateSummary"];
        };
        /** ReinstateApplicationInput */
        ReinstateApplicationInput: {
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            expected_status?: components["schemas"]["ApplicationStatus"] | null;
            /**
             * Notify
             * @default true
             */
            notify: boolean;
            /** Reason */
            reason: string;
            /** Target Round Id */
            target_round_id?: string | null;
        };
        /** ReinstateSummary */
        ReinstateSummary: {
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            /** Cleared Round States */
            cleared_round_states: {
                [key: string]: unknown;
            }[];
            from_status: components["schemas"]["ApplicationStatus"];
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Kept Round States */
            kept_round_states: {
                [key: string]: unknown;
            }[];
            /** Notify */
            notify: boolean;
            status: components["schemas"]["ApplicationStatus"];
            /** Target Round Id */
            target_round_id: string | null;
            /** Target Round Name */
            target_round_name: string | null;
        };
        /** RejectMembershipCommandPreview */
        RejectMembershipCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["MembershipSummary"];
        };
        /** RejectMembershipCommandRequest */
        RejectMembershipCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["RejectMembershipInput"];
        };
        /** RejectMembershipCommandResult */
        RejectMembershipCommandResult: {
            summary: components["schemas"]["MembershipSummary"];
        };
        /** RejectMembershipInput */
        RejectMembershipInput: {
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Membership Id
             * Format: uuid
             */
            membership_id: string;
            /** Reason */
            reason: string;
        };
        /** RemoveCoordinatorCommandPreview */
        RemoveCoordinatorCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["CoordinatorSummary"];
        };
        /** RemoveCoordinatorCommandRequest */
        RemoveCoordinatorCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["CoordinatorInput"];
        };
        /** RemoveCoordinatorCommandResult */
        RemoveCoordinatorCommandResult: {
            summary: components["schemas"]["CoordinatorSummary"];
        };
        /** RemoveMembershipCommandPreview */
        RemoveMembershipCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["MembershipExitSummary"];
        };
        /** RemoveMembershipCommandRequest */
        RemoveMembershipCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["RemoveMembershipInput"];
        };
        /** RemoveMembershipCommandResult */
        RemoveMembershipCommandResult: {
            summary: components["schemas"]["MembershipExitSummary"];
        };
        /** RemoveMembershipInput */
        RemoveMembershipInput: {
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Membership Id
             * Format: uuid
             */
            membership_id: string;
            /** Reason */
            reason: string;
        };
        /** RequestExportCommandPreview */
        RequestExportCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ExportSummary"];
        };
        /** RequestExportCommandRequest */
        RequestExportCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["RequestExportInput"];
        };
        /** RequestExportCommandResult */
        RequestExportCommandResult: {
            summary: components["schemas"]["ExportSummary"];
        };
        /** RequestExportInput */
        RequestExportInput: {
            /**
             * Cohort
             * @default applicants
             * @enum {string}
             */
            cohort: "applicants" | "round" | "offers";
            /**
             * Columns
             * @default []
             */
            columns: string[];
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Format
             * @default xlsx
             * @enum {string}
             */
            format: "xlsx" | "csv";
            /** Job Id */
            job_id?: string | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "job_applications" | "cycle_memberships";
            /**
             * Passed Only
             * @default true
             */
            passed_only: boolean;
            /** Round Id */
            round_id?: string | null;
            /** Status */
            status?: string | null;
        };
        /** RerequestMembershipCommandPreview */
        RerequestMembershipCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["MembershipSummary"];
        };
        /** RerequestMembershipCommandRequest */
        RerequestMembershipCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["RerequestMembershipInput"];
        };
        /** RerequestMembershipCommandResult */
        RerequestMembershipCommandResult: {
            summary: components["schemas"]["MembershipSummary"];
        };
        /** RerequestMembershipInput */
        RerequestMembershipInput: {
            /**
             * Consent
             * @default false
             */
            consent: boolean;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Default Resume Id
             * Format: uuid
             */
            default_resume_id: string;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
        };
        /** ResendNotificationCommandPreview */
        ResendNotificationCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ResendNotificationSummary"];
        };
        /** ResendNotificationCommandRequest */
        ResendNotificationCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["ResendNotificationInput"];
        };
        /** ResendNotificationCommandResult */
        ResendNotificationCommandResult: {
            summary: components["schemas"]["ResendNotificationSummary"];
        };
        /** ResendNotificationInput */
        ResendNotificationInput: {
            /**
             * Notification Id
             * Format: uuid
             */
            notification_id: string;
        };
        /** ResendNotificationSummary */
        ResendNotificationSummary: {
            /**
             * Notification Id
             * Format: uuid
             */
            notification_id: string;
            /** Queued */
            queued: boolean;
        };
        /** ResolveFindingCommandPreview */
        ResolveFindingCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["FindingVerdictSummary"];
        };
        /** ResolveFindingCommandRequest */
        ResolveFindingCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["ResolveFindingInput"];
        };
        /** ResolveFindingCommandResult */
        ResolveFindingCommandResult: {
            summary: components["schemas"]["FindingVerdictSummary"];
        };
        /** ResolveFindingInput */
        ResolveFindingInput: {
            /**
             * Finding Id
             * Format: uuid
             */
            finding_id: string;
            /** Reason */
            reason: string;
        };
        /** RestoreMembershipCommandPreview */
        RestoreMembershipCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["MembershipExitSummary"];
        };
        /** RestoreMembershipCommandRequest */
        RestoreMembershipCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["RestoreMembershipInput"];
        };
        /** RestoreMembershipCommandResult */
        RestoreMembershipCommandResult: {
            summary: components["schemas"]["MembershipExitSummary"];
        };
        /** RestoreMembershipInput */
        RestoreMembershipInput: {
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Membership Id
             * Format: uuid
             */
            membership_id: string;
        };
        /** RestoreSelection */
        RestoreSelection: {
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            /** Deadline At */
            deadline_at?: string | null;
        };
        /** ResumeIdInput */
        ResumeIdInput: {
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /**
             * Resume Id
             * Format: uuid
             */
            resume_id: string;
        };
        /** ResumeSummary */
        ResumeSummary: {
            /** Changed */
            changed: boolean;
            /** Is Default */
            is_default: boolean;
            /**
             * Resume Id
             * Format: uuid
             */
            resume_id: string;
        };
        /** RevokePenaltyCommandPreview */
        RevokePenaltyCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["PenaltySummary"];
        };
        /** RevokePenaltyCommandRequest */
        RevokePenaltyCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["RevokePenaltyInput"];
        };
        /** RevokePenaltyCommandResult */
        RevokePenaltyCommandResult: {
            summary: components["schemas"]["PenaltySummary"];
        };
        /** RevokePenaltyInput */
        RevokePenaltyInput: {
            /**
             * Penalty Id
             * Format: uuid
             */
            penalty_id: string;
            /** Reason */
            reason: string;
        };
        /** RevokeStrikeCommandPreview */
        RevokeStrikeCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["RevokeStrikeSummary"];
        };
        /** RevokeStrikeCommandRequest */
        RevokeStrikeCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["RevokeStrikeInput"];
        };
        /** RevokeStrikeCommandResult */
        RevokeStrikeCommandResult: {
            summary: components["schemas"]["RevokeStrikeSummary"];
        };
        /** RevokeStrikeInput */
        RevokeStrikeInput: {
            /** Reason */
            reason: string;
            /**
             * Strike Id
             * Format: uuid
             */
            strike_id: string;
        };
        /** RevokeStrikeSummary */
        RevokeStrikeSummary: {
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /** Full Name */
            full_name: string;
            /** Penalties Created */
            penalties_created: number;
            /** Penalties Dissolved */
            penalties_dissolved: number;
            /** Strike Total */
            strike_total: number;
        };
        /**
         * Role
         * @enum {string}
         */
        Role: "student" | "admin";
        /**
         * RuleDomain
         * @enum {string}
         */
        RuleDomain: "eligibility" | "application_deadline" | "edit_window" | "withdraw_window" | "outcome_gate" | "offer_cap" | "offer_deadline" | "cycle_registration_window" | "cycle_join_rule";
        /** RunConsistencyCheckerCommandPreview */
        RunConsistencyCheckerCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ConsistencyRunSummary"];
        };
        /** RunConsistencyCheckerCommandRequest */
        RunConsistencyCheckerCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["RunConsistencyCheckerInput"];
        };
        /** RunConsistencyCheckerCommandResult */
        RunConsistencyCheckerCommandResult: {
            summary: components["schemas"]["ConsistencyRunSummary"];
        };
        /** RunConsistencyCheckerInput */
        RunConsistencyCheckerInput: {
            /** Run At */
            run_at?: string | null;
        };
        /** SaveExportPresetCommandPreview */
        SaveExportPresetCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ExportPresetSummary"];
        };
        /** SaveExportPresetCommandRequest */
        SaveExportPresetCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["SaveExportPresetInput"];
        };
        /** SaveExportPresetCommandResult */
        SaveExportPresetCommandResult: {
            summary: components["schemas"]["ExportPresetSummary"];
        };
        /** SaveExportPresetInput */
        SaveExportPresetInput: {
            /** Columns */
            columns: string[];
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
        };
        /** SetCycleActiveCommandPreview */
        SetCycleActiveCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["CycleSummary"];
        };
        /** SetCycleActiveCommandRequest */
        SetCycleActiveCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["SetCycleActiveInput"];
        };
        /** SetCycleActiveCommandResult */
        SetCycleActiveCommandResult: {
            summary: components["schemas"]["CycleSummary"];
        };
        /** SetCycleActiveInput */
        SetCycleActiveInput: {
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Is Active */
            is_active: boolean;
        };
        /** SetDefaultResumeCommandPreview */
        SetDefaultResumeCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ResumeSummary"];
        };
        /** SetDefaultResumeCommandRequest */
        SetDefaultResumeCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["ResumeIdInput"];
        };
        /** SetDefaultResumeCommandResult */
        SetDefaultResumeCommandResult: {
            summary: components["schemas"]["ResumeSummary"];
        };
        /** SetOutcomeTagCommandPreview */
        SetOutcomeTagCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["OutcomeTagSummary"];
        };
        /** SetOutcomeTagCommandRequest */
        SetOutcomeTagCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["SetOutcomeTagInput"];
        };
        /** SetOutcomeTagCommandResult */
        SetOutcomeTagCommandResult: {
            summary: components["schemas"]["OutcomeTagSummary"];
        };
        /** SetOutcomeTagInput */
        SetOutcomeTagInput: {
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Membership Id
             * Format: uuid
             */
            membership_id: string;
            outcome_tag?: components["schemas"]["OutcomeTag"] | null;
        };
        /** SetSettingCommandPreview */
        SetSettingCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["SetSettingSummary"];
        };
        /** SetSettingCommandRequest */
        SetSettingCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["SetSettingInput"];
        };
        /** SetSettingCommandResult */
        SetSettingCommandResult: {
            summary: components["schemas"]["SetSettingSummary"];
        };
        /** SetSettingInput */
        SetSettingInput: {
            key: components["schemas"]["SettingKey"];
            /** Value */
            value: unknown;
        };
        /** SetSettingSummary */
        SetSettingSummary: {
            /** Changed */
            changed: boolean;
            key: components["schemas"]["SettingKey"];
            /** Value */
            value: unknown;
        };
        /**
         * SettingKey
         * @enum {string}
         */
        SettingKey: "strikes_per_penalty" | "session_hours" | "ses_sender";
        /** SetUserRoleCommandPreview */
        SetUserRoleCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["SetUserRoleSummary"];
        };
        /** SetUserRoleCommandRequest */
        SetUserRoleCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["SetUserRoleInput"];
        };
        /** SetUserRoleCommandResult */
        SetUserRoleCommandResult: {
            summary: components["schemas"]["SetUserRoleSummary"];
        };
        /** SetUserRoleInput */
        SetUserRoleInput: {
            role: components["schemas"]["Role"];
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
        };
        /** SetUserRoleSummary */
        SetUserRoleSummary: {
            /** Changed */
            changed: boolean;
            role: components["schemas"]["Role"];
        };
        /** StartNewEnrollmentCommandPreview */
        StartNewEnrollmentCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["StartNewEnrollmentSummary"];
        };
        /** StartNewEnrollmentCommandRequest */
        StartNewEnrollmentCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["StartNewEnrollmentInput"];
        };
        /** StartNewEnrollmentCommandResult */
        StartNewEnrollmentCommandResult: {
            summary: components["schemas"]["StartNewEnrollmentSummary"];
        };
        /** StartNewEnrollmentInput */
        StartNewEnrollmentInput: {
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
        };
        /** StartNewEnrollmentSummary */
        StartNewEnrollmentSummary: {
            /**
             * New Enrollment Id
             * Format: uuid
             */
            new_enrollment_id: string;
        };
        /** StrikeSummary */
        StrikeSummary: {
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /** Full Name */
            full_name: string;
            /** Penalties Created */
            penalties_created: number;
            /** Strike Total */
            strike_total: number;
        };
        /**
         * TaxonomyKind
         * @enum {string}
         */
        TaxonomyKind: "programs" | "branches" | "minors" | "sectors" | "round_types";
        /** TerminateOfferCommandPreview */
        TerminateOfferCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["TerminateOfferSummary"];
        };
        /** TerminateOfferCommandRequest */
        TerminateOfferCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["TerminateOfferInput"];
        };
        /** TerminateOfferCommandResult */
        TerminateOfferCommandResult: {
            summary: components["schemas"]["TerminateOfferSummary"];
        };
        /** TerminateOfferInput */
        TerminateOfferInput: {
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Discipline */
            discipline?: ("strike" | "penalty") | null;
            expected_status: components["schemas"]["ApplicationStatus"];
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /**
             * Notify
             * @default true
             */
            notify: boolean;
            /**
             * Offer Id
             * Format: uuid
             */
            offer_id: string;
            /** Reason */
            reason: string;
            /**
             * Restore
             * @default []
             */
            restore: components["schemas"]["RestoreSelection"][];
            termination_kind: components["schemas"]["TerminationKind"];
        };
        /** TerminateOfferSummary */
        TerminateOfferSummary: {
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            /** Automatic Effects */
            automatic_effects: {
                [key: string]: unknown;
            }[];
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Discipline */
            discipline: {
                [key: string]: unknown;
            } | null;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Notify */
            notify: boolean;
            /**
             * Offer Id
             * Format: uuid
             */
            offer_id: string;
            /** Reason */
            reason: string;
            /** Restoration Candidates */
            restoration_candidates: {
                [key: string]: unknown;
            }[];
            /** Restored */
            restored: {
                [key: string]: unknown;
            }[];
            status: components["schemas"]["ApplicationStatus"];
            termination_kind: components["schemas"]["TerminationKind"];
        };
        /**
         * TerminationKind
         * @enum {string}
         */
        TerminationKind: "company_revoked" | "student_renege" | "admin_correction";
        /** UnpublishJobCommandPreview */
        UnpublishJobCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["JobSummary"];
        };
        /** UnpublishJobCommandRequest */
        UnpublishJobCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["PublishJobInput"];
        };
        /** UnpublishJobCommandResult */
        UnpublishJobCommandResult: {
            summary: components["schemas"]["JobSummary"];
        };
        /** UpdateCompanyCommandPreview */
        UpdateCompanyCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["CompanySummary"];
        };
        /** UpdateCompanyCommandRequest */
        UpdateCompanyCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["UpdateCompanyInput"];
        };
        /** UpdateCompanyCommandResult */
        UpdateCompanyCommandResult: {
            summary: components["schemas"]["CompanySummary"];
        };
        /** UpdateCompanyInput */
        UpdateCompanyInput: {
            /**
             * Company Id
             * Format: uuid
             */
            company_id: string;
            /** Description */
            description?: string | null;
            /** Name */
            name?: string | null;
            /** Sector Id */
            sector_id?: string | null;
            /** Website Url */
            website_url?: string | null;
        };
        /** UpdateCycleCommandPreview */
        UpdateCycleCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["CycleSummary"];
        };
        /** UpdateCycleCommandRequest */
        UpdateCycleCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["UpdateCycleInput"];
        };
        /** UpdateCycleCommandResult */
        UpdateCycleCommandResult: {
            summary: components["schemas"]["CycleSummary"];
        };
        /** UpdateCycleInput */
        UpdateCycleInput: {
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Description */
            description?: string | null;
            /** Ends On */
            ends_on?: string | null;
            kind?: components["schemas"]["CycleKind"] | null;
            /** Name */
            name?: string | null;
            /** Registration Closes At */
            registration_closes_at?: string | null;
            /** Registration Opens At */
            registration_opens_at?: string | null;
            /** Starts On */
            starts_on?: string | null;
        };
        /** UpdateCyclePolicyCommandPreview */
        UpdateCyclePolicyCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["CyclePolicySummary"];
        };
        /** UpdateCyclePolicyCommandRequest */
        UpdateCyclePolicyCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["UpdateCyclePolicyInput"];
        };
        /** UpdateCyclePolicyCommandResult */
        UpdateCyclePolicyCommandResult: {
            summary: components["schemas"]["CyclePolicySummary"];
        };
        /** UpdateCyclePolicyInput */
        UpdateCyclePolicyInput: {
            /** Allow Edit After Deadline */
            allow_edit_after_deadline?: boolean | null;
            /** Allow Withdrawal After Deadline */
            allow_withdrawal_after_deadline?: boolean | null;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Deadline Reminder Hours */
            deadline_reminder_hours?: number | null;
            /** Join Rule */
            join_rule?: {
                [key: string]: unknown;
            } | null;
            /** Max Accepted Offers */
            max_accepted_offers?: number | null;
            /** Membership Requires Approval */
            membership_requires_approval?: boolean | null;
            offer_expiry_behavior?: components["schemas"]["OfferExpiry"] | null;
            /** Penalty Blocks Applications */
            penalty_blocks_applications?: boolean | null;
            /** Round Reminder Hours */
            round_reminder_hours?: number | null;
            /** Strike On Absence */
            strike_on_absence?: boolean | null;
        };
        /** UpdateExternalOfferCommandPreview */
        UpdateExternalOfferCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ExternalOfferSummary"];
        };
        /** UpdateExternalOfferCommandRequest */
        UpdateExternalOfferCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["UpdateExternalOfferInput"];
        };
        /** UpdateExternalOfferCommandResult */
        UpdateExternalOfferCommandResult: {
            summary: components["schemas"]["ExternalOfferSummary"];
        };
        /** UpdateExternalOfferInput */
        UpdateExternalOfferInput: {
            /**
             * Clear Ctc Lpa
             * @default false
             */
            clear_ctc_lpa: boolean;
            /**
             * Clear Notes
             * @default false
             */
            clear_notes: boolean;
            /**
             * Clear Offered On
             * @default false
             */
            clear_offered_on: boolean;
            /**
             * Clear Responded On
             * @default false
             */
            clear_responded_on: boolean;
            /**
             * Clear Source Application
             * @default false
             */
            clear_source_application: boolean;
            /**
             * Clear Stipend Month
             * @default false
             */
            clear_stipend_month: boolean;
            /** Company Id */
            company_id?: string | null;
            /** Ctc Lpa */
            ctc_lpa?: number | string | null;
            expected_status: components["schemas"]["ExternalStatus"];
            /**
             * External Offer Id
             * Format: uuid
             */
            external_offer_id: string;
            /** Notes */
            notes?: string | null;
            /**
             * Notify
             * @default true
             */
            notify: boolean;
            /** Offered On */
            offered_on?: string | null;
            outcome?: components["schemas"]["Outcome"] | null;
            /** Reason */
            reason: string;
            /** Responded On */
            responded_on?: string | null;
            /**
             * Restore
             * @default []
             */
            restore: components["schemas"]["RestoreSelection"][];
            source?: components["schemas"]["ExternalSource"] | null;
            /** Source Application Id */
            source_application_id?: string | null;
            status?: components["schemas"]["ExternalStatus"] | null;
            /** Stipend Month */
            stipend_month?: number | string | null;
        };
        /** UpdateJobBasicsCommandPreview */
        UpdateJobBasicsCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["JobSummary"];
        };
        /** UpdateJobBasicsCommandRequest */
        UpdateJobBasicsCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["UpdateJobBasicsInput"];
        };
        /** UpdateJobBasicsCommandResult */
        UpdateJobBasicsCommandResult: {
            summary: components["schemas"]["JobSummary"];
        };
        /** UpdateJobBasicsInput */
        UpdateJobBasicsInput: {
            /** Application Deadline */
            application_deadline?: string | null;
            /** Company Id */
            company_id?: string | null;
            /** Ctc Breakdown */
            ctc_breakdown?: string | null;
            /** Ctc Lpa */
            ctc_lpa?: number | string | null;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Description */
            description?: string | null;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Location */
            location?: string | null;
            /** Offer Acceptance Deadline */
            offer_acceptance_deadline?: string | null;
            outcome?: components["schemas"]["Outcome"] | null;
            /** Program Ctc */
            program_ctc?: components["schemas"]["ProgramCtcRow"][] | null;
            /** Sector Id */
            sector_id?: string | null;
            /** Stipend Month */
            stipend_month?: number | string | null;
            /** Title */
            title?: string | null;
        };
        /** UpdateJobEligibilityCommandPreview */
        UpdateJobEligibilityCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["JobEligibilitySummary"];
        };
        /** UpdateJobEligibilityCommandRequest */
        UpdateJobEligibilityCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["UpdateJobEligibilityInput"];
        };
        /** UpdateJobEligibilityCommandResult */
        UpdateJobEligibilityCommandResult: {
            summary: components["schemas"]["JobEligibilitySummary"];
        };
        /** UpdateJobEligibilityInput */
        UpdateJobEligibilityInput: {
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /** Eligibility Rule */
            eligibility_rule?: {
                [key: string]: unknown;
            } | null;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
        };
        /** UpdateProfileSummary */
        UpdateProfileSummary: {
            /** Changed Fields */
            changed_fields: string[];
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
        };
        /** UpdateResumeCommandPreview */
        UpdateResumeCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["ResumeSummary"];
        };
        /** UpdateResumeCommandRequest */
        UpdateResumeCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["UpdateResumeInput"];
        };
        /** UpdateResumeCommandResult */
        UpdateResumeCommandResult: {
            summary: components["schemas"]["ResumeSummary"];
        };
        /** UpdateResumeInput */
        UpdateResumeInput: {
            /** Drive Url */
            drive_url?: string | null;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /** Label */
            label?: string | null;
            /**
             * Resume Id
             * Format: uuid
             */
            resume_id: string;
        };
        /** UpdateStudentFieldsCommandPreview */
        UpdateStudentFieldsCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["UpdateProfileSummary"];
        };
        /** UpdateStudentFieldsCommandRequest */
        UpdateStudentFieldsCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["UpdateStudentFieldsInput"];
        };
        /** UpdateStudentFieldsCommandResult */
        UpdateStudentFieldsCommandResult: {
            summary: components["schemas"]["UpdateProfileSummary"];
        };
        /** UpdateStudentFieldsInput */
        UpdateStudentFieldsInput: {
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
            /** Fields */
            fields: {
                [key: string]: unknown;
            };
        };
        /** UpdateTemplateCommandPreview */
        UpdateTemplateCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["UpdateTemplateSummary"];
        };
        /** UpdateTemplateCommandRequest */
        UpdateTemplateCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["UpdateTemplateInput"];
        };
        /** UpdateTemplateCommandResult */
        UpdateTemplateCommandResult: {
            summary: components["schemas"]["UpdateTemplateSummary"];
        };
        /** UpdateTemplateInput */
        UpdateTemplateInput: {
            /** Body */
            body: string;
            /** Cycle Id */
            cycle_id?: string | null;
            /** Enabled */
            enabled: boolean;
            /** Event Key */
            event_key: string;
            /** Subject */
            subject: string;
        };
        /** UpdateTemplateSummary */
        UpdateTemplateSummary: {
            /** Created */
            created: boolean;
            /** Cycle Id */
            cycle_id: string | null;
            /** Enabled */
            enabled: boolean;
            /** Event Key */
            event_key: string;
            /**
             * Template Id
             * Format: uuid
             */
            template_id: string;
        };
        /** UpsertJobQuestionsCommandPreview */
        UpsertJobQuestionsCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["JobQuestionsSummary"];
        };
        /** UpsertJobQuestionsCommandRequest */
        UpsertJobQuestionsCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["UpsertJobQuestionsInput"];
        };
        /** UpsertJobQuestionsCommandResult */
        UpsertJobQuestionsCommandResult: {
            summary: components["schemas"]["JobQuestionsSummary"];
        };
        /** UpsertJobQuestionsInput */
        UpsertJobQuestionsInput: {
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Questions */
            questions: components["schemas"]["JobQuestionRow"][];
        };
        /** UpsertJobRoundsCommandPreview */
        UpsertJobRoundsCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["JobRoundsSummary"];
        };
        /** UpsertJobRoundsCommandRequest */
        UpsertJobRoundsCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["UpsertJobRoundsInput"];
        };
        /** UpsertJobRoundsCommandResult */
        UpsertJobRoundsCommandResult: {
            summary: components["schemas"]["JobRoundsSummary"];
        };
        /** UpsertJobRoundsInput */
        UpsertJobRoundsInput: {
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Rounds */
            rounds: components["schemas"]["JobRoundRow"][];
        };
        /** UpsertTaxonomyItemCommandPreview */
        UpsertTaxonomyItemCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["UpsertTaxonomyItemSummary"];
        };
        /** UpsertTaxonomyItemCommandRequest */
        UpsertTaxonomyItemCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["UpsertTaxonomyItemInput"];
        };
        /** UpsertTaxonomyItemCommandResult */
        UpsertTaxonomyItemCommandResult: {
            summary: components["schemas"]["UpsertTaxonomyItemSummary"];
        };
        /** UpsertTaxonomyItemInput */
        UpsertTaxonomyItemInput: {
            /**
             * Action
             * @default upsert
             * @enum {string}
             */
            action: "upsert" | "delete";
            /** Branch Ids */
            branch_ids?: string[] | null;
            /**
             * Is Active
             * @default true
             */
            is_active: boolean;
            /** Item Id */
            item_id?: string | null;
            kind: components["schemas"]["TaxonomyKind"];
            /** Name */
            name?: string | null;
        };
        /** UpsertTaxonomyItemSummary */
        UpsertTaxonomyItemSummary: {
            /**
             * Action
             * @enum {string}
             */
            action: "created" | "updated" | "deleted" | "deactivated" | "unchanged";
            /** Branch Ids */
            branch_ids?: string[] | null;
            /** Is Active */
            is_active: boolean | null;
            /**
             * Item Id
             * Format: uuid
             */
            item_id: string;
            kind: components["schemas"]["TaxonomyKind"];
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /** WaitlistApplicationsCommandPreview */
        WaitlistApplicationsCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["BulkRoundSummary"];
        };
        /** WaitlistApplicationsCommandRequest */
        WaitlistApplicationsCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["BulkRoundInput"];
        };
        /** WaitlistApplicationsCommandResult */
        WaitlistApplicationsCommandResult: {
            summary: components["schemas"]["BulkRoundSummary"];
        };
        /** WithdrawApplicationCommandPreview */
        WithdrawApplicationCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["WithdrawApplicationSummary"];
        };
        /** WithdrawApplicationCommandRequest */
        WithdrawApplicationCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["WithdrawApplicationInput"];
        };
        /** WithdrawApplicationCommandResult */
        WithdrawApplicationCommandResult: {
            summary: components["schemas"]["WithdrawApplicationSummary"];
        };
        /** WithdrawApplicationInput */
        WithdrawApplicationInput: {
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
        };
        /** WithdrawApplicationSummary */
        WithdrawApplicationSummary: {
            /**
             * Application Id
             * Format: uuid
             */
            application_id: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            status: components["schemas"]["ApplicationStatus"];
        };
        /** WithdrawMembershipCommandPreview */
        WithdrawMembershipCommandPreview: {
            /** Events */
            events: {
                [key: string]: unknown;
            }[];
            summary: components["schemas"]["MembershipExitSummary"];
        };
        /** WithdrawMembershipCommandRequest */
        WithdrawMembershipCommandRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
            /** Idempotency Key */
            idempotency_key?: string | null;
            input: components["schemas"]["WithdrawMembershipInput"];
        };
        /** WithdrawMembershipCommandResult */
        WithdrawMembershipCommandResult: {
            summary: components["schemas"]["MembershipExitSummary"];
        };
        /** WithdrawMembershipInput */
        WithdrawMembershipInput: {
            /**
             * Cycle Id
             * Format: uuid
             */
            cycle_id: string;
            /**
             * Enrollment Id
             * Format: uuid
             */
            enrollment_id: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    command_accept_offer_api_v1_commands_accept_offer_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AcceptOfferCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AcceptOfferCommandResult"] | components["schemas"]["AcceptOfferCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_activate_company_api_v1_commands_activate_company_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ActivateCompanyCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ActivateCompanyCommandResult"] | components["schemas"]["ActivateCompanyCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_add_resume_api_v1_commands_add_resume_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AddResumeCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AddResumeCommandResult"] | components["schemas"]["AddResumeCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_admin_update_profile_api_v1_commands_admin_update_profile_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AdminUpdateProfileCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdminUpdateProfileCommandResult"] | components["schemas"]["AdminUpdateProfileCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_advance_applications_api_v1_commands_advance_applications_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AdvanceApplicationsCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdvanceApplicationsCommandResult"] | components["schemas"]["AdvanceApplicationsCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_apply_api_v1_commands_apply_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApplyCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApplyCommandResult"] | components["schemas"]["ApplyCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_approve_memberships_api_v1_commands_approve_memberships_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApproveMembershipsCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApproveMembershipsCommandResult"] | components["schemas"]["ApproveMembershipsCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_archive_cycle_api_v1_commands_archive_cycle_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ArchiveCycleCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArchiveCycleCommandResult"] | components["schemas"]["ArchiveCycleCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_assign_coordinator_api_v1_commands_assign_coordinator_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AssignCoordinatorCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssignCoordinatorCommandResult"] | components["schemas"]["AssignCoordinatorCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_assign_venue_timing_api_v1_commands_assign_venue_timing_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AssignVenueTimingCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssignVenueTimingCommandResult"] | components["schemas"]["AssignVenueTimingCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_attach_external_offer_api_v1_commands_attach_external_offer_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AttachExternalOfferCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AttachExternalOfferCommandResult"] | components["schemas"]["AttachExternalOfferCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_attach_external_offers_api_v1_commands_attach_external_offers_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AttachExternalOffersCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AttachExternalOffersCommandResult"] | components["schemas"]["AttachExternalOffersCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_award_penalty_api_v1_commands_award_penalty_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AwardPenaltyCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AwardPenaltyCommandResult"] | components["schemas"]["AwardPenaltyCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_award_strike_api_v1_commands_award_strike_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AwardStrikeCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AwardStrikeCommandResult"] | components["schemas"]["AwardStrikeCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_bulk_mark_absent_api_v1_commands_bulk_mark_absent_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BulkMarkAbsentCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BulkMarkAbsentCommandResult"] | components["schemas"]["BulkMarkAbsentCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_bulk_mark_present_api_v1_commands_bulk_mark_present_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BulkMarkPresentCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BulkMarkPresentCommandResult"] | components["schemas"]["BulkMarkPresentCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_bulk_upsert_profiles_api_v1_commands_bulk_upsert_profiles_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BulkUpsertProfilesCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BulkUpsertProfilesCommandResult"] | components["schemas"]["BulkUpsertProfilesCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_cancel_job_api_v1_commands_cancel_job_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CancelJobCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CancelJobCommandResult"] | components["schemas"]["CancelJobCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_contact_create_api_v1_commands_contact_create_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ContactCreateCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContactCreateCommandResult"] | components["schemas"]["ContactCreateCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_contact_delete_api_v1_commands_contact_delete_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ContactDeleteCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContactDeleteCommandResult"] | components["schemas"]["ContactDeleteCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_contact_update_api_v1_commands_contact_update_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ContactUpdateCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContactUpdateCommandResult"] | components["schemas"]["ContactUpdateCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_create_company_api_v1_commands_create_company_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateCompanyCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreateCompanyCommandResult"] | components["schemas"]["CreateCompanyCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_create_cycle_api_v1_commands_create_cycle_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateCycleCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreateCycleCommandResult"] | components["schemas"]["CreateCycleCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_create_external_offer_api_v1_commands_create_external_offer_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateExternalOfferCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreateExternalOfferCommandResult"] | components["schemas"]["CreateExternalOfferCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_create_job_api_v1_commands_create_job_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateJobCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreateJobCommandResult"] | components["schemas"]["CreateJobCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_create_override_api_v1_commands_create_override_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateOverrideCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreateOverrideCommandResult"] | components["schemas"]["CreateOverrideCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_deactivate_company_api_v1_commands_deactivate_company_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DeactivateCompanyCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeactivateCompanyCommandResult"] | components["schemas"]["DeactivateCompanyCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_deactivate_override_api_v1_commands_deactivate_override_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DeactivateOverrideCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeactivateOverrideCommandResult"] | components["schemas"]["DeactivateOverrideCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_deactivate_user_api_v1_commands_deactivate_user_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DeactivateUserCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeactivateUserCommandResult"] | components["schemas"]["DeactivateUserCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_declare_profile_api_v1_commands_declare_profile_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DeclareProfileCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeclareProfileCommandResult"] | components["schemas"]["DeclareProfileCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_decline_offer_api_v1_commands_decline_offer_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DeclineOfferCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeclineOfferCommandResult"] | components["schemas"]["DeclineOfferCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_delete_external_offer_api_v1_commands_delete_external_offer_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DeleteExternalOfferCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeleteExternalOfferCommandResult"] | components["schemas"]["DeleteExternalOfferCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_delete_resume_api_v1_commands_delete_resume_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DeleteResumeCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeleteResumeCommandResult"] | components["schemas"]["DeleteResumeCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_delete_staged_row_api_v1_commands_delete_staged_row_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DeleteStagedRowCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeleteStagedRowCommandResult"] | components["schemas"]["DeleteStagedRowCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_detach_external_offer_api_v1_commands_detach_external_offer_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DetachExternalOfferCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DetachExternalOfferCommandResult"] | components["schemas"]["DetachExternalOfferCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_dismiss_finding_api_v1_commands_dismiss_finding_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DismissFindingCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DismissFindingCommandResult"] | components["schemas"]["DismissFindingCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_edit_application_api_v1_commands_edit_application_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EditApplicationCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EditApplicationCommandResult"] | components["schemas"]["EditApplicationCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_eliminate_applications_api_v1_commands_eliminate_applications_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EliminateApplicationsCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EliminateApplicationsCommandResult"] | components["schemas"]["EliminateApplicationsCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_extend_offers_api_v1_commands_extend_offers_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ExtendOffersCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExtendOffersCommandResult"] | components["schemas"]["ExtendOffersCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_finalize_round_api_v1_commands_finalize_round_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FinalizeRoundCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FinalizeRoundCommandResult"] | components["schemas"]["FinalizeRoundCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_force_transition_api_v1_commands_force_transition_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ForceTransitionCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ForceTransitionCommandResult"] | components["schemas"]["ForceTransitionCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_join_cycle_api_v1_commands_join_cycle_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["JoinCycleCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JoinCycleCommandResult"] | components["schemas"]["JoinCycleCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_logout_api_v1_commands_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LogoutCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LogoutCommandResult"] | components["schemas"]["LogoutCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_mark_attendance_api_v1_commands_mark_attendance_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MarkAttendanceCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MarkAttendanceCommandResult"] | components["schemas"]["MarkAttendanceCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_merge_companies_api_v1_commands_merge_companies_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MergeCompaniesCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MergeCompaniesCommandResult"] | components["schemas"]["MergeCompaniesCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_promote_waitlisted_api_v1_commands_promote_waitlisted_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PromoteWaitlistedCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromoteWaitlistedCommandResult"] | components["schemas"]["PromoteWaitlistedCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_publish_job_api_v1_commands_publish_job_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PublishJobCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublishJobCommandResult"] | components["schemas"]["PublishJobCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_re_extend_offer_api_v1_commands_re_extend_offer_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReExtendOfferCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReExtendOfferCommandResult"] | components["schemas"]["ReExtendOfferCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_record_open_outcome_api_v1_commands_record_open_outcome_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecordOpenOutcomeCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecordOpenOutcomeCommandResult"] | components["schemas"]["RecordOpenOutcomeCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_reinstate_application_api_v1_commands_reinstate_application_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReinstateApplicationCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReinstateApplicationCommandResult"] | components["schemas"]["ReinstateApplicationCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_reject_membership_api_v1_commands_reject_membership_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RejectMembershipCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RejectMembershipCommandResult"] | components["schemas"]["RejectMembershipCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_remove_coordinator_api_v1_commands_remove_coordinator_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RemoveCoordinatorCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RemoveCoordinatorCommandResult"] | components["schemas"]["RemoveCoordinatorCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_remove_membership_api_v1_commands_remove_membership_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RemoveMembershipCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RemoveMembershipCommandResult"] | components["schemas"]["RemoveMembershipCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_request_export_api_v1_commands_request_export_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RequestExportCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RequestExportCommandResult"] | components["schemas"]["RequestExportCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_rerequest_membership_api_v1_commands_rerequest_membership_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RerequestMembershipCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RerequestMembershipCommandResult"] | components["schemas"]["RerequestMembershipCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_resend_notification_api_v1_commands_resend_notification_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResendNotificationCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResendNotificationCommandResult"] | components["schemas"]["ResendNotificationCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_resolve_finding_api_v1_commands_resolve_finding_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResolveFindingCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResolveFindingCommandResult"] | components["schemas"]["ResolveFindingCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_restore_membership_api_v1_commands_restore_membership_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RestoreMembershipCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RestoreMembershipCommandResult"] | components["schemas"]["RestoreMembershipCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_revoke_penalty_api_v1_commands_revoke_penalty_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RevokePenaltyCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RevokePenaltyCommandResult"] | components["schemas"]["RevokePenaltyCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_revoke_strike_api_v1_commands_revoke_strike_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RevokeStrikeCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RevokeStrikeCommandResult"] | components["schemas"]["RevokeStrikeCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_run_consistency_checker_api_v1_commands_run_consistency_checker_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RunConsistencyCheckerCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunConsistencyCheckerCommandResult"] | components["schemas"]["RunConsistencyCheckerCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_save_export_preset_api_v1_commands_save_export_preset_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SaveExportPresetCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SaveExportPresetCommandResult"] | components["schemas"]["SaveExportPresetCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_set_cycle_active_api_v1_commands_set_cycle_active_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetCycleActiveCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SetCycleActiveCommandResult"] | components["schemas"]["SetCycleActiveCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_set_default_resume_api_v1_commands_set_default_resume_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetDefaultResumeCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SetDefaultResumeCommandResult"] | components["schemas"]["SetDefaultResumeCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_set_outcome_tag_api_v1_commands_set_outcome_tag_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetOutcomeTagCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SetOutcomeTagCommandResult"] | components["schemas"]["SetOutcomeTagCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_set_setting_api_v1_commands_set_setting_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetSettingCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SetSettingCommandResult"] | components["schemas"]["SetSettingCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_set_user_role_api_v1_commands_set_user_role_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetUserRoleCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SetUserRoleCommandResult"] | components["schemas"]["SetUserRoleCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_start_new_enrollment_api_v1_commands_start_new_enrollment_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StartNewEnrollmentCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StartNewEnrollmentCommandResult"] | components["schemas"]["StartNewEnrollmentCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_terminate_offer_api_v1_commands_terminate_offer_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TerminateOfferCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TerminateOfferCommandResult"] | components["schemas"]["TerminateOfferCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_unpublish_job_api_v1_commands_unpublish_job_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UnpublishJobCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UnpublishJobCommandResult"] | components["schemas"]["UnpublishJobCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_update_company_api_v1_commands_update_company_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateCompanyCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpdateCompanyCommandResult"] | components["schemas"]["UpdateCompanyCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_update_cycle_api_v1_commands_update_cycle_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateCycleCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpdateCycleCommandResult"] | components["schemas"]["UpdateCycleCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_update_cycle_policy_api_v1_commands_update_cycle_policy_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateCyclePolicyCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpdateCyclePolicyCommandResult"] | components["schemas"]["UpdateCyclePolicyCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_update_external_offer_api_v1_commands_update_external_offer_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateExternalOfferCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpdateExternalOfferCommandResult"] | components["schemas"]["UpdateExternalOfferCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_update_job_basics_api_v1_commands_update_job_basics_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateJobBasicsCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpdateJobBasicsCommandResult"] | components["schemas"]["UpdateJobBasicsCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_update_job_eligibility_api_v1_commands_update_job_eligibility_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateJobEligibilityCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpdateJobEligibilityCommandResult"] | components["schemas"]["UpdateJobEligibilityCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_update_resume_api_v1_commands_update_resume_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateResumeCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpdateResumeCommandResult"] | components["schemas"]["UpdateResumeCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_update_student_fields_api_v1_commands_update_student_fields_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateStudentFieldsCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpdateStudentFieldsCommandResult"] | components["schemas"]["UpdateStudentFieldsCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_update_template_api_v1_commands_update_template_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateTemplateCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpdateTemplateCommandResult"] | components["schemas"]["UpdateTemplateCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_upsert_job_questions_api_v1_commands_upsert_job_questions_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpsertJobQuestionsCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpsertJobQuestionsCommandResult"] | components["schemas"]["UpsertJobQuestionsCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_upsert_job_rounds_api_v1_commands_upsert_job_rounds_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpsertJobRoundsCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpsertJobRoundsCommandResult"] | components["schemas"]["UpsertJobRoundsCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_upsert_taxonomy_item_api_v1_commands_upsert_taxonomy_item_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpsertTaxonomyItemCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpsertTaxonomyItemCommandResult"] | components["schemas"]["UpsertTaxonomyItemCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_waitlist_applications_api_v1_commands_waitlist_applications_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WaitlistApplicationsCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WaitlistApplicationsCommandResult"] | components["schemas"]["WaitlistApplicationsCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_withdraw_application_api_v1_commands_withdraw_application_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WithdrawApplicationCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WithdrawApplicationCommandResult"] | components["schemas"]["WithdrawApplicationCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    command_withdraw_membership_api_v1_commands_withdraw_membership_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WithdrawMembershipCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WithdrawMembershipCommandResult"] | components["schemas"]["WithdrawMembershipCommandPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_status_api_v1_exports__export_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                export_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_download_api_v1_exports__export_id__download_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                export_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _portal_analytics_screen_api_v1_screens_admin_analytics_portal_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    _admin_bulk_upsert_screen_api_v1_screens_admin_bulk_upsert_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    _admin_discipline_screen_api_v1_screens_admin_discipline_get: {
        parameters: {
            query?: {
                enrollment_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _admin_findings_screen_api_v1_screens_admin_findings_get: {
        parameters: {
            query?: {
                invariant?: string | null;
                status?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_admin_overrides_api_v1_screens_admin_overrides_get: {
        parameters: {
            query?: {
                cycle_id?: string | null;
                rule_domain?: string | null;
                scope?: string | null;
                state?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _settings_screen_api_v1_screens_admin_settings_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    _taxonomies_screen_api_v1_screens_admin_taxonomies_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    _templates_screen_api_v1_screens_admin_templates_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    screen_admin_users_api_v1_screens_admin_users_get: {
        parameters: {
            query?: {
                include_inactive?: boolean;
                q?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_cycle__id__jobs_api_v1_screens_cycle__id__jobs_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_cycles_joinable_api_v1_screens_cycles_joinable_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    screen_job__id__api_v1_screens_job__id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_me_applications_api_v1_screens_me_applications_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    screen_me_dashboard_api_v1_screens_me_dashboard_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    screen_me_notifications_api_v1_screens_me_notifications_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    screen_me_profile_api_v1_screens_me_profile_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    _companies_screen_api_v1_screens_staff_companies_get: {
        parameters: {
            query?: {
                include_inactive?: boolean;
                q?: string | null;
                sector_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_staff_company__id__api_v1_screens_staff_company__id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_staff_cycle__id__api_v1_screens_staff_cycle__id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_staff_cycle__id__analytics_api_v1_screens_staff_cycle__id__analytics_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_staff_cycle__id__approvals_api_v1_screens_staff_cycle__id__approvals_get: {
        parameters: {
            query?: {
                status?: string;
            };
            header?: never;
            path: {
                id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_staff_cycle__id__external_api_v1_screens_staff_cycle__id__external_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_staff_cycle__id__jobs_api_v1_screens_staff_cycle__id__jobs_get: {
        parameters: {
            query?: {
                include_cancelled?: boolean;
            };
            header?: never;
            path: {
                id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_staff_cycles_api_v1_screens_staff_cycles_get: {
        parameters: {
            query?: {
                include_archived?: boolean;
                kind?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _staff_external_screen_api_v1_screens_staff_external_get: {
        parameters: {
            query?: {
                attached?: boolean | null;
                outcome?: string | null;
                q?: string | null;
                status?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_staff_job__id__analytics_api_v1_screens_staff_job__id__analytics_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_staff_job__id__board_api_v1_screens_staff_job__id__board_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_staff_job__id__builder_api_v1_screens_staff_job__id__builder_get: {
        parameters: {
            query: {
                cycle_id: string;
            };
            header?: never;
            path: {
                id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_staff_job__id__offers_api_v1_screens_staff_job__id__offers_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_staff_student__enrollment_id__api_v1_screens_staff_student__enrollment_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                enrollment_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _taxonomies_screen_api_v1_screens_staff_taxonomies_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    parse_profile_upload_api_v1_uploads_profile_rows_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_parse_profile_upload_api_v1_uploads_profile_rows_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    parse_venue_upload_api_v1_uploads_venue_rows_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_parse_venue_upload_api_v1_uploads_venue_rows_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    google_callback_auth_google_callback_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    google_login_auth_google_login_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    healthz_healthz_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    me_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    readyz_readyz_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
}
