import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Me } from "@/api/client";
import type {
  AdminFindingsPayload,
  BuilderPayload,
  DisciplinePayload,
  StaffJobBoardPayload,
  StaffJobOffersPayload,
  StudentJobPayload,
  StudentRecordPayload,
} from "@/api/payloads";
import { mockScreens, renderScreen } from "@/test/harness";
import adminDiscipline from "@/test/fixtures/admin-discipline.json";
import adminFindings from "@/test/fixtures/admin-findings.json";
import adminOverrides from "@/test/fixtures/admin-overrides.json";
import adminSettings from "@/test/fixtures/admin-settings.json";
import adminTaxonomies from "@/test/fixtures/admin-taxonomies.json";
import adminTemplates from "@/test/fixtures/admin-templates.json";
import approvals from "@/test/fixtures/approvals.json";
import builder from "@/test/fixtures/builder.json";
import ids from "@/test/fixtures/ids.json";
import joinable from "@/test/fixtures/joinable.json";
import meApplications from "@/test/fixtures/me-applications.json";
import meDashboard from "@/test/fixtures/me-dashboard.json";
import staffCompanies from "@/test/fixtures/staff-companies.json";
import staffCompany from "@/test/fixtures/staff-company.json";
import staffCycle from "@/test/fixtures/staff-cycle.json";
import staffCycleExternal from "@/test/fixtures/staff-cycle-external.json";
import staffCycleJobs from "@/test/fixtures/staff-cycle-jobs.json";
import staffCycles from "@/test/fixtures/staff-cycles.json";
import staffExternal from "@/test/fixtures/staff-external.json";
import staffJobBoard from "@/test/fixtures/staff-job-board.json";
import staffJobBoardOpen from "@/test/fixtures/staff-job-board-open.json";
import staffJobOffers from "@/test/fixtures/staff-job-offers.json";
import staffJobOffersCascade from "@/test/fixtures/staff-job-offers-cascade.json";
import studentJob from "@/test/fixtures/student-job.json";
import studentJobs from "@/test/fixtures/student-jobs.json";
import staffStudent from "@/test/fixtures/staff-student.json";

import { Discipline } from "./admin/Discipline";
import { Findings } from "./admin/Findings";
import { Overrides } from "./admin/Overrides";
import { Settings } from "./admin/Settings";
import { Taxonomies } from "./admin/Taxonomies";
import { Templates } from "./admin/Templates";
import { Companies } from "./companies/Companies";
import { Company } from "./companies/Company";
import { Approvals } from "./cycles/Approvals";
import { StaffCycle } from "./cycles/StaffCycle";
import { StaffCycles } from "./cycles/StaffCycles";
import { Home } from "./Home";
import { CycleJobs } from "./jobs/CycleJobs";
import { JobBoard } from "./jobs/JobBoard";
import { JobBuilder } from "./jobs/JobBuilder";
import { CycleExternal } from "./offers/CycleExternal";
import { ExternalOffers } from "./offers/ExternalOffers";
import { Offers } from "./offers/Offers";
import { Dashboard } from "./student/Dashboard";
import { MyApplications } from "./student/MyApplications";
import { MyNotifications } from "./student/MyNotifications";
import { StudentCycles } from "./student/StudentCycles";
import { StudentJob } from "./student/StudentJob";
import { StudentJobs } from "./student/StudentJobs";
import { StudentRecord } from "./student/StudentRecord";

