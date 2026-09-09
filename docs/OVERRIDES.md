# Placement Portal exception catalogue — implementation audit

Audited against the implementation prepared for the initial public release. This is a static end-to-end audit of the command loaders/deciders, command registry, screen payloads, React routes/components, and relevant tests. It distinguishes the requested policy outcome from the mere presence of a similarly named control.

## Verdict

The nine override domains and all six ruled scope combinations are implemented in the backend and exposed in the browser:

- Domains: `eligibility`, `application_deadline`, `edit_window`, `withdraw_window`, `outcome_gate`, `offer_cap`, `offer_deadline`, `cycle_registration_window`, `cycle_join_rule`.
- Scopes: cycle, job, enrollment, cycle+enrollment, job+enrollment, and application.

Most catalogue rows are operable end to end. The exceptions are important:

| Kind | Scenarios | Finding |
|---|---|---|
| Not supported as requested | 5.7, 7.4, 8.5, 8.6 | There is no backend operation and therefore no browser operation for the requested result. |
| Supported only by a narrower/corrective workflow | 3.4, 3.6, 3.8, 4.8, 5.6, 6.3, 6.9, 7.8, 8.1 | The scenario is conditional or the catalogue's stated instrument over-promises. See the row. |
| Stale catalogue claim | 4.5, 4.6 | Remove and restore membership now both have browser controls routed to backend commands. |

In particular, **8.5 is not implemented by outcome tags**. A tag removes a membership only from the separate *registered (seeking only)* denominator. It does not remove a placement from the placed numerator and does not alter the headline placed/registered placement rate.

### Status notation

- **✅** — supported as an auditable backend command and reachable browser workflow.
- **⚠️** — some useful workflow exists, but not the whole operation as stated, or it has a material state restriction.
- **❌** — the requested operation cannot be performed through that layer.

“Backend” means a sanctioned command, not a direct database edit. All UI writes below use the command preview/execute API; none is a client-only mutation. Normal authorization, non-archived-cycle, and source-state prerequisites still apply. Some rows require a staff action followed by a student action; the portal has no impersonation feature.

## UI playbook and backend routing

The scenario tables refer to these playbook IDs. Each entry gives the browser path and the backend command reached by the confirmation action.

