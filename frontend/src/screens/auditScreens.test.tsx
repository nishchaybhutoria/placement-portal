import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mockScreens, renderScreen } from "@/test/harness";
import { BulkUpsert } from "./admin/BulkUpsert";
import { Users } from "./admin/Users";
import { Profile } from "./student/Profile";

const enrollmentId = "10000000-0000-4000-8000-000000000001";

describe("F2/F4 gap screens", () => {
  it("renders the declared profile, resume controls, and Drive preview", async () => {
    mockScreens({
      "screens/me/profile": {
        enrollment: { id: enrollmentId, is_current: true, institute_email: "asha@example.edu" },
        declared_at: "2026-08-01T00:00:00+00:00",
        // `editable` is the server's verdict per field: full_name is seeded from
        // Google and never the student's, personal_email always is (§4.33).
        fields: [
          {
            key: "full_name",
            label: "Full name",
            owner: "admin",
            home: "users",
            editable: false,
          },
          {
            key: "personal_email",
            label: "Personal email",
            owner: "student",
            home: "profiles",
            editable: true,
          },
          {
            key: "cpi",
            label: "CPI",
            owner: "admin",
            home: "profiles",
            editable: true,
          },
        ],
        values: { full_name: "Asha Mehta", personal_email: "asha@example.com", cpi: null },
        resumes: [{
          id: "20000000-0000-4000-8000-000000000001",
          label: "Placements",
          drive_url: "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view",
          preview_url: "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/preview",
          is_default: true,
        }],
        taxonomies: { programs: [], branches: [], minors: [] },
        program_branches: [],
      },
    });
    renderScreen(<Profile />, { path: "/profile", route: "/profile" });

    expect(await screen.findByRole("heading", { name: "My profile" })).toBeInTheDocument();
    expect(await screen.findByLabelText("Personal email")).toHaveValue("asha@example.com");
    // An admin-managed field still holding nothing is the student's to supply,
    // even after declaration — otherwise a blank left at declaration is a
    // permanently unjoinable profile (the design review §4.33).
    expect(await screen.findByLabelText("CPI")).toHaveValue(null);
    expect(await screen.findByRole("button", { name: "Add resume" })).toBeInTheDocument();
    expect(await screen.findByTitle("Preview of Placements")).toHaveAttribute("src", expect.stringContaining("/preview"));
  });

  it("renders staged bulk rows with their compensating delete control", async () => {
    mockScreens({
      "screens/admin/bulk-upsert": {
        columns: [{ key: "roll_number", label: "Roll number", owner: "admin", home: "enrollments" }],
        email_column: "institute_email",
        staged: {
          pending: [{
            id: "30000000-0000-4000-8000-000000000001",
            institute_email: "future@example.edu",
            raw: {},
            fields: { roll_number: "26110001" },
            batch_key: "batch",
            row_number: 2,
            uploaded_by_email: "admin@example.edu",
            created_at: "2026-08-01T00:00:00+00:00",
            applied_at: null,
            error: null,
          }],
          errored: [],
          applied: [],
        },
      },
    });
    renderScreen(<BulkUpsert />, { path: "/admin/bulk-upsert", route: "/admin/bulk-upsert" });

    expect(await screen.findByRole("heading", { name: "Bulk profile upsert" })).toBeInTheDocument();
    expect(await screen.findByText("future@example.edu · row 2")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Delete" })).toBeEnabled();
  });

  it("renders every identity action exposed by admin/users", async () => {
    mockScreens({
      "screens/admin/users": {
        filters: { q: null, include_inactive: true },
        counts: { total: 1, active: 1, admins: 0 },
        users: [{
          id: "40000000-0000-4000-8000-000000000001",
          email: "asha@example.edu",
          full_name: "Asha Mehta",
          role: "student",
          is_active: true,
          created_at: "2026-08-01T00:00:00+00:00",
          current_enrollment: { id: enrollmentId, roll_number: "21110001", profile_declared: true },
          enrollment_count: 1,
          enrollments: [{ id: enrollmentId, roll_number: "21110001", is_current: true, created_at: "2026-08-01T00:00:00+00:00" }],
          actions: {
            start_new_enrollment: { allowed: true, reason: null, human: null },
            set_role: { allowed: true, reason: null, human: null },
            deactivate: { allowed: true, reason: null, human: null },
          },
        }],
      },
    });
    renderScreen(<Users />, { path: "/admin/users", route: "/admin/users" });

    expect(await screen.findByRole("heading", { name: "Users and enrollments" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Start new enrollment" })).toBeEnabled();
    expect(await screen.findByRole("button", { name: "Deactivate" })).toBeEnabled();
    expect(await screen.findByRole("button", { name: "Change role" })).toBeDisabled();
  });
});