/**
 * Every implemented screen, rendered against the payload the server really sends.
 *
 * The fixtures are captured from a seeded database rather than written here, so
 * these tests fail when a screen reads a field the backend does not send — the
 * front-end half of the same gap `backend/tests/test_screen_execution.py`
 * closes on the server side. A screen that renders only against a fixture
 * somebody invented proves nothing about the real payload.
 */

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("admin screens", () => {
  it("lists the taxonomies and the branches each program admits", async () => {
    mockScreens({ "screens/admin/taxonomies": adminTaxonomies });
    renderScreen(<Taxonomies />);

    expect(await screen.findByRole("heading", { name: "Taxonomies" })).toBeInTheDocument();
    // Programs is the default tab, and it renders the branches each admits.
    expect(await screen.findByText("BTech")).toBeInTheDocument();
    // The branch appears twice on purpose: once as a checkbox on the add form,
    // once in the mapped-branches column of the programs table.
    expect(
      (await screen.findAllByText(/Computer Science and Engineering/)).length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("names every setting, including the ones with no override", async () => {
    mockScreens({ "screens/admin/settings": adminSettings });
    renderScreen(<Settings />);

    expect(await screen.findByLabelText(/Notification sender address/)).toBeInTheDocument();
    // The seed sets only ses_sender; the other two must still be listed, with
    // the code default named rather than left invisible.
    expect(await screen.findByLabelText(/Strikes per penalty/)).toBeInTheDocument();
    expect(
      (await screen.findAllByText(/the code default is in force/)).length,
    ).toBeGreaterThan(0);
  });

  it("edits global and per-cycle notification templates and exposes dead letters", async () => {
    mockScreens({ "screens/admin/templates": adminTemplates });
    renderScreen(<Templates />, { path: "/admin/templates", route: "/admin/templates" });

    expect(
      await screen.findByRole("heading", { name: "Notification templates" }),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText("Subject")).toHaveValue(
      "Offer extended: {job} at {company}",
    );
    expect(await screen.findByText(/\{student\}, \{job\}, \{company\}/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Save template" })).toBeEnabled();
    expect(await screen.findByRole("button", { name: "Resend" })).toBeEnabled();
  });

  it("shows the discipline roster and the selected student's full record", async () => {
    mockScreens({ "screens/admin/discipline": adminDiscipline });
    renderScreen(<Discipline />, {
      path: "/admin/discipline",
      route: `/admin/discipline?enrollment_id=${adminDiscipline.student.enrollment_id}`,
    });

    expect(await screen.findByRole("heading", { name: "Discipline" })).toBeInTheDocument();
    expect(await screen.findByText("Missed the coordinator follow-up")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Award strike" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Award penalty" })).toBeInTheDocument();
    expect(await screen.findAllByRole("button", { name: "Revoke" })).toHaveLength(3);
  });

  it("lists live and deactivated overrides and exposes the server's deactivate verdict", async () => {
    mockScreens({ "screens/admin/overrides": adminOverrides });
    renderScreen(<Overrides />, { path: "/admin/overrides", route: "/admin/overrides" });

    expect(await screen.findByRole("heading", { name: "Overrides" })).toBeInTheDocument();
    expect(await screen.findByText("Company extended their own deadline by a day")).toBeInTheDocument();
    expect(await screen.findByText("Cap frozen while external offers were reconciled")).toBeInTheDocument();
    expect((await screen.findAllByText("Active")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Deactivated")).length).toBeGreaterThan(0);
    expect(await screen.findByRole("button", { name: "Deactivate" })).toBeEnabled();
    expect(await screen.findByRole("button", { name: "Grant override" })).toBeEnabled();
  });

  it("renders and launches a real expiry fallback finding with its catalog-built fix", async () => {
    mockScreens({
      "screens/admin/findings": adminFindings,
      "commands/re_extend_offer": {
        summary: { status: "offered", deadline_at: null, notify: true },
        events: [],
      },
    });
    renderScreen(<Findings />, { path: "/admin/findings", route: "/admin/findings" });

    expect(await screen.findByRole("heading", { name: "Findings" })).toBeInTheDocument();
    expect(await screen.findByText(/Auto-accept fell back to decline/)).toBeInTheDocument();
    const launch = await screen.findByRole("button", { name: "Apply suggested fix" });
    expect(launch).toBeEnabled();
    expect(await screen.findByRole("button", { name: "Resolve" })).toBeEnabled();
    expect(await screen.findByRole("button", { name: "Dismiss" })).toBeEnabled();
    fireEvent.click(launch);
    expect(await screen.findByRole("heading", { name: "Run re_extend_offer?" })).toBeInTheDocument();
    expect(await screen.findByText("offered", { exact: true })).toBeInTheDocument();
  });

  it("runs the consistency checker on demand and previews what it found", async () => {
    // the design review §4.36: an administrator who has just compensated a finding
    // needs to see it clear rather than wait for 03:00. The dry run is the
    // whole check and writes nothing, so the preview answers that question
    // before anything is recorded.
    mockScreens({
      "screens/admin/findings": adminFindings,
      "commands/run_consistency_checker": {
        summary: {
          checked_invariants: 12,
          violations: 1,
          findings_opened: 1,
          findings_reopened: 0,
          findings_auto_resolved: 0,
          by_invariant: [
            { invariant: "offer_cap_respected", violations: 1 },
            { invariant: "one_current_enrollment", violations: 0 },
          ],
          sessions_purged: 3,
          reminder_sends_purged: 0,
        },
        events: [],
      },
    });
    renderScreen(<Findings />, { path: "/admin/findings", route: "/admin/findings" });

    fireEvent.click(await screen.findByRole("button", { name: "Run now" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByRole("heading", { name: "Run the consistency checker now?" }),
    ).toBeInTheDocument();
    // Named, never reduced to a count: "one violation" says nothing about
    // which promise stopped being kept.
    expect(await within(dialog).findByText("offer_cap_respected")).toBeInTheDocument();
    expect(within(dialog).queryByText("one_current_enrollment")).not.toBeInTheDocument();
    expect(within(dialog).getByText(/3 expired sessions/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Run the checker" })).toBeEnabled();
  });

  it("names a finding's subject instead of printing its ids", async () => {
    // A finding stores ids because a name can be edited or merged away, but an
    // administrator deciding whether to resolve one cannot recognise a UUID.
    // The id stays available behind the copy control; it is not the subject.
    mockScreens({ "screens/admin/findings": adminFindings });
    renderScreen(<Findings />, { path: "/admin/findings", route: "/admin/findings" });

    const finding = (adminFindings as unknown as AdminFindingsPayload).findings[0]!;
    for (const label of Object.values(finding.subject_labels)) {
      expect((await screen.findAllByText(label)).length).toBeGreaterThan(0);
    }
    for (const [key, value] of Object.entries(finding.subject)) {
      if (key in finding.subject_labels) {
        expect(screen.queryByText(String(value))).not.toBeInTheDocument();
      }
    }
    expect((await screen.findAllByRole("button", { name: /^Copy identifier/ })).length).toBe(
      Object.keys(finding.subject_labels).length,
    );
  });

  it("uses the server's discipline permission to disable a revoke control", async () => {
    const body = structuredClone(adminDiscipline) as unknown as DisciplinePayload;
    const student = body.student!;
    student.strikes[0]!.actions.revoke = {
      allowed: false,
      reason: "strike_already_revoked",
      human: "That strike is already revoked",
    };
    mockScreens({ "screens/admin/discipline": body });
    renderScreen(<Discipline />, {
      path: "/admin/discipline",
      route: `/admin/discipline?enrollment_id=${student.enrollment_id}`,
    });

    const revoke = await screen.findAllByRole("button", { name: "Revoke" });
    expect(revoke.filter((button) => button.hasAttribute("disabled"))).toHaveLength(1);
  });
});

describe("student drill-down", () => {
  it("renders audit field changes with their labels and before/after values", async () => {
    const body = structuredClone(staffStudent) as unknown as StudentRecordPayload;
    const enrollmentId = body.enrollment!.id;
    body.audit[0] = {
      ...body.audit[0]!,
      action: "profile_field_change",
      details: { field: "cpi", before: "9.10", after: "9.12" },
    };
    mockScreens({ [`screens/staff/student/${enrollmentId}`]: body });
    renderScreen(<StudentRecord />, {
      path: "/staff/student/:enrollmentId",
      route: `/staff/student/${enrollmentId}`,
    });

    const action = await screen.findByText("Profile field change");
    expect(action.closest("li")).toHaveTextContent("CPI: 9.10 → 9.12");
  });

  it("keeps every non-field audit detail available in a compact disclosure", async () => {
    const enrollmentId = staffStudent.enrollment!.id;
    mockScreens({ [`screens/staff/student/${enrollmentId}`]: staffStudent });
    renderScreen(<StudentRecord />, {
      path: "/staff/student/:enrollmentId",
      route: `/staff/student/${enrollmentId}`,
    });

    const action = (await screen.findAllByText("Create external offer"))[0]!;
    const auditRow = action.closest("li")!;
    fireEvent.click(within(auditRow).getByText(/^Details/));
    expect(within(auditRow).getByText(/Development seed: seed: accepted PPO/)).toBeVisible();
    expect(within(auditRow).getByText("External offer ID")).toBeVisible();
    expect(within(auditRow).getAllByText("Create external offer", { exact: true })).toHaveLength(2);
  });

  it("shows snapshot drift, full timelines, interventions and enrollment audit rows", async () => {
    const enrollmentId = staffStudent.enrollment!.id;
    mockScreens({ [`screens/staff/student/${enrollmentId}`]: staffStudent });
    renderScreen(<StudentRecord />, {
      path: "/staff/student/:enrollmentId",
      route: `/staff/student/${enrollmentId}`,
    });

    expect(await screen.findByRole("heading", { name: "Asha Mehta" })).toBeInTheDocument();
    expect(await screen.findByLabelText("Enrollment")).toHaveValue(enrollmentId);
    expect((await screen.findAllByText("9.10", { exact: true })).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("9.12", { exact: true })).length).toBeGreaterThan(0);
    expect(
      (await screen.findAllByText("Development seed correction with restoration")).length,
    ).toBeGreaterThan(0);
    expect((await screen.findAllByRole("button", { name: "Reinstate" })).length).toBe(
      staffStudent.applications.length,
    );
    expect((await screen.findAllByRole("button", { name: "Force transition" })).length).toBe(
      staffStudent.applications.length,
    );
    // These actions have no application event when no source application exists;
    // the enrollment audit trail is the only complete account.
    expect((await screen.findAllByText("Create external offer")).length).toBeGreaterThan(0);
    expect(await screen.findByText(/PPO · Placement/)).toBeInTheDocument();
    expect(screen.queryByText(/Ppo/)).not.toBeInTheDocument();
    // the design review §4.35: the event payload is rendered, not merely delivered.
    // An override is a rule set aside for one student, and "why was this
    // person allowed in" is answered on the row or nowhere.
    expect(
      await screen.findByText(
        /Eligibility requirement waived — override granted by CDS Administrator.*reason: Development seed: company asked for this student by name/,
      ),
    ).toBeInTheDocument();
  });

  it("offers every admin-managed field, seeded, and can clear one", async () => {
    // INT-1's correction path. The dialog has to reach a locked field the
    // student cannot touch and the bulk upsert will not clear, and it has to
    // arrive holding what is true now rather than an empty form somebody could
    // save over the record by accident.
    const enrollmentId = staffStudent.enrollment!.id;
    const mocked = mockScreens({
      [`screens/staff/student/${enrollmentId}`]: staffStudent,
      "commands/admin_update_profile": {
        summary: { enrollment_id: enrollmentId, changed_fields: ["cpi"] },
        events: [],
      },
    });
    renderScreen(<StudentRecord />, {
      path: "/staff/student/:enrollmentId",
      route: `/staff/student/${enrollmentId}`,
    });

    fireEvent.click(await screen.findByRole("button", { name: "Edit profile" }));
    const dialog = await screen.findByRole("dialog");
    const body = staffStudent as unknown as StudentRecordPayload;
    const adminFields = body.profile.fields.filter((field) => field.admin_editable);
    expect(adminFields.length).toBeGreaterThan(0);
    for (const field of adminFields) {
      expect(within(dialog).getByLabelText(new RegExp(`^${field.label}`))).toBeInTheDocument();
    }
    expect(within(dialog).getByLabelText(/^CPI/)).toHaveValue(9.12);

    fireEvent.change(within(dialog).getByLabelText(/^CPI/), { target: { value: "" } });
    // The preview names the field, rather than flattening the server's
    // `changed_fields` list to the number the operator already knows.
    expect(await within(dialog).findByText("CPI changes")).toBeInTheDocument();
    await waitFor(() => {
      const previews = mocked.posted("admin_update_profile");
      expect(previews.length).toBeGreaterThan(0);
      const last = previews.at(-1)!;
      const fields = last.fields as Record<string, unknown>;
      // Cleared, not omitted: an omitted key leaves the column as it was.
      expect(fields.cpi).toBeNull();
      // And the rest of the record travels with it, unchanged.
      expect(fields.roll_number).toBe("21110001");
      expect(fields.graduating_year).toBe("2026");
    });
  });

  it("tags a membership's ANA-3 outcome from the record", async () => {
    const enrollmentId = staffStudent.enrollment!.id;
    const mocked = mockScreens({
      [`screens/staff/student/${enrollmentId}`]: staffStudent,
      "commands/set_outcome_tag": {
        summary: {
          cycle_id: staffStudent.memberships[0]!.cycle.id,
          membership_id: staffStudent.memberships[0]!.id,
          outcome_tag: "higher_studies",
          changed: true,
        },
        events: [],
      },
    });
    renderScreen(<StudentRecord />, {
      path: "/staff/student/:enrollmentId",
      route: `/staff/student/${enrollmentId}`,
    });

    const untagged = await screen.findAllByRole("button", { name: "Not tagged" });
    expect(untagged.length).toBe(staffStudent.memberships.length);
    fireEvent.click(untagged[0]!);
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/^Outcome/), {
      target: { value: "higher_studies" },
    });
    await waitFor(() => {
      const posted = mocked.posted("set_outcome_tag").at(-1);
      expect(posted?.outcome_tag).toBe("higher_studies");
      expect(posted?.membership_id).toBe(staffStudent.memberships[0]!.id);
    });
  });

  it("uses server permissions and domains for enrollment and application overrides", async () => {
    const body = structuredClone(staffStudent) as unknown as StudentRecordPayload;
    const enrollmentId = body.enrollment!.id;
    body.override_domains = [
      "eligibility",
      "application_deadline",
      "edit_window",
      "withdraw_window",
      "outcome_gate",
      "offer_cap",
      "offer_deadline",
      "cycle_registration_window",
      "cycle_join_rule",
    ];
    body.actions.grant_enrollment_override = {
      allowed: false,
      reason: "out_of_scope",
      human: "An enrollment override applies in every cycle, so only an administrator may grant one",
    };
    for (const application of body.applications) {
      application.override_domains = [
        "edit_window",
        "withdraw_window",
        "outcome_gate",
        "offer_cap",
        "offer_deadline",
      ];
      application.actions.grant_override = {
        allowed: true,
        reason: null,
        human: null,
      };
    }
    const mocked = mockScreens({
      [`screens/staff/student/${enrollmentId}`]: body,
      "commands/create_override": {
        summary: {
          override_id: "10000000-0000-4000-8000-000000000001",
          rule_domain: "edit_window",
          allow: true,
          scope: "application",
          subject_id: body.applications[0]!.id,
          is_active: true,
          expires_at: null,
        },
        events: [],
      },
    });
    renderScreen(<StudentRecord />, {
      path: "/staff/student/:enrollmentId",
      route: `/staff/student/${enrollmentId}`,
    });

    const enrollmentGrant = await screen.findByRole("button", {
      name: "Grant an override",
    });
    expect(enrollmentGrant).toBeDisabled();
    expect(enrollmentGrant).toHaveAttribute(
      "title",
      body.actions.grant_enrollment_override.human,
    );

    const application = body.applications[0]!;
    const card = screen.getByRole("region", { name: application.job_title });
    fireEvent.click(
      within(card).getByRole("button", { name: "Grant application override" }),
    );
    const dialog = await screen.findByRole("dialog");
    const domain = within(dialog).getByRole("combobox", {
      name: "Rule domain *",
    });
    expect(within(domain).queryByRole("option", { name: "Eligibility" })).toBeNull();
    expect(
      within(domain).queryByRole("option", { name: "Application deadline" }),
    ).toBeNull();
    // PreviewConfirm contributes the disabled "Select…" placeholder.
    expect(within(domain).getAllByRole("option")).toHaveLength(6);
    expect(domain).toHaveValue("edit_window");
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Reason *" }), {
      target: { value: "Application-specific exception" },
    });
    await waitFor(() => {
      expect(mocked.posted("create_override").at(-1)).toMatchObject({
        cycle_id: application.cycle.id,
        application_id: application.id,
        rule_domain: "edit_window",
      });
    });
  });

  it("grants a pre-application student-plus-job override from an authorized picker", async () => {
    const body = structuredClone(staffStudent) as unknown as StudentRecordPayload;
    const enrollmentId = body.enrollment!.id;
    const application = body.applications[0]!;
    body.override_targets = {
      cycle_domains: [],
      job_domains: [
        "eligibility",
        "application_deadline",
        "edit_window",
        "withdraw_window",
        "outcome_gate",
        "offer_cap",
        "offer_deadline",
      ],
      cycles: [],
      jobs: [
        {
          id: application.job_id,
          title: application.job_title,
          company_name: application.company_name,
          cycle: {
            id: application.cycle.id,
            name: application.cycle.name,
          },
        },
      ],
    };
    const mocked = mockScreens({
      [`screens/staff/student/${enrollmentId}`]: body,
      "commands/create_override": {
        summary: {
          override_id: "10000000-0000-4000-8000-000000000003",
          rule_domain: "eligibility",
          allow: true,
          scope: "job+enrollment",
          subject_id: application.job_id,
          is_active: true,
          expires_at: null,
        },
        events: [],
      },
    });
    renderScreen(<StudentRecord />, {
      path: "/staff/student/:enrollmentId",
      route: `/staff/student/${enrollmentId}`,
    });

    fireEvent.click(
      await screen.findByRole("button", { name: "Grant job override" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Job *")).toHaveValue(application.job_id);
    expect(within(dialog).queryByRole("option", { name: "Cycle join rule" })).toBeNull();
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Reason *" }), {
      target: { value: "Company requested this student" },
    });

    await waitFor(() => {
      expect(mocked.posted("create_override").at(-1)).toMatchObject({
        cycle_id: application.cycle.id,
        job_id: application.job_id,
        enrollment_id: enrollmentId,
        rule_domain: "eligibility",
      });
    });
  });

  it("shows the tag read-only where the server withholds the permission", async () => {
    const body = structuredClone(staffStudent) as unknown as StudentRecordPayload;
    const enrollmentId = body.enrollment!.id;
    body.actions.edit_profile = {
      allowed: false,
      reason: null,
      human: "Only an administrator can correct a locked profile field",
    };
    for (const membership of body.memberships) {
      membership.actions.set_outcome_tag = {
        allowed: false,
        reason: "cycle_archived",
        human: "The cycle is archived and is now read-only",
      };
    }
    body.memberships[0]!.outcome_tag = "not_seeking";
    mockScreens({ [`screens/staff/student/${enrollmentId}`]: body });
    renderScreen(<StudentRecord />, {
      path: "/staff/student/:enrollmentId",
      route: `/staff/student/${enrollmentId}`,
    });

    expect(await screen.findByRole("heading", { name: "Asha Mehta" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit profile" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Not tagged" })).not.toBeInTheDocument();
    expect((await screen.findAllByText("Not seeking")).length).toBe(1);
  });
});

describe("the notification feed", () => {
  const feed = {
    notifications: [
      {
        id: "aa000000-0000-4000-8000-000000000001",
        event_key: "venue_timing",
        subject: "Schedule published for Online Assessment",
        status: "sent",
        sent_at: "2027-07-01T04:00:00+00:00",
        recorded_at: "2027-07-01T04:00:00+00:00",
      },
      {
        id: "aa000000-0000-4000-8000-000000000002",
        event_key: "offer_extended",
        subject: "Offer extended: Backend Engineer at Acme",
        status: "dead",
        sent_at: null,
        recorded_at: "2027-07-02T05:30:00+00:00",
      },
    ],
  };

  it("shows what was sent, and says plainly when something never arrived", async () => {
    // LLD §18: the student who deletes an email, or never gets one, had no
    // way to find out what the portal told them. A notice that gave up is
    // exactly what brings someone to the CDS office, so it is listed rather
    // than hidden until delivery succeeds.
    mockScreens({ "me/notifications": feed });
    renderScreen(<MyNotifications />, { path: "/notifications", route: "/notifications" });

    expect(await screen.findByRole("heading", { name: "Notifications" })).toBeInTheDocument();
    // Scoped per row: "Sent" is also a column header, and a status read off
    // the wrong row is the one mistake this screen cannot afford.
    const delivered = screen
      .getByText("Schedule published for Online Assessment")
      .closest("tr")!;
    // The event key is humanised, never printed as a wire token.
    expect(within(delivered).getByText("Venue timing")).toBeInTheDocument();
    expect(within(delivered).getByText("Sent")).toBeInTheDocument();

    const undelivered = screen
      .getByText("Offer extended: Backend Engineer at Acme")
      .closest("tr")!;
    expect(within(undelivered).getByText("Not delivered")).toBeInTheDocument();
    expect(within(undelivered).getByText(/Not yet — recorded/)).toBeInTheDocument();
  });

  it("says nothing has been sent rather than rendering an empty table", async () => {
    mockScreens({ "me/notifications": { notifications: [] } });
    renderScreen(<MyNotifications />, { path: "/notifications", route: "/notifications" });

    expect(
      await screen.findByText("The portal has not emailed you yet."),
    ).toBeInTheDocument();
  });
});

describe("cycle screens", () => {
  it("lists cycles with their counts", async () => {
    mockScreens({ "screens/staff/cycles": staffCycles });
    renderScreen(<StaffCycles />);

    expect(await screen.findByRole("link", { name: "Placement 2026" })).toBeInTheDocument();
    expect(await screen.findByText("Summer Internship 2026")).toBeInTheDocument();
  });

  it("shows the policy with the source of each value", async () => {
    mockScreens({ [`screens/staff/cycle/${ids.cycle_id}`]: staffCycle });
    renderScreen(<StaffCycle />, {
      path: "/staff/cycles/:id",
      route: `/staff/cycles/${ids.cycle_id}`,
    });

    expect(await screen.findByRole("heading", { name: "Placement 2026" })).toBeInTheDocument();
    expect(await screen.findByLabelText(/Accepted-offer cap/)).toBeInTheDocument();
    // A policy row must say whether the value is the cycle's or an inherited
    // default; a bare checkbox would say nothing about which.
    expect((await screen.findAllByText(/Set on this cycle|Inherited from/)).length).toBeGreaterThan(
      0,
    );
  });

  it("names every application affected or bypassed by cycle archival", async () => {
    mockScreens({
      [`screens/staff/cycle/${ids.cycle_id}`]: staffCycle,
      "commands/archive_cycle": {
        summary: {
          auto_withdrawn: [
            {
              application_id: "withdrawn-app",
              full_name: "Asha Mehta",
              job: "Backend Engineer",
              from_status: "in_progress",
            },
          ],
          untouched: [
            {
              application_id: "accepted-app",
              full_name: "Demo Student 04",
              job: "Platform Engineer",
              status: "accepted",
              suggested_command: "terminate_offer",
            },
          ],
        },
        events: [],
      },
    });
    renderScreen(<StaffCycle />, {
      path: "/staff/cycles/:id",
      route: `/staff/cycles/${ids.cycle_id}`,
    });

    fireEvent.click(await screen.findByRole("button", { name: "Archive" }));
    const dialog = await screen.findByRole("dialog");
    const withdrawn = within(dialog).getByText(/Asha Mehta.*Backend Engineer/).closest("li")!;
    expect(withdrawn).toHaveTextContent(/Backend Engineer.*in progress/);
    const accepted = within(dialog)
      .getByText(/Demo Student 04.*Platform Engineer/)
      .closest("li")!;
    expect(accepted).toHaveTextContent(/Platform Engineer.*accepted.*use terminate offer/);
    expect(within(dialog).queryByText("withdrawn-app")).not.toBeInTheDocument();
  });

  it("puts the pending queue in a bulk bar with per-row rejection", async () => {
    mockScreens({ "approvals": approvals });
    renderScreen(<Approvals />, {
      path: "/staff/cycles/:id/approvals",
      route: `/staff/cycles/${ids.cycle_id}/approvals`,
    });

    expect(await screen.findByRole("heading", { name: "Approvals" })).toBeInTheDocument();
    // The seed leaves two students waiting; both must be selectable.
    const rows = approvals.rows as { full_name: string; status: string }[];
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(await screen.findByLabelText(`Select ${row.full_name}`)).toBeInTheDocument();
    }
    expect(await screen.findByRole("button", { name: "Approve selected" })).toBeDisabled();
    const pending = rows.filter((row) => row.status === "pending");
    expect((await screen.findAllByRole("button", { name: "Reject" })).length).toBe(
      pending.length,
    );
  });

  it("offers removal on an active membership and restoration on a removed one", async () => {
    // CYC-3.7 and 3.8 had no browser surface at all until this control: "take
    // this person out of the cycle" is a week-one request over a real season,
    // and `restore_membership` is a repair the consistency checker names.
    mockScreens({ approvals: approvals });
    renderScreen(<Approvals />, {
      path: "/staff/cycles/:id/approvals",
      route: `/staff/cycles/${ids.cycle_id}/approvals`,
    });

    expect(await screen.findByRole("heading", { name: "Approvals" })).toBeInTheDocument();
    // One active row, one removed row: one of each control, never both on one
    // row, and never on a pending one — the transition table says so and the
    // server has already read it (§4.22).
    expect((await screen.findAllByRole("button", { name: "Remove" })).length).toBe(1);
    expect((await screen.findAllByRole("button", { name: "Restore" })).length).toBe(1);
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Remove Ishaan Bose from this cycle\?/)).toBeInTheDocument();
    // CYC-3.7 requires a reason, and the dialog must ask for one.
    expect(within(dialog).getByRole("textbox", { name: /^Reason/ })).toBeInTheDocument();
  });

  it("names every application a removal closes, and every one it cannot", async () => {
    // §4.21 widened by §4.37: the per-row planned effect, never an aggregate.
    // A coordinator removing someone mid-process has to see the applications
    // that closes before they press it.
    mockScreens({
      approvals,
      "commands/remove_membership": {
        summary: {
          auto_withdrawn: [
            {
              application_id: "b6f6b8c0-0000-4000-8000-000000000001",
              full_name: "Ishaan Bose",
              job: "Backend Engineer",
              from_status: "in_progress",
            },
          ],
          untouched: [
            {
              application_id: "b6f6b8c0-0000-4000-8000-000000000002",
              full_name: "Ishaan Bose",
              job: "Platform Engineer",
              status: "offered",
            },
          ],
        },
        events: [],
      },
    });
    renderScreen(<Approvals />, {
      path: "/staff/cycles/:id/approvals",
      route: `/staff/cycles/${ids.cycle_id}/approvals`,
    });

    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox", { name: /^Reason/ }), {
      target: { value: "Left the institute" },
    });

    expect(await within(dialog).findByText(/Applications this closes \(1\)/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Backend Engineer/)).toBeInTheDocument();
    expect(within(dialog).getByText(/was in progress/)).toBeInTheDocument();
    // An offered application carries an offer, and only terminate_offer may
    // unwind it — so it is named rather than silently left behind.
    expect(within(dialog).getByText(/Left open \(1\)/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Platform Engineer/)).toBeInTheDocument();
    expect(within(dialog).getByText(/terminate that first/)).toBeInTheDocument();
  });

  it("tags an outcome from the queue and reads the status filter off the payload", async () => {
    // ANA-3's denominator is only as good as the tags somebody can set, and
    // the students it describes are members, not pending requests -- so the
    // queue doubles as the roster its filter can reach.
    const mocked = mockScreens({
      approvals,
      "commands/set_outcome_tag": {
        summary: {
          cycle_id: ids.cycle_id,
          membership_id: approvals.rows[0]!.membership_id,
          outcome_tag: "not_seeking",
          changed: true,
        },
        events: [],
      },
    });
    renderScreen(<Approvals />, {
      path: "/staff/cycles/:id/approvals",
      route: `/staff/cycles/${ids.cycle_id}/approvals`,
    });

    const filter = await screen.findByLabelText("Membership status");
    expect(filter).toHaveValue("pending");
    expect(within(filter as HTMLSelectElement).getByRole("option", { name: "Active" }))
      .toBeInTheDocument();

    fireEvent.click((await screen.findAllByRole("button", { name: "Not tagged" }))[0]!);
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/^Outcome/), {
      target: { value: "not_seeking" },
    });
    await waitFor(() => {
      const posted = mocked.posted("set_outcome_tag").at(-1);
      expect(posted?.outcome_tag).toBe("not_seeking");
    });
  });

  it("names the pasted identifiers that matched nobody before approving", async () => {
    // The failure this prevents is silent: a typo swallowed into "12 rows" is
    // a student who never gets approved and only finds out by complaining
    // (the design review §4.21, widened by §4.37).
    const ticked = approvals.rows[0]!;
    mockScreens({
      approvals,
      "commands/approve_memberships": {
        summary: {
          rows: [
            { identifier: ticked.membership_id, membership_id: ticked.membership_id, status: "applied", reason: null },
            { identifier: "25119999", membership_id: null, status: "error", reason: "unmatched_identifier" },
            { identifier: "NOT-A-ROLL", membership_id: null, status: "error", reason: "unmatched_identifier" },
          ],
        },
        events: [],
      },
    });
    renderScreen(<Approvals />, {
      path: "/staff/cycles/:id/approvals",
      route: `/staff/cycles/${ids.cycle_id}/approvals`,
    });

    fireEvent.click(await screen.findByLabelText(`Select ${ticked.full_name}`));
    fireEvent.click(await screen.findByRole("button", { name: "Approve selected" }));
    const dialog = await screen.findByRole("dialog");
    const unmatched = (await within(dialog).findByText(/Matched nothing \(2\)/)).closest(
      "section",
    )!;
    expect(within(unmatched).getByText("25119999")).toBeInTheDocument();
    expect(within(unmatched).getByText("NOT-A-ROLL")).toBeInTheDocument();
    // And the row that will apply is named, not printed as a membership id.
    const applying = (await within(dialog).findByText(/Will approve \(1\)/)).closest("section")!;
    expect(within(applying).getByText(ticked.full_name)).toBeInTheDocument();
  });
});