| ID | Browser steps | Backend command(s) |
|---|---|---|
| **UI-1 Profile correction** | As an admin, open **Admin → Discipline**, open the student's full record, select **Edit profile**, correct the fields, enter a reason, preview and confirm. Students can complete their own editable fields under **Profile**. Institute email is absent from both forms. | `admin_update_profile`; student form uses `declare_profile` / `update_student_fields` |
| **UI-2 Bulk profiles** | Open **Admin → Bulk upsert**, download/check the CSV shape, upload the corrected rows, review the row preview, and confirm. | `bulk_upsert_profiles` |
| **UI-3 Job basics/deadlines** | Open **Staff → Cycles → cycle → Jobs → job**, choose **Basics**, edit compensation or deadlines, then preview and confirm. Moving the acceptance deadline updates still-open offer rows and reschedules expiry. | `update_job_basics` |
| **UI-4 Eligibility rule** | Open the job as in UI-3, choose **Eligibility**, edit the rule/programme/primary-or-secondary-branch clauses, preview and confirm. | `update_job_eligibility` |
| **UI-5 Grant override** | Open the student's full record. Choose **Grant an override**, select the cycle or job target when needed, choose the domain, allow/deny, expiry and reason, then preview and confirm. For one existing application use **Applications → Grant application override** on that card. Job-only grants are also available on the job's **Eligibility** tab; cycle-only grants are available at **Admin → Overrides**. | `create_override` (and `deactivate_override` from **Admin → Overrides** when the grant should stop) |
| **UI-6 Apply/edit/withdraw** | As the student, open **Cycles → cycle → Jobs → job** and apply. To change or leave an existing application, open **My applications** and choose **Edit** or **Withdraw**. Buttons come from server `can_*` verdicts and appear after a matching override. | `apply`, `edit_application`, `withdraw_application` |
| **UI-7 Join/leave cycle** | As the student, open **Cycles** and choose **Join**, **Request again**, or **Withdraw** on the relevant cycle. If a registration/join override was just granted, refresh this screen before acting. | `join_cycle`, `rerequest_membership`, `withdraw_membership` |
| **UI-8 Membership staff action** | Open **Staff → Cycles → cycle → Approvals** (or the membership on the student's full record). Select **Approve**, **Reject**, **Remove**, or **Restore**, supply a reason where requested, and confirm. | `approve_memberships`, `reject_membership`, `remove_membership`, `restore_membership` |
| **UI-9 Pipeline result/intervention** | Open **Staff → cycle → Jobs → job → Board** and use row selection/round actions to advance, waitlist or eliminate. For a direct offer, open **Staff → job → Offers**, select the in-progress application and extend the offer. For **Reinstate** or **Force transition**, open the student's full record and its application card. Force transition requires a reason and intentionally performs no hidden cascade. | `finalize_round`, `extend_offers`, `reinstate_application`, `force_transition` |
| **UI-10 Attendance/venue** | On the job **Board**, choose the round, mark or bulk-paste attendance and confirm. Use the venue/timing uploader for new or corrected assignments; an existing assignment is emitted as an update. | `mark_attendance`, `bulk_mark_present`, `bulk_mark_absent`, `assign_venue_timing` |
| **UI-11 Student offer response** | As the student, open **Dashboard** and choose **Accept** or **Decline** on an offered application. A matching `offer_deadline`, `outcome_gate`, or `offer_cap` grant changes the server verdict; acceptance still performs the standard cascade. | `accept_offer`, `decline_offer` |
| **UI-12 Offer intervention** | Open **Staff → job → Offers**. On the offer choose **Terminate** or, for a declined/terminated offer, **Re-extend**; enter termination kind/reason, restoration choices, discipline choice, and/or a fresh deadline as shown, then confirm. | `terminate_offer`, `re_extend_offer` |
| **UI-13 Cancel job** | Open the staff job, choose the destructive **Cancel job** action, review the per-application preview, enter the reason, and confirm. | `cancel_job` |
| **UI-14 Rounds** | Open the staff job's **Rounds** tab, add/reorder/edit/remove rounds, then preview and confirm. A round that an application has already entered cannot be deleted. | `upsert_job_rounds` |
| **UI-15 Discipline** | Open **Admin → Discipline**, find the enrollment, then award/revoke a strike or penalty with the required reason. The same record links to the student's full history. | `award_strike`, `revoke_strike`, `award_penalty`, `revoke_penalty` |
| **UI-16 External offer** | Open **Staff → External offers**, create or edit the offer with source, outcome, status and actual compensation. Later open **Staff → cycle → External offers** to attach/detach it (single or bulk). Accepted external offers run the same placement gates/cascade; attaching an accepted offer runs the cycle cap gate. | `create_external_offer`, `update_external_offer`, `delete_external_offer`, `attach_external_offer`, `attach_external_offers`, `detach_external_offer` |
| **UI-17 Company repair** | Open **Staff → Companies → company**. Choose **Merge** and select the survivor, or choose **Activate** for an inactive company; preview and confirm. | `merge_companies`, `activate_company` |
| **UI-18 New enrollment** | Open **Admin → Users**, find the existing user and choose **Start new enrollment**; enter the new programme data and confirm. | `start_new_enrollment` |
| **UI-19 Outcome tag** | Open the cycle's **Approvals** roster or the student's cycle membership. Set **Higher studies**, **Entrepreneurship**, **Not seeking**, or clear the tag; confirm. | `set_outcome_tag` |

## 1. Eligibility

| # | Situation / expected instrument | Backend | Frontend | Audit and UI steps |
|---|---|---:|---:|---|
| 1.1 | Named student misses CPI cutoff — `eligibility` at job+enrollment | ✅ | ✅ | **UI-5:** student record → grant `eligibility` → select the job → allow; then the student uses **UI-6** to apply. The combined target is resolved by `apply`. |
| 1.2 | CPI is stale after semester results | ✅ | ✅ | **UI-1** to correct CPI; no override. New applications use the corrected profile. Existing applications deliberately retain their submission snapshot. |
| 1.3 | Cleared backlog not reflected | ✅ | ✅ | **UI-1** to correct backlog fields and reason, then apply normally through **UI-6**. |
| 1.4 | Company widens branch list for everyone | ✅ | ✅ | **UI-4** to edit the job rule. This correctly changes every subsequent eligibility verdict for that job. |
| 1.5 | Company widens branch list for one student | ✅ | ✅ | **UI-5** job+enrollment `eligibility` allow, then **UI-6**. |
| 1.6 | Medical leave shifted graduating year | ✅ | ✅ | **UI-1** to correct graduating year, then normal apply flow. |
| 1.7 | Returning from abroad; records temporarily incomplete | ✅ | ✅ | **UI-1** for facts that are known; **UI-5** cycle+enrollment `eligibility` allow for the temporary policy exception. The student then uses **UI-6**. This does not bypass profile completeness at cycle registration. |
| 1.8 | Branch changed mid-degree | ✅ | ✅ | **UI-1** to correct branch. Existing application snapshots remain historical. |
| 1.9 | PhD/non-standard programme sits for placements | ✅ | ✅ | For a real policy change use **UI-4** to add the programme; for one student use **UI-5** job+enrollment `eligibility`, then **UI-6**. |
| 1.10 | Rule-authoring error excludes intended students | ✅ | ✅ | **UI-4** to repair the rule. Using an override would conceal the incorrect source rule. |
| 1.11 | Missing 10th/12th records | ✅ | ✅ | Use **UI-1** when the values are known; otherwise **UI-5** cycle+enrollment `eligibility` is available as a temporary exception. Complete-profile requirements still cannot be overridden. |
| 1.12 | Dual-major student eligible through secondary branch | ✅ | ✅ | **UI-4** and add a secondary-branch rule clause. The backend rule evaluator supports secondary branch directly. |

## 2. Deadlines

| # | Situation / expected instrument | Backend | Frontend | Audit and UI steps |
|---|---|---:|---:|---|
| 2.1 | Medical emergency during application window | ✅ | ✅ | **UI-5** job+enrollment `application_deadline` allow; student refreshes and applies via **UI-6**. |
| 2.2 | Bereavement/hospitalisation/family emergency | ✅ | ✅ | Same as 2.1. |
| 2.3 | Travel/no connectivity | ✅ | ✅ | Same as 2.1. |
| 2.4 | Portal/campus network outage | ✅ | ✅ | Use **UI-5** from the job page for a job-scoped `application_deadline` allow, so every affected student can use **UI-6**. Deactivate it afterward if expiry was not set. |
| 2.5 | Company extends the real application deadline | ✅ | ✅ | **UI-3** to change the job's application deadline. In-flight students are notified. |
| 2.6 | Switch jobs after both have closed | ✅ | ✅ | On the old job grant job+enrollment `withdraw_window`; on the destination job grant job+enrollment `application_deadline` (**UI-5** twice). Student then withdraws the old application and applies to the new job (**UI-6**). |
| 2.7 | Fix answer typo after close | ✅ | ✅ | **UI-5** application-scoped `edit_window`; student opens **My applications → Edit** (**UI-6**). Only an `in_progress` application is editable. |
| 2.8 | Leave pipeline after withdrawal window | ✅ | ✅ | For an `in_progress` application, **UI-5** application `withdraw_window`, then **UI-6 → Withdraw**. Offered applications must be declined and accepted offers terminated; the withdrawal override does not change transition legality. |
| 2.9 | Response deadline elapsed while student unreachable | ✅ | ✅ | Two valid branches: if the offer is still open, grant application `offer_deadline` (**UI-5**) and the student responds in **UI-11**. If expiry already auto-declined it, use **UI-12 → Re-extend** with a fresh future deadline. A grant does not resurrect an expired offer, and re-extension accepts only declined/terminated offers. |
| 2.10 | Company verbally extends every open offer deadline | ✅ | ✅ | **UI-3** to change the job acceptance deadline. The backend propagates it to open offer rows and reschedules their expiry. |
| 2.11 | Student waits for another result past response deadline | ✅ | ✅ | Grant application `offer_deadline` before expiry (**UI-5**), then student responds in **UI-11**. If already auto-declined, use the 2.9 re-extension branch. |

## 3. Placement status and offer caps

| # | Situation / expected instrument | Backend | Frontend | Audit and UI steps |
|---|---|---:|---:|---|
| 3.1 | Placed student gets one dream-company attempt | ✅ | ✅ | **UI-5** job+enrollment `outcome_gate` allow; student uses **UI-6**. The same grant is considered if that application's offer is later accepted through **UI-11**. |
| 3.2 | Upgrade attempt after low package | ✅ | ✅ | Same as 3.1. Package comparison is office policy; the portal records the explicit grant rather than deriving “upgrade.” |
| 3.3 | Accepted company goes bankrupt/withdraws role | ✅ | ✅ | **UI-12 → Terminate**, choose an appropriate termination kind and restoration candidates. Placement is re-derived, so normal gates resume when no accepted placement remains. |
| 3.4 | Company defers joining by a year | ⚠️ | ⚠️ | **UI-12 → Terminate** is supported if the ruling is that the old offer no longer stands. The alternative “leave placed and record deferral” has no structured deferral field/status/command or UI; at most an external-offer/audit reason can serve as an informal convention. **Policy/product gap:** decide whether deferral remains placed and model it explicitly if it must be reportable. |
| 3.5 | Accepted PPO, then one dream-company attempt | ✅ | ✅ | Record/accept the PPO with **UI-16**, then grant job+enrollment `outcome_gate` using **UI-5** and apply via **UI-6**. If the PPO is attached to the same capped cycle and a second offer is to be accepted, `offer_cap` may also be required; an earlier PPO acceptance may also have auto-withdrawn an existing placement application. |
| 3.6 | Hold two offers briefly while deciding | ⚠️ | ⚠️ | Two unresolved `offered` rows can coexist already; `offer_cap` limits **accepted** offers and is irrelevant until acceptance. If “hold” means two accepted offers, first acceptance auto-declines the other same-outcome offer. Staff must grant both cycle+enrollment `offer_cap` **and** a suitable `outcome_gate` (**UI-5**), re-extend the auto-declined offer (**UI-12**), then the student accepts it (**UI-11**). There is no atomic “hold two accepted offers without cascade” operation. |
| 3.7 | Student reneges after accepting | ✅ | ✅ | **UI-12 → Terminate**, choose `student_renege`, and use the dialog's discipline choice or follow with **UI-15**. |
| 3.8 | Student allowed both roles at same company | ⚠️ | ⚠️ | Company identity has no special exemption. For two **accepted** roles of the same outcome, use the two-grant/re-extension sequence in 3.6. `offer_cap` alone is insufficient because the outcome gate and acceptance cascade also apply. |
| 3.9 | Internship converts to a full-time offer | ✅ | ✅ | **UI-16:** create an external offer with source PPO, outcome placement and the real status/compensation; attach it to the placement cycle if appropriate. Accepted status invokes placement derivation and cascade. |

## 4. Registration and cycle membership

| # | Situation / expected instrument | Backend | Frontend | Audit and UI steps |
|---|---|---:|---:|---|
| 4.1 | Missed registration by a day | ✅ | ✅ | **UI-5** cycle+enrollment `cycle_registration_window`; student then joins/re-requests through **UI-7**. |
| 4.2 | Opted out, then changed mind | ✅ | ✅ | Grant as in 4.1, then use **UI-7 → Request again**. The existing membership is re-requested rather than duplicated. |
| 4.3 | Fails cycle join rule but office wants them in | ✅ | ✅ | **UI-5** cycle+enrollment `cycle_join_rule`; student then joins/re-requests through **UI-7**. |
| 4.4 | Registration rejected in error | ✅ | ✅ | A rejected student uses **UI-7 → Request again**, then staff approve through **UI-8**. `restore_membership` itself accepts only `withdrawn`/`removed`, not `rejected`; therefore “restore rejected” is not a valid direct transition, but the complete correction workflow exists. |
| 4.5 | Remove student who left/is disciplined | ✅ | ✅ | **UI-8 → Remove** with reason. The catalogue's “no browser surface” note is stale: `MembershipExit` exposes this action on current staff membership/student-record screens and calls `remove_membership`. |
| 4.6 | Reinstate a removed student | ✅ | ✅ | **UI-8 → Restore** with reason. The catalogue's “no browser surface” note is stale; it calls `restore_membership`. |
| 4.7 | Student joined wrong cycle | ✅ | ✅ | Student withdraws the wrong membership and joins the correct cycle through **UI-7**. Staff removal/restoration is available through **UI-8** if an administrative correction is required. |
| 4.8 | Register despite incomplete profile | ⚠️ | ⚠️ | The requested exception does not exist: completeness is deliberately outside override domains and `join_cycle`/`rerequest_membership` reject it. The reachable corrective workflow is **UI-1** (admin) or **UI-2** (student) to complete the profile, then **UI-7**. **Policy gap as phrased:** there is no provisional/incomplete registration state. |

## 5. Discipline

| # | Situation / expected instrument | Backend | Frontend | Audit and UI steps |
|---|---|---:|---:|---|
| 5.1 | Strike for an excused absence | ✅ | ✅ | **UI-15 → Revoke strike**, with the correction reason. |
| 5.2 | Medical certificate after finalisation | ✅ | ✅ | Either revoke the resulting strike through **UI-15**, or correct attendance via **UI-10** and reinstate the rejected application to the selected round via **UI-9**. These are independent explicit corrections. |
| 5.3 | Successful penalty appeal | ✅ | ✅ | **UI-15 → Revoke penalty**, with reason. |
| 5.4 | One exception despite an active penalty | ✅ | ✅ | There is intentionally no penalty override. Revoke the penalty through **UI-15**, perform the now-sanctioned operation, and award a new penalty later only if policy genuinely calls for one. |
| 5.5 | Manual strike for non-absence offence | ✅ | ✅ | **UI-15 → Award strike**, choose/source the manual reason, preview and confirm. |
| 5.6 | Threshold reached but automatic conversion unwanted | ⚠️ | ⚠️ | **UI-15 → Revoke strike** drops the active support below threshold and dissolves an unsupported automatic penalty. There is no suppression flag that keeps every threshold-completing strike active while preventing conversion. “Award a penalty deliberately and revoke it” does not suppress the automatic conversion and is not an equivalent implementation. **Policy gap:** add an adjudicated/suppressed conversion state if all strikes must remain active. |
| 5.7 | Discipline follows student across enrollments | ❌ | ❌ | Strikes and penalties target `enrollment_id`; new enrollments neither inherit nor enforce old discipline. Admins can inspect history, but no command/global-person discipline target exists. **Ruled product gap**, not a dismissed scenario. |

## 6. Pipeline interventions

| # | Situation / expected instrument | Backend | Frontend | Audit and UI steps |
|---|---|---:|---:|---|
| 6.1 | Company reconsiders a rejected candidate | ✅ | ✅ | **UI-9 → Reinstate**, choose the destination round and confirm. Reinstatement supports rejected/withdrawn/auto-withdrawn source states. |
| 6.2 | Company skips rounds for strong candidate | ✅ | ✅ | On **UI-9**, select the in-progress application and extend/directly record the offer. `extend_offers` moves it to offered without fabricating intermediate round results. |
| 6.3 | Company cancels a round | ⚠️ | ⚠️ | **UI-14** can delete an **unused** round and notifies in-flight applicants about the process change. Once any application has entered that round, backend deletion is rejected and the UI cannot cancel it. **Product gap:** no first-class cancelled-round state or migration plan for applications already in that round. |
| 6.4 | Company adds a round mid-process | ✅ | ✅ | **UI-14** to insert/reorder the round and confirm. Applications retain their referenced round UUID; only the process order changes. |
| 6.5 | Attendance marked wrong | ✅ | ✅ | Correct it through **UI-10**. If finalisation rejected the student, follow with **UI-9 → Reinstate** to the intended round. |
| 6.6 | Venue/time changes late | ✅ | ✅ | Use **UI-10** to upload/assign the corrected venue and time. Existing assignments are marked and notified as updates. |
| 6.7 | Company pulls out entirely | ✅ | ✅ | **UI-13 → Cancel job**. Non-terminal applications are rejected and open offers are terminated. Accepted offers are deliberately left standing and require an explicit **UI-12 → Terminate** decision. |
| 6.8 | Company revokes offer before acceptance | ✅ | ✅ | **UI-12 → Terminate**, kind `company_revoked`, select restorations if offered, and confirm. |
| 6.9 | Wrong student advanced by paste error | ⚠️ | ⚠️ | **UI-9 → Eliminate** is available if rejection is the intended correction. `force_transition` changes application status only; it has no destination-round field and does not move `current_round_id` backward. Thus a true “undo advancement to the previous round” is unavailable in both layers. **Product gap:** add a reasoned move-to-round intervention if this must preserve the student in the pipeline. |
| 6.10 | Application state no normal action can repair | ✅ | ✅ | **UI-9 → Force transition**, select a different status, provide mandatory reason, preview and confirm. The backend intentionally performs no implicit offer, round, attendance, or cascade consequences; operators must repair those separately. |

## 7. Data corrections

| # | Situation / expected instrument | Backend | Frontend | Audit and UI steps |
|---|---|---:|---:|---|
| 7.1 | Semester CPI update | ✅ | ✅ | **UI-2** to upload, preview row changes and confirm. |
| 7.2 | One CPI is wrong | ✅ | ✅ | **UI-1** to correct it with an audit reason. |
| 7.3 | Roll/name/branch/programme wrong | ✅ | ✅ | **UI-1** to correct the enrollment/profile fields. |
| 7.4 | Institute email changed | ❌ | ❌ | `admin_update_profile` explicitly rejects email and no browser field exists. There is no user/session/notification-history migration command, so the requested identity correction cannot be made. **Deliberate product gap requiring a ruled migration workflow**, not a reason to edit the database directly. |
| 7.5 | Same person returns as MTech/PhD with same email | ✅ | ✅ | **UI-18 → Start new enrollment** on the existing user. This preserves one identity while creating a new enrollment. |
| 7.6 | Duplicate companies | ✅ | ✅ | **UI-17 → Merge**, select the survivor, review references and confirm. |
| 7.7 | Company deactivated in error | ✅ | ✅ | **UI-17 → Activate** and confirm. |
| 7.8 | Wrong resume link on application | ⚠️ | ⚠️ | While the application is `in_progress`, grant application `edit_window` if needed (**UI-5**), then student uses **UI-6 → Edit** and selects/pastes the correct resume. For `pending_offer`, `offered`, or terminal applications, `edit_application` remains illegal regardless of the window override; there is no staff-only resume correction command. |

## 8. Company-side and administrative

| # | Situation / expected instrument | Backend | Frontend | Audit and UI steps |
|---|---|---:|---:|---|
| 8.1 | Apply a company's exception to all its jobs | ⚠️ | ⚠️ | There is no company override scope or bulk grant command. Staff can repeat **UI-5** on each job, and every grant reaches `create_override`, but future jobs are not covered automatically. **Product gap:** decide whether company-wide inheritance and precedence are wanted. |
| 8.2 | Actual compensation differs from posting | ✅ | ✅ | If the posting is wrong, use **UI-3** to correct it. For an off-portal/PPO fact, use **UI-16** and record the actual figure on the external offer. |
| 8.3 | Off-campus offer needed in analytics | ✅ | ✅ | **UI-16 → Create**, source `off_campus`, outcome/status/compensation as known, then confirm. Accepted offers feed placement derivations. |
| 8.4 | PPO known before placement cycle exists | ✅ | ✅ | **UI-16** to create it unattached. When the dedicated cycle exists, open that cycle's external-offer screen and attach it; accepted attachment checks the cycle cap and may auto-create membership. |
| 8.5 | Exclude a student's placement from placement rate | ❌ | ❌ | **UI-19 exists but does not implement this result.** `set_outcome_tag` removes the member only from the seeking-only **denominator**. The placed numerator is unchanged, and headline `placement_rate = placed / registered` is unchanged. A placed tagged member can even make the seeking-only ratio exceed 100%. **Analytics-policy gap:** model an explicit placement exclusion (with reason/audit) or redefine the metric; do not present an outcome tag as the solution. |
| 8.6 | Correct an archived cycle | ❌ | ❌ | Archived cycles are centrally read-only. There is `archive_cycle` but no unarchive command, no correction exception, and no browser action. **Ruled product gap:** define an audited reopen/correction mechanism if this operational case must be supported. |

## Gap register / decisions required

These are the cases for which operator training alone is insufficient:

1. **Deferral (3.4):** define whether a deferred offer remains accepted/placed and add structured dates/status if it must be reported.
2. **Multiple accepted offers (3.6, 3.8):** clarify whether the standard acceptance cascade should be suppressible. Today two grants plus re-extension can create the state, but there is no atomic “hold” action.
3. **Provisional registration (4.8):** decide whether incomplete profiles may enter a provisional membership state; currently they must be completed first.
4. **Threshold adjudication (5.6):** decide whether active strikes may be retained while suppressing their automatic conversion.
5. **Cross-enrollment discipline (5.7):** add a person-level/transfer policy if visibility of old discipline is not enough.
6. **Round cancellation/undo (6.3, 6.9):** model cancelled rounds and a reasoned move-to-round intervention if already-entered rounds and paste-error rollback must be supported.
7. **Identity email migration (7.4):** define migration of login identity, sessions, staged rows and notification/audit references.
8. **Late resume repair (7.8):** decide whether staff may correct an immutable application artifact after `in_progress`.
9. **Company override scope (8.1):** add company targeting/bulk inheritance if per-job grants are operationally inadequate.
10. **Placement-rate exclusion (8.5):** outcome tags are not numerator exclusions; this needs an analytics ruling and a distinct audited fact.
11. **Archived-cycle repair (8.6):** add a controlled reopen/correction command or retain the current hard prohibition.

## Implementation evidence

The central contracts inspected for this audit are:

- Override domains/scopes and precedence: `backend/app/domain/shared.py`, `backend/app/modules/overrides/{commands,service,queries,screens}.py`
- Gate enforcement: `backend/app/domain/gates.py`
- Profile and identity correction: `backend/app/modules/profiles/`, `backend/app/modules/identity/admin_commands.py`
- Applications, rounds and attendance: `backend/app/modules/applications/`
- Job editing/cancellation: `backend/app/modules/jobs/`
- Offer response/intervention/external offers: `backend/app/modules/offers/`
- Memberships and discipline: `backend/app/modules/cycles/memberships.py`, `backend/app/modules/discipline/`
- Placement-rate semantics: `backend/app/modules/analytics/{metrics,reports}.py`
- Browser reachability and routes: `frontend/src/App.tsx`
- Override, membership and outcome-tag controls: `frontend/src/components/{GrantOverride,MembershipExit,OutcomeTag}.tsx`
- Staff/student screens: `frontend/src/screens/`

The frontend's command dependency map (`frontend/src/api/screenDeps.ts`) includes the sanctioned writes above, so successful confirmations invalidate/refetch their server screens rather than simulating state locally.

### Validation run

Validation for the public-release tree passed: Ruff and Pyright were clean, all 1,870 backend tests passed, the frontend production build completed, all 175 frontend unit/component tests passed, and all 33 rebuilt Playwright flows passed. Browser reachability in this document is supported by the route/component/command audit and the rebuilt browser suite.