describe("company screens", () => {
  it("lists companies with their primary contact", async () => {
    mockScreens({ "screens/staff/companies": staffCompanies });
    renderScreen(<Companies />);

    expect(await screen.findByRole("link", { name: "Northwind Systems" })).toBeInTheDocument();
    // The seed's duplicate shares a contact with the survivor, which is what
    // makes the merge preview's dropped-contact payload non-empty.
    expect(
      await screen.findByRole("link", { name: "Northwind Systems India" }),
    ).toBeInTheDocument();
    expect((await screen.findAllByText("Rita Rao")).length).toBe(2);
  });

  it("offers a merge and renders the full contacts_dropped preview", async () => {
    const dropped = {
      id: "dropped-contact",
      name: "Rita Rao",
      email: "rita.rao@northwind.example.com",
      phone: "+91 99999 12345",
      designation: "University relations lead",
      is_primary: true,
    };
    mockScreens({
      [`screens/staff/company/${ids.company_id}`]: staffCompany,
      "screens/staff/companies": staffCompanies,
      "commands/merge_companies": {
        summary: {
          jobs: 2,
          external_offers: 1,
          contacts_repointed: 3,
          contacts_dropped: [dropped],
        },
        events: [],
      },
    });
    renderScreen(<Company />, {
      path: "/staff/companies/:id",
      route: `/staff/companies/${ids.company_id}`,
    });

    expect(await screen.findByRole("heading", { name: "Northwind Systems" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Merge duplicate" }));
    fireEvent.change(await screen.findByLabelText(/Company to merge in/), {
      target: { value: staffCompanies.companies.find((company) => company.id !== ids.company_id)!.id },
    });
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/University relations lead/)).toBeInTheDocument();
    expect(await within(dialog).findByText(/\+91 99999 12345/)).toBeInTheDocument();
    expect(await within(dialog).findByText(/rita\.rao@northwind\.example\.com/)).toBeInTheDocument();
    // The contact is named by everything a human can act on; the id it also
    // carries is not one of those things and is not printed.
    expect(within(dialog).queryByText(/dropped-contact/)).not.toBeInTheDocument();
  });
});

describe("job builder", () => {
  it("renders four tabs and the impact of the saved rule", async () => {
    mockScreens({
      "builder": builder,
      // The builder reads the staff-visible id: a coordinator has no access to
      // `admin/taxonomies`, and reading it there is what made every builder tab
      // render "Forbidden" for the people JOB-1 gives the builder to.
      "screens/staff/taxonomies": adminTaxonomies,
      "screens/staff/companies": staffCompanies,
    });
    renderScreen(<JobBuilder />, {
      path: "/staff/jobs/:id",
      route: `/staff/jobs/${ids.job_id}?cycle_id=${ids.cycle_id}`,
    });

    expect(await screen.findByRole("heading", { name: "Backend Engineer" })).toBeInTheDocument();
    for (const label of ["Basics", "Rounds", "Questions", "Eligibility"]) {
      expect(await screen.findByRole("tab", { name: new RegExp(label) })).toBeInTheDocument();
    }
    // Basics is the landing tab and carries the per-program compensation that
    // JOB-2.1 makes invisible to the student who is not on that program.
    expect(await screen.findByText(/Per-program compensation/)).toBeInTheDocument();
  });

  it("posts only the fields update_job_basics names", async () => {
    // `UpdateJobBasicsInput` is `extra="forbid"`, and the form is an untyped
    // bag a spread hides from TypeScript. Two things used to travel in it that
    // the command does not have: the `datetime-local` display strings the two
    // deadline inputs render, and the program *name* the screen ships beside
    // each per-program CTC. Either one is a 422 reading "Extra inputs are not
    // permitted", on a save the operator has no way to interpret.
    const mock = mockScreens({
      "builder": builder,
      "screens/staff/taxonomies": adminTaxonomies,
      "screens/staff/companies": staffCompanies,
    });
    renderScreen(<JobBuilder />, {
      path: "/staff/jobs/:id",
      route: `/staff/jobs/${ids.job_id}?cycle_id=${ids.cycle_id}`,
    });

    fireEvent.change(await screen.findByLabelText("Offer acceptance deadline"), {
      target: { value: "2026-10-01T09:00" },
    });
    fireEvent.change(
      (await screen.findAllByLabelText("CTC for this program"))[0]!,
      { target: { value: "26.00" } },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(mock.posted("update_job_basics")).toHaveLength(1));
    const input = mock.posted("update_job_basics")[0]!;
    expect(Object.keys(input).filter((key) => key.endsWith("_local"))).toEqual([]);
    expect(input["offer_acceptance_deadline"]).toEqual(expect.any(String));
    for (const row of input["program_ctc"] as Record<string, unknown>[]) {
      expect(Object.keys(row).sort()).toEqual(["ctc_lpa", "program_id"]);
    }
  });

  it("shows the eligibility clauses and who the rule admits", async () => {
    mockScreens({
      "builder": builder,
      // The builder reads the staff-visible id: a coordinator has no access to
      // `admin/taxonomies`, and reading it there is what made every builder tab
      // render "Forbidden" for the people JOB-1 gives the builder to.
      "screens/staff/taxonomies": adminTaxonomies,
      "screens/staff/companies": staffCompanies,
    });
    const { container } = renderScreen(<JobBuilder />, {
      path: "/staff/jobs/:id",
      route: `/staff/jobs/${ids.job_id}?cycle_id=${ids.cycle_id}`,
    });

    fireEvent.click(await screen.findByRole("tab", { name: /Eligibility/ }));

    await waitFor(() => expect(screen.getByText("Who qualifies")).toBeInTheDocument());
    // The impact must not be unanimous, or it demonstrates nothing.
    const impact = builder.eligibility.impact;
    expect(impact.eligible_count).toBeGreaterThan(0);
    expect(impact.eligible_count).toBeLessThan(impact.member_count);
    expect(
      await screen.findByText(new RegExp(`of ${impact.member_count} active member`)),
    ).toBeInTheDocument();
    // The saved rule round-trips into clauses rather than dropping to JSON.
    expect(await screen.findByText("Minimum CPI")).toBeInTheDocument();
    expect(container.querySelector("textarea")).toBeNull();
  });

  it("takes the job override domain list from the server", async () => {
    const body = structuredClone(builder) as unknown as BuilderPayload;
    body.override_domains = [
      "eligibility",
      "application_deadline",
      "edit_window",
      "withdraw_window",
      "outcome_gate",
      "offer_cap",
      "offer_deadline",
    ];
    const mocked = mockScreens({
      builder: body,
      "screens/staff/taxonomies": adminTaxonomies,
      "screens/staff/companies": staffCompanies,
      "commands/create_override": {
        summary: {
          override_id: "10000000-0000-4000-8000-000000000002",
          rule_domain: "eligibility",
          allow: true,
          scope: "job",
          subject_id: ids.job_id,
          is_active: true,
          expires_at: null,
        },
        events: [],
      },
    });
    renderScreen(<JobBuilder />, {
      path: "/staff/jobs/:id",
      route: `/staff/jobs/${ids.job_id}?cycle_id=${ids.cycle_id}`,
    });

    expect(await screen.findByText("Job overrides")).toBeInTheDocument();
    expect(screen.queryByText("Who qualifies")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Grant an override" }));
    const dialog = await screen.findByRole("dialog");
    const domain = within(dialog).getByRole("combobox", { name: "Rule domain *" });
    expect(within(domain).getAllByRole("option")).toHaveLength(8);
    expect(domain).toHaveValue("eligibility");
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Reason *" }), {
      target: { value: "Job-wide exception" },
    });
    await waitFor(() => {
      expect(mocked.posted("create_override").at(-1)).toMatchObject({
        cycle_id: ids.cycle_id,
        job_id: ids.job_id,
        rule_domain: "eligibility",
      });
    });
  });

  it("builds a nested rule through the group controls, never the JSON box", async () => {
    // O.5: LLD §9.1 makes JSON the *advanced* fallback, and while it was the
    // only door a coordinator could not express a rule the engine supports.
    mockScreens({
      builder: builder,
      "screens/staff/taxonomies": adminTaxonomies,
      "screens/staff/companies": staffCompanies,
    });
    const { container } = renderScreen(<JobBuilder />, {
      path: "/staff/jobs/:id",
      route: `/staff/jobs/${ids.job_id}?cycle_id=${ids.cycle_id}`,
    });

    fireEvent.click(await screen.findByRole("tab", { name: /Eligibility/ }));
    await waitFor(() => expect(screen.getByText("Who qualifies")).toBeInTheDocument());

    fireEvent.click(await screen.findByRole("button", { name: "Any of these" }));

    // A group arrives with two options, because one is not an alternative to
    // anything, and each option takes its own conditions.
    expect(await screen.findByText("Option 1")).toBeInTheDocument();
    expect(screen.getByText("Option 2")).toBeInTheDocument();
    expect(
      screen.getByText(/At least one option must hold/),
    ).toBeInTheDocument();

    // The palette inside an option is filtered per option, not globally:
    // "branch is CSE" in one and "branch is EE" in the other is the entire
    // point, and a globally filtered palette would hide the second one.
    const optionOne = screen.getByText("Option 1").closest("li")!;
    const optionTwo = screen.getByText("Option 2").closest("li")!;
    expect(
      within(optionOne).getByRole("button", { name: /Primary branches/ }),
    ).toBeInTheDocument();
    expect(
      within(optionTwo).getByRole("button", { name: /Primary branches/ }),
    ).toBeInTheDocument();

    // And the JSON escape hatch was never opened.
    expect(container.querySelector("textarea")).toBeNull();
  });
});

describe("staff job list", () => {
  it("distinguishes drafts from published jobs", async () => {
    mockScreens({
      [`screens/staff/cycle/${ids.cycle_id}/jobs`]: staffCycleJobs,
      "screens/staff/companies": staffCompanies,
    });
    renderScreen(<CycleJobs />, {
      path: "/staff/cycles/:id/jobs",
      route: `/staff/cycles/${ids.cycle_id}/jobs`,
    });

    expect(await screen.findByRole("link", { name: "Backend Engineer" })).toBeInTheDocument();
    // The seed keeps one job unpublished so this state is visible at all.
    expect(await screen.findByText("Draft")).toBeInTheDocument();
    expect((await screen.findAllByText("Published")).length).toBeGreaterThan(0);
  });
});

describe("the ATS board", () => {
  it("groups applicants into the round they are sitting in", async () => {
    mockScreens({ [`screens/staff/job/${ids.job_id}/board`]: staffJobBoard });
    renderScreen(<JobBoard />, {
      path: "/staff/jobs/:id/board",
      route: `/staff/jobs/${ids.job_id}/board`,
    });

    expect(await screen.findByRole("heading", { name: "Backend Engineer" })).toBeInTheDocument();
    for (const column of staffJobBoard.columns) {
      expect(
        await screen.findByText(new RegExp(`${column.ord}\\. ${column.name}`)),
      ).toBeInTheDocument();
      for (const row of column.rows) {
        expect(await screen.findByText(row.full_name)).toBeInTheDocument();
      }
    }
  });

  it("shows a waitlisted row as waitlisted, not merely in progress", async () => {
    mockScreens({ [`screens/staff/job/${ids.job_id}/board`]: staffJobBoard });
    renderScreen(<JobBoard />, {
      path: "/staff/jobs/:id/board",
      route: `/staff/jobs/${ids.job_id}/board`,
    });

    // The fixture is captured from the seeded board, where one applicant is
    // waitlisted at round one: RND-1's result, distinct from the status.
    expect(await screen.findByText("Waitlisted")).toBeInTheDocument();
  });

  it("offers finalization and links to the M12 offers panel", async () => {
    mockScreens({ [`screens/staff/job/${ids.job_id}/board`]: staffJobBoard });
    renderScreen(<JobBoard />, {
      path: "/staff/jobs/:id/board",
      route: `/staff/jobs/${ids.job_id}/board`,
    });

    expect(await screen.findByRole("button", { name: "Finalize round" })).toBeEnabled();
    expect(await screen.findByRole("link", { name: "Offers" })).toHaveAttribute(
      "href",
      `/staff/jobs/${staffJobBoard.job.id}/offers`,
    );
  });

  it("disables finalization exactly when the round payload refuses it", async () => {
    const board = structuredClone(staffJobBoard) as unknown as StaffJobBoardPayload;
    board.rounds[0]!.finalized_at = "2026-08-22T10:30:00+00:00";
    board.rounds[0]!.finalized_by = { id: "admin-id", name: "CDS Administrator" };
    board.rounds[0]!.actions.finalize = {
      allowed: false,
      reason: "round_already_finalized",
      human: "Online Assessment was finalized already",
    };
    mockScreens({ [`screens/staff/job/${ids.job_id}/board`]: board });
    renderScreen(<JobBoard />, {
      path: "/staff/jobs/:id/board",
      route: `/staff/jobs/${ids.job_id}/board`,
    });

    expect(await screen.findByRole("button", { name: "Finalize round" })).toBeDisabled();
    expect(await screen.findByText(/Closed .* by CDS Administrator/)).toBeInTheDocument();
  });

  it("renders each finalization consequence, including the strike warning", async () => {
    mockScreens({
      [`screens/staff/job/${ids.job_id}/board`]: staffJobBoard,
      "commands/finalize_round": {
        summary: {
          job_id: ids.job_id,
          round_id: staffJobBoard.rounds[0]!.id,
          round_name: staffJobBoard.rounds[0]!.name,
          strike_on_absence: true,
          finalized: 1,
          strikes: 1,
          penalties: 0,
          rows: [
            {
              application_id: "preview-row",
              full_name: "Asha Mehta",
              roll_number: "21110001",
              attendance_before: "absent",
              attendance_after: "absent",
              to_status: "rejected",
              reason: "absence",
              earns_strike: true,
              outcome: "finalized",
            },
          ],
        },
        events: [],
      },
    });
    renderScreen(<JobBoard />, {
      path: "/staff/jobs/:id/board",
      route: `/staff/jobs/${ids.job_id}/board`,
    });

    fireEvent.click(await screen.findByRole("button", { name: "Finalize round" }));
    expect(await screen.findByText(/will earn a strike/i)).toBeInTheDocument();
  });

  it("disables every bulk action until something is selected", async () => {
    mockScreens({ [`screens/staff/job/${ids.job_id}/board`]: staffJobBoard });
    renderScreen(<JobBoard />, {
      path: "/staff/jobs/:id/board",
      route: `/staff/jobs/${ids.job_id}/board`,
    });

    for (const label of ["Advance", "Eliminate", "Waitlist", "Promote"]) {
      expect(await screen.findByRole("button", { name: label })).toBeDisabled();
    }
  });

  it("offers an open-cycle job only the operations its rows can take", async () => {
    // JOB-6: a job with no rounds has no round position to move, so advance,
    // waitlist and promote can only ever be refused. The applicants are live
    // all the same, and must be reachable without pasting a roll number.
    mockScreens({ [`screens/staff/job/${ids.job_id}/board`]: staffJobBoardOpen });
    renderScreen(<JobBoard />, {
      path: "/staff/jobs/:id/board",
      route: `/staff/jobs/${ids.job_id}/board`,
    });

    const live = (staffJobBoardOpen as unknown as StaffJobBoardPayload).unrouted[0]!;
    expect(await screen.findByText(/runs no rounds/i)).toBeInTheDocument();
    for (const label of ["Advance", "Waitlist", "Promote"]) {
      expect(screen.queryByRole("button", { name: label })).not.toBeInTheDocument();
    }

    fireEvent.click(await screen.findByRole("checkbox", { name: `Select ${live.full_name}` }));
    expect(await screen.findByRole("button", { name: "Eliminate" })).toBeEnabled();
  });

  it("disables an operation the server refuses on every selected row", async () => {
    // The client half of the design review §4.22 for the bulk bar: a button that stays
    // live over a selection the command will skip is a button that reports
    // "Will move (0)" after the coordinator has already committed to it.
    const board = structuredClone(staffJobBoard) as unknown as StaffJobBoardPayload;
    const row = board.columns[0]!.rows[0]!;
    row.actions["advance"] = {
      allowed: false,
      reason: "invalid_transition",
      human: "Waitlisted: promote it rather than advancing it",
    };
    mockScreens({ [`screens/staff/job/${ids.job_id}/board`]: board });
    renderScreen(<JobBoard />, {
      path: "/staff/jobs/:id/board",
      route: `/staff/jobs/${ids.job_id}/board`,
    });

    fireEvent.click(await screen.findByRole("checkbox", { name: `Select ${row.full_name}` }));
    const advance = await screen.findByRole("button", { name: "Advance" });
    expect(advance).toBeDisabled();
    expect(advance).toHaveAttribute("title", "Waitlisted: promote it rather than advancing it");
    expect(await screen.findByRole("button", { name: "Eliminate" })).toBeEnabled();
  });

  it("keeps a ticked selection inside one round", async () => {
    // Advancing round one and round two in a single batch is two decisions
    // wearing one button, so ticking into a second round replaces the first
    // rather than adding to it -- and says how many it dropped.
    const board = staffJobBoard as unknown as StaffJobBoardPayload;
    const first = board.columns[0]!.rows[0]!;
    const second = board.columns[1]!.rows[0]!;
    mockScreens({ [`screens/staff/job/${ids.job_id}/board`]: staffJobBoard });
    renderScreen(<JobBoard />, {
      path: "/staff/jobs/:id/board",
      route: `/staff/jobs/${ids.job_id}/board`,
    });

    fireEvent.click(await screen.findByRole("checkbox", { name: `Select ${first.full_name}` }));
    expect(await screen.findByText("1")).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("checkbox", { name: `Select ${second.full_name}` }));
    expect(
      await screen.findByText(
        new RegExp(`1 from ${board.columns[0]!.name} was cleared`, "i"),
      ),
    ).toBeInTheDocument();
    expect(
      (await screen.findByRole("checkbox", { name: `Select ${first.full_name}` })),
    ).not.toBeChecked();
    expect(
      (await screen.findByRole("checkbox", { name: `Select ${second.full_name}` })),
    ).toBeChecked();
  });

  it("ticks a whole round at once", async () => {
    const board = staffJobBoard as unknown as StaffJobBoardPayload;
    const column = board.columns[0]!;
    mockScreens({ [`screens/staff/job/${ids.job_id}/board`]: staffJobBoard });
    renderScreen(<JobBoard />, {
      path: "/staff/jobs/:id/board",
      route: `/staff/jobs/${ids.job_id}/board`,
    });

    fireEvent.click(
      await screen.findByRole("checkbox", { name: `Select everyone in ${column.name}` }),
    );
    for (const row of column.rows) {
      expect(await screen.findByRole("checkbox", { name: `Select ${row.full_name}` })).toBeChecked();
    }
  });

  it("names the reason a row was skipped, not its code", async () => {
    // "invalid transition" is three different refusals wearing one label; the
    // server said which one, and the preview must repeat it rather than
    // de-underscoring the code back into a shrug.
    mockScreens({
      [`screens/staff/job/${ids.job_id}/board`]: staffJobBoardOpen,
      "commands/eliminate_applications": {
        summary: {
          rows: [
            {
              identifier: "21110009",
              application_id: "preview-row",
              full_name: "Chitra Rao",
              roll_number: "21110009",
              status: "skipped",
              reason: "invalid_transition",
              human: "Not sitting in a round",
            },
          ],
        },
        events: [],
      },
    });
    renderScreen(<JobBoard />, {
      path: "/staff/jobs/:id/board",
      route: `/staff/jobs/${ids.job_id}/board`,
    });

    const live = (staffJobBoardOpen as unknown as StaffJobBoardPayload).unrouted[0]!;
    fireEvent.click(await screen.findByRole("checkbox", { name: `Select ${live.full_name}` }));
    fireEvent.click(await screen.findByRole("button", { name: "Eliminate" }));
    // Eliminating needs a reason before the dry run has an input to run on.
    fireEvent.change(await screen.findByLabelText(/Reason/), {
      target: { value: "Withdrew from the programme" },
    });
    expect(await screen.findByText(/Not sitting in a round/)).toBeInTheDocument();
    expect(screen.queryByText(/invalid transition/i)).not.toBeInTheDocument();
  });

  it("offers each attendance mark by name, exactly when the server allows it", async () => {
    // The client's half of the design review §4.22: whether attendance can be marked
    // is the server's answer on the row, so flipping that answer must flip the
    // control. RND-3 makes absence consequential — finalisation rejects the
    // absentee and may award a strike — so "Absent" has to be a thing you can
    // click, not a state reached by clicking a cycling chip the right number of
    // times.
    const board = structuredClone(staffJobBoard) as unknown as StaffJobBoardPayload;
    const marked = board.columns[0]!.rows[0]!;
    const refused = board.columns[1]!.rows[0]!;
    refused.actions["mark_attendance"] = {
      allowed: false,
      reason: "invalid_transition",
      human: "Withdrawn from this job",
    };
    mockScreens({ [`screens/staff/job/${ids.job_id}/board`]: board });
    renderScreen(<JobBoard />, {
      path: "/staff/jobs/:id/board",
      route: `/staff/jobs/${ids.job_id}/board`,
    });

    for (const mark of ["absent", "excused"]) {
      expect(
        await screen.findByRole("button", {
          name: `Mark ${marked.full_name} ${mark}`,
        }),
      ).toBeInTheDocument();
    }
    // The state the row is already in is not offered as somewhere to go.
    expect(
      screen.queryByRole("button", {
        name: `Mark ${marked.full_name} ${marked.attendance}`,
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: new RegExp(refused.full_name) }),
    ).not.toBeInTheDocument();
  });

  it("states the slot each applicant has, and whose it is", async () => {
    mockScreens({ [`screens/staff/job/${ids.job_id}/board`]: staffJobBoard });
    renderScreen(<JobBoard />, {
      path: "/staff/jobs/:id/board",
      route: `/staff/jobs/${ids.job_id}/board`,
    });

    const board = staffJobBoard as unknown as StaffJobBoardPayload;
    const published = board.columns
      .flatMap((column) => column.rows)
      .find((row) => row.venue !== null);
    expect(published, "the fixture publishes no slot").toBeDefined();
    expect(await screen.findByText(new RegExp(published!.venue!))).toBeInTheDocument();
  });

  it("scopes attendance and venues to a round the coordinator picks", async () => {
    // RND-4 and §4.23: these are facts about a round, so the round is named
    // explicitly rather than inferred from wherever each row happens to sit.
    mockScreens({ [`screens/staff/job/${ids.job_id}/board`]: staffJobBoard });
    renderScreen(<JobBoard />, {
      path: "/staff/jobs/:id/board",
      route: `/staff/jobs/${ids.job_id}/board`,
    });

    const picker = await screen.findByLabelText(/Round/);
    expect(picker).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Mark present" })).toBeDisabled();
    expect(await screen.findByRole("button", { name: "Publish" })).toBeDisabled();
  });
});

describe("M12 offer screens", () => {
  it("renders the job offer panel from server permissions", async () => {
    mockScreens({
      [`screens/staff/job/${staffJobOffers.job.id}/offers`]: staffJobOffers,
    });
    renderScreen(<Offers />, {
      path: "/staff/jobs/:id/offers",
      route: `/staff/jobs/${staffJobOffers.job.id}/offers`,
    });

    expect(
      await screen.findByRole("heading", { name: "Backend Engineer offers" }),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText("Select Asha Screen")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Extend / rollout" })).toBeDisabled();
  });

  it("shows termination restoration checkboxes and an optional fresh deadline inside the preview", async () => {
    const offers = structuredClone(staffJobOffersCascade) as unknown as StaffJobOffersPayload;
    const candidate = offers.applications[0]!.restoration_candidates[0]!;
    candidate.requires_fresh_offer = true;
    candidate.deadline_editable = true;
    mockScreens({
      [`screens/staff/job/${offers.job.id}/offers`]: offers,
    });
    renderScreen(<Offers />, {
      path: "/staff/jobs/:id/offers",
      route: `/staff/jobs/${staffJobOffersCascade.job.id}/offers`,
    });

    fireEvent.click(await screen.findByRole("button", { name: "Terminate" }));
    expect(await screen.findByText("Restoration choices (1)")).toBeInTheDocument();
    expect(await screen.findByText(/Backend Engineer · Acme Corp/)).toBeInTheDocument();
    expect(await screen.findByText(/prior round restored/)).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Restore Backend Engineer" }));
    expect(await screen.findByLabelText(/Fresh offer deadline for Backend Engineer/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Terminate offer" })).toBeInTheDocument();
  });

  it("renders global external CRUD and the dedicated-cycle pool", async () => {
    mockScreens({
      "screens/staff/external": staffExternal,
      [`screens/staff/cycle/${staffCycleExternal.cycle.id}/external`]: staffCycleExternal,
    });
    const global = renderScreen(<ExternalOffers />, {
      path: "/staff/external",
      route: "/staff/external",
    });
    expect(await screen.findByRole("heading", { name: "External offers" })).toBeInTheDocument();
    expect(await screen.findByText(/Asha Screen · Acme Corp/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Record external offer" })).toBeInTheDocument();
    global.unmount();

    renderScreen(<CycleExternal />, {
      path: "/staff/cycles/:id/external",
      route: `/staff/cycles/${staffCycleExternal.cycle.id}/external`,
    });
    expect(
      await screen.findByRole("heading", { name: "Placement 2026 external offers" }),
    ).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Attach" })).toBeEnabled();
  });

  it("switches external compensation units by outcome and posts the stipend", async () => {
    const mock = mockScreens({ "screens/staff/external": staffExternal });
    renderScreen(<ExternalOffers />, { path: "/staff/external", route: "/staff/external" });

    fireEvent.click(await screen.findByRole("button", { name: "Record external offer" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("CTC (LPA)")).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Stipend per month (INR)")).toBeNull();

    fireEvent.change(within(dialog).getByRole("combobox", { name: /^Outcome/ }), { target: { value: "internship" } });
    expect(within(dialog).queryByLabelText("CTC (LPA)")).toBeNull();
    fireEvent.change(within(dialog).getByLabelText("Stipend per month (INR)"), {
      target: { value: "65000" },
    });
    fireEvent.change(within(dialog).getByRole("combobox", { name: /^Student \*/ }), {
      target: { value: staffExternal.enrollments[0]!.id },
    });
    fireEvent.change(within(dialog).getByRole("combobox", { name: /^Company/ }), {
      target: { value: staffExternal.companies[0]!.id },
    });
    fireEvent.change(within(dialog).getByRole("textbox", { name: /^Reason \/ evidence/ }), {
      target: { value: "Verified off-campus internship" },
    });

    await waitFor(() =>
      expect(mock.posted("create_external_offer").at(-1)?.["stipend_month"]).toBe("65000"),
    );
    const input = mock.posted("create_external_offer").at(-1)!;
    expect(input).toMatchObject({
      outcome: "internship",
      stipend_month: "65000",
      ctc_lpa: null,
    });
  });

  it("edits an external offer's outcome-specific compensation and posts it", async () => {
    const mock = mockScreens({ "screens/staff/external": staffExternal });
    renderScreen(<ExternalOffers />, { path: "/staff/external", route: "/staff/external" });

    fireEvent.click(await screen.findByRole("button", { name: "Update status" }));
    const dialog = await screen.findByRole("dialog");
    const ctc = within(dialog).getByLabelText("CTC (LPA)");
    expect(ctc).toBeInTheDocument();
    fireEvent.change(ctc, { target: { value: "24.50" } });
    fireEvent.change(within(dialog).getByRole("textbox", { name: /^Reason/ }), {
      target: { value: "Confirmed compensation letter" },
    });

    await waitFor(() =>
      expect(mock.posted("update_external_offer").at(-1)?.["ctc_lpa"]).toBe("24.50"),
    );
    expect(mock.posted("update_external_offer").at(-1)).toMatchObject({
      ctc_lpa: "24.50",
      stipend_month: null,
    });
  });

  it("offers Record PPO on an internship application and links its CTC payload", async () => {
    const board = structuredClone(staffJobBoardOpen) as unknown as StaffJobBoardPayload;
    board.job.company_id = staffExternal.companies[0]!.id;
    const applicant = board.unrouted[0]!;
    applicant.enrollment_id = staffExternal.enrollments[0]!.id;
    const mock = mockScreens({ [`screens/staff/job/${board.job.id}/board`]: board });
    renderScreen(<JobBoard />, {
      path: "/staff/jobs/:id/board",
      route: `/staff/jobs/${board.job.id}/board`,
    });

    fireEvent.click((await screen.findAllByRole("button", { name: "Record PPO" }))[0]!);
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("CTC (LPA)"), {
      target: { value: "30.00" },
    });
    fireEvent.change(within(dialog).getByRole("textbox", { name: /^Reason \/ evidence/ }), {
      target: { value: "PPO letter received" },
    });

    await waitFor(() =>
      expect(mock.posted("create_external_offer").at(-1)?.["ctc_lpa"]).toBe("30.00"),
    );
    expect(mock.posted("create_external_offer").at(-1)).toMatchObject({
      enrollment_id: applicant.enrollment_id,
      company_id: board.job.company_id,
      outcome: "placement",
      source: "ppo",
      source_application_id: applicant.application_id,
      ctc_lpa: "30.00",
      stipend_month: null,
    });
  });

  it("gives students portal actions and read-only external offers", async () => {
    mockScreens({ "screens/me/dashboard": meDashboard });
    renderScreen(<Dashboard />, { path: "/dashboard", route: "/dashboard" });

    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Accept" })).toBeEnabled();
    expect(await screen.findByRole("button", { name: "Decline" })).toBeEnabled();
    expect(await screen.findByText("External offers (read only)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Update status|Delete/ })).toBeNull();
  });
});

describe("student screens", () => {
  it("separates active memberships and renders structured reasons on the student home page", async () => {
    const homeJoinable = {
      ...joinable,
      cycles: joinable.cycles.map((cycle) =>
        cycle.membership === null
          ? {
              ...cycle,
              can_join: false,
              reasons: [
                {
                  code: "profile_incomplete",
                  human: "Complete your profile before joining this cycle.",
                  path: "profile",
                },
              ],
            }
          : cycle,
      ),
    };
    mockScreens({ "screens/cycles/joinable": homeJoinable });
    const me = {
      authenticated: true,
      dev_login_enabled: false,
      user: {
        id: "student-id",
        email: "student@example.edu",
        full_name: "Test Student",
        role: "student",
      },
      coordinated_cycle_ids: [],
    } satisfies Me;
    renderScreen(<Home me={me} />);

    const yourCycles = await screen.findByRole("region", { name: "Your cycles" });
    const otherCycles = await screen.findByRole("region", { name: "Other cycles" });

    for (const cycle of homeJoinable.cycles) {
      const isActive = cycle.membership?.status === "active";
      expect(within(yourCycles).queryByText(cycle.name) !== null).toBe(isActive);
      expect(within(otherCycles).queryByText(cycle.name) !== null).toBe(!isActive);
    }
    expect(
      within(otherCycles).getByText("Complete your profile before joining this cycle."),
    ).toBeInTheDocument();
  });

  it("separates active memberships from other cycles", async () => {
    mockScreens({ "screens/cycles/joinable": joinable });
    renderScreen(<StudentCycles />, { path: "/cycles", route: "/cycles" });

    const yourCycles = await screen.findByRole("region", { name: "Your cycles" });
    const otherCycles = await screen.findByRole("region", { name: "Other cycles" });
    const activeCycles = joinable.cycles.filter(
      (cycle) => cycle.membership?.status === "active",
    );
    const remainingCycles = joinable.cycles.filter(
      (cycle) => cycle.membership?.status !== "active",
    );

    for (const cycle of activeCycles) {
      expect(within(yourCycles).getByRole("link", { name: cycle.name })).toHaveAttribute(
        "href",
        `/cycles/${cycle.id}/jobs`,
      );
      expect(within(otherCycles).queryByText(cycle.name)).toBeNull();
    }
    for (const cycle of remainingCycles) {
      expect(
        within(otherCycles).getByRole("heading", { name: cycle.name }),
      ).toBeInTheDocument();
      expect(within(otherCycles).queryByRole("link", { name: cycle.name })).toBeNull();
      expect(within(yourCycles).queryByText(cycle.name)).toBeNull();
    }
    expect(
      within(otherCycles).getByText(/Eligible to join with coordinator approval/),
    ).toBeInTheDocument();
  });

  it("renders join consent and resume choices from the joinable payload", async () => {
    const body = structuredClone(joinable);
    const cycle = body.cycles.find((item) => item.membership === null && item.can_join);
    expect(cycle).toBeDefined();
    mockScreens({ "screens/cycles/joinable": body });
    renderScreen(<StudentCycles />, { path: "/cycles", route: "/cycles" });

    fireEvent.click(await screen.findByRole("button", { name: /Request to join|Join/ }));
    expect(await screen.findByLabelText(/Resume for this cycle/)).toBeInTheDocument();
    expect(await screen.findByLabelText(/Consent/)).toBeInTheDocument();
  });

  it("offers a withdrawn member the way back into the cycle", async () => {
    // the design review §4.34. The withdrawn card used to render nothing at all, so a
    // student who changed their mind had to ask a coordinator to restore them.
    const body = structuredClone(joinable);
    const cycle = body.cycles.find((item) => item.membership === null && item.can_join);
    expect(cycle).toBeDefined();
    cycle!.membership = {
      membership_id: "40000000-0000-4000-8000-000000000001",
      status: "withdrawn",
      rejection_reason: null,
    };
    mockScreens({ "screens/cycles/joinable": body });
    renderScreen(<StudentCycles />, { path: "/cycles", route: "/cycles" });

    fireEvent.click(
      await screen.findByRole("button", { name: /Register again|Request again/ }),
    );
    // Re-entry re-runs every join check, so it asks for what joining asks for.
    expect(await screen.findByLabelText(/Resume for this cycle/)).toBeInTheDocument();
    expect(await screen.findByLabelText(/Consent/)).toBeInTheDocument();
  });

  it("shows only published jobs, with the reasons an ineligible one is closed", async () => {
    mockScreens({ [`screens/cycle/${ids.cycle_id}/jobs`]: studentJobs });
    renderScreen(<StudentJobs />, {
      path: "/cycles/:id/jobs",
      route: `/cycles/${ids.cycle_id}/jobs`,
    });

    expect(await screen.findByRole("heading", { name: "Placement 2026" })).toBeInTheDocument();
    const titles = (studentJobs.jobs as { title: string }[]).map((job) => job.title);
    for (const title of titles) {
      expect(await screen.findByRole("link", { name: title })).toBeInTheDocument();
    }
    // The draft the staff list shows must not be here.
    expect(screen.queryByText("Associate Consultant")).toBeNull();
  });

  it("shows the active penalty in the student's eligibility reasons", async () => {
    mockScreens({ [`screens/job/${ids.job_id}`]: studentJob });
    renderScreen(<StudentJob />, { path: "/jobs/:id", route: `/jobs/${ids.job_id}` });

    expect(await screen.findByRole("heading", { name: "Backend Engineer" })).toBeInTheDocument();
    expect(await screen.findByText(/disciplinary penalty is blocking/i)).toBeInTheDocument();
    // JOB-2.1: one compensation figure, said to be the student's program's.
    expect(await screen.findByText(/the figure for your program/)).toBeInTheDocument();
  });

  it("makes the header Apply a control that reaches the form", async () => {
    // It was `<Button asChild><a href="#application-form">`, which renders an
    // anchor: it only scrolls, and the second click does nothing at all because
    // the hash is already current. A button labelled Apply that does nothing is
    // worse than no button.
    const job = structuredClone(studentJob) as unknown as StudentJobPayload;
    job.eligibility = { eligible: true, summary: "Eligible", reasons: [] };
    job.application = null;
    mockScreens({ [`screens/job/${ids.job_id}`]: job });
    renderScreen(<StudentJob />, { path: "/jobs/:id", route: `/jobs/${ids.job_id}` });

    await screen.findByRole("heading", { name: "Backend Engineer" });
    expect(screen.queryByRole("link", { name: "Apply" })).toBeNull();
    const applies = await screen.findAllByRole("button", { name: "Apply" });
    // The header control and the form's submit — both buttons, neither a link.
    expect(applies).toHaveLength(2);
    fireEvent.click(applies[0]!);
    // Nothing is submitted by the jump: the form's own button is still the one
    // that applies, so APP-1's validation has exactly one path through it.
    expect(await screen.findAllByRole("button", { name: "Apply" })).toHaveLength(2);
  });

  it("wires Apply and generates controls for every question type", async () => {
    const job = structuredClone(studentJob) as unknown as StudentJobPayload;
    job.eligibility = { eligible: true, summary: "Eligible", reasons: [] };
    job.application = null;
    const types = ["text", "longtext", "single", "multi", "boolean", "number", "date", "email", "url"];
    job.apply_form.questions = types.map((qtype, index) => ({
      question_id: `00000000-0000-4000-8000-0000000000${String(index).padStart(2, "0")}`,
      text: `Question ${qtype}`,
      qtype,
      required: false,
      ord: index + 1,
      options: qtype === "single" || qtype === "multi" ? ["One", "Two"] : [],
    }));
    mockScreens({ [`screens/job/${ids.job_id}`]: job });
    const { container } = renderScreen(<StudentJob />, {
      path: "/jobs/:id",
      route: `/jobs/${ids.job_id}`,
    });

    const applyButtons = await screen.findAllByRole("button", { name: "Apply" });
    expect(applyButtons.some((button) => !button.hasAttribute("disabled"))).toBe(true);
    for (const qtype of types.filter((item) => item !== "multi")) {
      expect(await screen.findByLabelText(`Question ${qtype}`)).toBeInTheDocument();
    }
    expect(await screen.findByRole("group", { name: "Question multi" })).toBeInTheDocument();
    expect(container.querySelector('input[type="number"]')).not.toBeNull();
    expect(container.querySelector('input[type="date"]')).not.toBeNull();
    expect(container.querySelector('input[type="email"]')).not.toBeNull();
    expect(container.querySelector('input[type="url"]')).not.toBeNull();
  });

  it("lists every application with its position and status", async () => {
    mockScreens({ "screens/me/applications": meApplications });
    renderScreen(<MyApplications />, { path: "/applications", route: "/applications" });

    expect(await screen.findByRole("heading", { name: "My applications" })).toBeInTheDocument();
    for (const application of meApplications.applications) {
      expect(
        await screen.findByRole("link", { name: application.job.title }),
      ).toBeInTheDocument();
    }
    // A pipeline application names the round it sits in; the open-cycle one
    // holds no position at all and must not be rendered as round zero (JOB-6).
    const positioned = meApplications.applications.find((application) => application.round);
    expect(positioned?.round).toBeTruthy();
    expect(
      await screen.findByText(
        `Round ${positioned!.round!.ord} of ${positioned!.round!.of} — ${positioned!.round!.name}`,
      ),
    ).toBeInTheDocument();
    expect(await screen.findAllByText("No rounds")).toHaveLength(1);
  });

  it("offers Edit exactly where can_edit exposes it", async () => {
    mockScreens({ "screens/me/applications": meApplications });
    renderScreen(<MyApplications />, { path: "/applications", route: "/applications" });

    const editable = meApplications.applications.filter((application) => application.can_edit).length;
    expect(await screen.findAllByRole("button", { name: "Edit" })).toHaveLength(editable);
  });

  it("offers Withdraw only where the server says the window is open", async () => {
    mockScreens({ "screens/me/applications": meApplications });
    renderScreen(<MyApplications />, { path: "/applications", route: "/applications" });

    await screen.findByRole("heading", { name: "My applications" });
    // The fixture carries two live applications and one withdrawn one, so the
    // button count is the server's `can_withdraw`, not a client guess.
    const withdrawable = meApplications.applications.filter(
      (application) => application.can_withdraw,
    ).length;
    expect(await screen.findAllByRole("button", { name: "Withdraw" })).toHaveLength(
      withdrawable,
    );
    expect(withdrawable).toBeLessThan(meApplications.applications.length);
  });
});
