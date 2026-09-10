import { expect, type Page, test } from "@playwright/test";

const ADMIN = "admin@example.edu";
const PRIMARY_COORDINATOR = "demo.coordinator01@example.edu";
const COORD2 = "demo.coordinator02@example.edu";
const OPEN_CYCLE = "Open Opportunities — Summer";
const OPEN_JOB_ONE = "Campus Community Associate";
const OPEN_JOB_TWO = "Open Research Internship";
/**
 * The open cycle's placement-outcome job (Step 7, corrected).
 *
 * Step 42's universal cascade only reaches outside the placement cycle if a
 * placement-outcome application exists there, and both other open jobs are
 * internships — the seeded one and job 2, which must stay one because P1
 * accepts it at Step 11.
 */
const OPEN_JOB_THREE = "Open Graduate Analyst";
const SUMMER_CYCLE = "Summer Internships 2027";
const DRIVE = "https://drive.google.com/file/d/1MockRunLifecycleResumeFile000001/view";
const SUMMER_JOB_ONE = "Embedded Systems Intern";
const SUMMER_JOB_TWO = "Controls Engineering Intern";
const SUMMER_JOB_THREE = "Engineering Operations Intern";
const PLACEMENT_CYCLE = "Placements 2027–28";
const WINTER_CYCLE = "Winter Internships 2027";
const WINTER_JOB = "Winter Systems Internship";
/** Stage 3's three jobs. B is the one carrying a rule (Steps 45 and 39). */
const PLACEMENT_JOB_A = "Graduate Software Engineer";
const PLACEMENT_JOB_B = "Quantitative Researcher";
const PLACEMENT_JOB_C = "Operations Management Trainee";
/** Who applies where, once P1 is out and job B's CPI floor is applied. */
const PLACEMENT_APPLICANTS = {
  a: ["p2", "p3", "p4", "p5", "p6", "p7", "p8", "p9", "p10", "p11"],
  b: ["p2", "p3", "p6", "p7", "p11"],
  c: ["p2", "p3", "p5", "p9", "p10", "p11"],
} as const;

const students = {
  p1: ["demo.student01@example.edu", "Demo Student 01"],
  p2: ["demo.student02@example.edu", "Demo Student 02"],
  p3: ["demo.student03@example.edu", "Demo Student 03"],
  p4: ["demo.student04@example.edu", "Demo Student 04"],
  p5: ["demo.student05@example.edu", "Demo Student 05"],
  p6: ["demo.student06@example.edu", "Demo Student 06"],
  p7: ["demo.student07@example.edu", "Demo Student 07"],
  p8: ["demo.student08@example.edu", "Demo Student 08"],
  p9: ["demo.student09@example.edu", "Demo Student 09"],
  p10: ["demo.student10@example.edu", "Demo Student 10"],
  p11: ["demo.student11@example.edu", "Demo Student 11"],
} as const;

/** Part A.4's roll numbers, everyone but P7, as Step 17 pastes them. */
const ROLLS_EXCEPT_P7 = [
  "99000001", "99000002", "99000003", "99000004", "99000005",
  "99000006", "99000008", "99000009", "99000010", "99000011",
] as const;

/** The same rolls, addressable by person, for the steps that paste a subset. */
const ROLL = {
  p1: "99000001",
  p2: "99000002",
  p3: "99000003",
  p4: "99000004",
  p5: "99000005",
  p6: "99000006",
  p7: "99000007",
  p8: "99000008",
  p9: "99000009",
  p10: "99000010",
  p11: "99000011",
} as const;

/** Job 1's six applicants: four ordinary, P11 and P3 by their overrides. */
const JOB_ONE_ROLLS = [ROLL.p1, ROLL.p2, ROLL.p6, ROLL.p8, ROLL.p11, ROLL.p3] as const;

type Profile = {
  email: string;
  program: "BTech";
  branch: "Mechanical" | "Civil";
  cpi: string;
  active: string;
  total: string;
};

async function login(page: Page, email: string) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByRole("button", { name: "Sign in as this user" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

async function logout(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
}

async function declareProfile(page: Page, profile: Profile) {
  await login(page, profile.email);
  await page.getByRole("link", { name: "My profile", exact: true }).click();
  await expect(page.getByRole("heading", { name: "My profile" })).toBeVisible();

  await page.getByRole("combobox", { name: "Program" }).selectOption({ label: profile.program });
  await page.getByRole("combobox", { name: "Primary branch" }).selectOption({ label: profile.branch });
  await page.getByRole("spinbutton", { name: "Graduating year" }).fill("2027");
  await page.getByRole("spinbutton", { name: "CPI" }).fill(profile.cpi);
  await page.getByRole("spinbutton", { name: "Active backlog count" }).fill(profile.active);
  await page.getByRole("spinbutton", { name: "Total backlog count" }).fill(profile.total);
  await page.getByRole("combobox", { name: "Gender" }).selectOption("other");
  await page.getByRole("textbox", { name: "Personal email" }).fill(profile.email.replace("@example.edu", "@example.com"));
  await page.getByRole("textbox", { name: "Contact number" }).fill("+1 202-555-0199");
  await page.getByRole("textbox", { name: "Nationality" }).fill("IN");
  await page.getByRole("spinbutton", { name: "10th percentage" }).fill("90");
  await page.getByRole("spinbutton", { name: "10th year" }).fill("2019");
  await page.getByRole("spinbutton", { name: "12th percentage" }).fill("92");
  await page.getByRole("spinbutton", { name: "12th year" }).fill("2021");
  await page.getByRole("button", { name: "Declare profile" }).click();
  await expect(page.getByText(/Declared .* Locked fields now belong to the administration/)).toBeVisible();

  await page.getByRole("textbox", { name: "Label" }).fill("Primary resume");
  await page.getByRole("textbox", { name: "Google Drive / Docs file link" }).fill(DRIVE);
  await page.getByRole("button", { name: "Add resume" }).click();
  await expect(page.getByText("Primary resume · Default", { exact: true })).toBeVisible();
  await logout(page);
}

async function uploadCsv(page: Page, name: string, csv: string) {
  await page.getByLabel("CSV or XLSX").setInputFiles({
    name,
    mimeType: "text/csv",
    buffer: Buffer.from(csv),
  });
  await expect(page.getByRole("button", { name: "Preview and commit" })).toBeEnabled();
}

/**
 * Hand the board a venue sheet and wait for the parser's own report.
 *
 * The upload is read before anything is sent (the design review §4.5), so the row
 * count in the report is what the button will publish, not what the file had.
 */
async function uploadVenueSheet(page: Page, name: string, csv: string) {
  await page.getByLabel("Or upload a sheet").setInputFiles({
    name,
    mimeType: "text/csv",
    buffer: Buffer.from(csv),
  });
  await expect(page.getByText(/rows? read from the file/)).toBeVisible();
}

/** Open the venue publish preview, which is the only per-row report it has. */
async function publishSlots(page: Page) {
  await page.getByRole("button", { name: "Publish", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("What will happen")).toBeVisible();
  return dialog;
}

async function previewAndCommit(page: Page) {
  await page.getByRole("button", { name: "Preview and commit" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("What will happen")).toBeVisible();
  return dialog;
}

async function enrollmentId(page: Page, email: string): Promise<string> {
  const response = await page.request.get(`/api/v1/screens/admin/users?q=${encodeURIComponent(email)}&include_inactive=true`);
  expect(response.ok()).toBeTruthy();
  const body = await response.json() as { users: { email: string; current_enrollment: { id: string } | null }[] };
  const user = body.users.find((candidate) => candidate.email === email);
  if (!user?.current_enrollment) throw new Error(`No enrollment for ${email}`);
  return user.current_enrollment.id;
}

/**
 * Join a cycle from the student's own card. A cycle whose policy requires
 * approval labels both the trigger and the confirm differently and lands the
 * member on `Pending` rather than `Active`, so the caller says which it is.
 */
async function joinCycle(page: Page, cycleName: string, approval: boolean = false) {
  await page.goto("/cycles");
  const card = page.getByRole("heading", { name: cycleName }).locator("xpath=../..");
  await card
    .getByRole("button", { name: approval ? "Request to join" : "Join", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("combobox", { name: "Resume for this cycle *", exact: true })
    .selectOption({ label: "Primary resume" });
  await dialog
    .getByRole("combobox", { name: "Consent *", exact: true })
    .selectOption({ label: "I consent to sharing my application data" });
  await dialog
    .getByRole("button", { name: approval ? "Request to join" : "Join cycle", exact: true })
    .click();
  await expect(card.getByText(approval ? "Pending" : "Active", { exact: true })).toBeVisible();
}

/**
 * The taxonomy ids a rule names.
 *
 * ELG-2 rules address programs and branches by id, and the nested rule Step 19
 * asks for has to be written as JSON — the clause list compiles to `all[...]`
 * of flat leaves and cannot express an `any` (observation O.5). So the ids come
 * from the same screen the builder's own pickers read.
 */
async function taxonomyIds(page: Page): Promise<{
  programs: Record<string, string>;
  branches: Record<string, string>;
}> {
  const response = await page.request.get("/api/v1/screens/staff/taxonomies");
  expect(response.ok()).toBeTruthy();
  const body = (await response.json()) as {
    programs: { id: string; name: string }[];
    branches: { id: string; name: string }[];
  };
  const index = (rows: { id: string; name: string }[]) =>
    Object.fromEntries(rows.map((row) => [row.name, row.id]));
  return { programs: index(body.programs), branches: index(body.branches) };
}

function jobCard(page: Page, title: string) {
  return page.getByRole("link", { name: title, exact: true }).locator("xpath=ancestor::li[1]");
}

/** Create one job in a cycle and return the builder id it lands on. */
async function createJob(
  page: Page,
  cycleId: string,
  {
    title,
    company,
    description,
    deadline,
  }: { title: string; company: string; description: string; deadline: string },
): Promise<string> {
  await page.goto(`/staff/cycles/${cycleId}/jobs`);
  await page.getByRole("button", { name: "New job" }).click();
  await page.getByRole("textbox", { name: "Title" }).fill(title);
  await page.getByRole("combobox", { name: "Company" }).selectOption({ label: company });
  await page.getByRole("textbox", { name: "Description" }).fill(description);
  await page.getByLabel("Application deadline").fill(deadline);
  await page.getByRole("button", { name: "Create job" }).click();
  const link = page.getByRole("link", { name: title, exact: true });
  await expect(link).toBeVisible();
  const href = await link.getAttribute("href");
  const jobId = href?.match(/\/staff\/jobs\/([^?]+)/)?.[1];
  if (!jobId) throw new Error(`Could not resolve the new job ${title}`);
  return jobId;
}

/**
 * Write a rule tree straight into the editor's JSON escape hatch.
 *
 * The builder resolves its cycle from `?cycle_id=`, which is why every link
 * into it carries one: opened without it the screen says so rather than
 * guessing which season's membership to evaluate a rule against.
 */
async function writeRule(page: Page, cycleId: string, jobId: string, rule: unknown) {
  await openEligibility(page, cycleId, jobId);
  await page.getByRole("button", { name: "Edit as JSON" }).click();
  await page.getByRole("textbox", { name: "Rule tree" }).fill(JSON.stringify(rule, null, 2));
}

async function openEligibility(page: Page, cycleId: string, jobId: string) {
  await page.goto(`/staff/jobs/${jobId}?cycle_id=${cycleId}`);
  await page.getByRole("tab", { name: /^Eligibility/ }).click();
  await expect(page.getByRole("heading", { name: "Eligibility rule" })).toBeVisible();
}

/**
 * Build Stage 2's nested rule the way a coordinator has to: through the
 * clause and group controls, never the JSON box.
 *
 * This is Step 19's own question — "could they?" — and until the group
 * controls existed the answer was no, because `any` was reachable only through
 * **Edit as JSON** (observation O.5, ruled a product gap against LLD §9.1).
 * Driving the real controls is the only thing that answers it.
 */
async function buildNestedRule(
  page: Page,
  cycleId: string,
  jobId: string,
  { program, branchA, cpiA, branchB, cpiB }: {
    program: string;
    branchA: string;
    cpiA: string;
    branchB: string;
    cpiB: string;
  },
) {
  await openEligibility(page, cycleId, jobId);

  // Top level: the program clause and the backlog clause, which are ordinary
  // flat conditions, with the group between them. Each clause and each group
  // is a region named by its own label, so no locator has to walk the DOM.
  const palette = page.getByRole("group", { name: "Add a condition or a group" });
  await palette.getByRole("button", { name: "Primary programs" }).click();
  await page
    .getByRole("region", { name: "Primary programs" })
    .getByRole("checkbox", { name: program })
    .check();

  await palette.getByRole("button", { name: "Any of these" }).click();
  const group = page.getByRole("region", { name: "Any of these" });
  await expect(group.getByText("Option 1")).toBeVisible();
  await expect(group.getByText("Option 2")).toBeVisible();

  for (const [index, [branch, cpi]] of [
    [branchA, cpiA],
    [branchB, cpiB],
  ].entries()) {
    // Addressed by name, not by position: an option's own clause rows are
    // list items too, so `nth(index)` would drift to one of them.
    const option = group.getByRole("group", { name: `Option ${index + 1}` });
    const optionPalette = option.getByRole("group", {
      name: `Add a condition to option ${index + 1}`,
    });
    await optionPalette.getByRole("button", { name: "Primary branches" }).click();
    await option.getByRole("checkbox", { name: branch as string }).check();
    await optionPalette.getByRole("button", { name: "Minimum CPI" }).click();
    await option.getByRole("spinbutton", { name: "Minimum CPI" }).fill(cpi as string);
  }

  await palette.getByRole("button", { name: "Maximum active backlogs" }).click();
  await page
    .getByRole("region", { name: "Maximum active backlogs" })
    .getByRole("spinbutton", { name: "Maximum active backlogs" })
    .fill("0");

  // The JSON escape hatch was never opened, which is the whole point.
  await expect(page.getByRole("textbox", { name: "Rule tree" })).toHaveCount(0);
}

/** The id of a job that already exists in a cycle, read off the staff list. */
async function staffJobId(page: Page, cycleId: string, title: string): Promise<string> {
  await page.goto(`/staff/cycles/${cycleId}/jobs`);
  const href = await page.getByRole("link", { name: title, exact: true }).getAttribute("href");
  const jobId = href?.match(/\/staff\/jobs\/([^?]+)/)?.[1];
  if (!jobId) throw new Error(`Could not resolve the job ${title}`);
  return jobId;
}

/** The same id from the student side, which is the only list they can see. */
async function staffJobIdAsStudent(page: Page, email: string, title: string): Promise<string> {
  await login(page, email);
  await page.goto("/cycles");
  await page.getByRole("link", { name: SUMMER_CYCLE, exact: true }).click();
  const href = await page.getByRole("link", { name: title, exact: true }).getAttribute("href");
  const jobId = href?.match(/\/jobs\/([^?]+)/)?.[1];
  await logout(page);
  if (!jobId) throw new Error(`Could not resolve the job ${title}`);
  return jobId;
}

/**
 * Give a job its pipeline, before anybody applies to it.
 *
 * The script never says when a job's rounds are created — Step 25 simply opens
 * on "Round 1" — and the order is not free: `apply` places an application in
 * the job's *first* round, so a job whose rounds arrive after its applications
 * leaves everyone sitting before round one, where RND-1 has nothing to advance
 * them from. Building the rounds is therefore part of building the job.
 */
async function addRounds(page: Page, cycleId: string, jobId: string, names: readonly string[]) {
  await page.goto(`/staff/jobs/${jobId}?cycle_id=${cycleId}`);
  await page.getByRole("tab", { name: /^Rounds/ }).click();
  await expect(page.getByRole("heading", { name: "Rounds" })).toBeVisible();
  for (const name of names) {
    await page.getByRole("button", { name: "Add round" }).click();
    await page.getByRole("textbox", { name: "Name" }).last().fill(name);
    await page.getByRole("combobox", { name: "Type" }).last().selectOption({ label: name });
  }
  await page.getByRole("button", { name: "Save rounds" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Save rounds" }).click();
  await expect(dialog).toBeHidden();
}

/** All summer jobs run these two, so Step 31 has a round to skip. */
const ROUNDS = ["Online Assessment", "Technical"] as const;

async function publishJob(page: Page, cycleId: string, jobId: string) {
  await page.goto(`/staff/jobs/${jobId}?cycle_id=${cycleId}`);
  await page.getByRole("button", { name: "Publish", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Publish", exact: true }).click();
  await expect(page.getByRole("button", { name: "Unpublish" })).toBeVisible();
}

/** Every question type APP-1 offers, on one job (Step 22). */
const QUESTIONS = [
  { text: "Why this internship?", type: "Short text", required: true },
  { text: "Describe something you built", type: "Long text" },
  { text: "Preferred team", type: "Choose one", options: ["Firmware", "Controls"] },
  { text: "Toolchains you know", type: "Choose several", options: ["C", "Rust", "Python"] },
  { text: "Available for eight weeks?", type: "Yes / no" },
  { text: "Years of embedded experience", type: "Number" },
  { text: "Earliest start date", type: "Date" },
  { text: "Email for scheduling", type: "Email" },
  { text: "Portfolio link", type: "Link", required: true },
] as const;

/**
 * Build the application form through the builder's own controls.
 *
 * Each row is filled as it is added, so the "last" row is always the new one —
 * the fields carry one label per row and addressing them by index would break
 * the moment a row moved.
 */
async function addQuestions(page: Page, cycleId: string, jobId: string) {
  await page.goto(`/staff/jobs/${jobId}?cycle_id=${cycleId}`);
  await page.getByRole("tab", { name: /^Questions/ }).click();
  await expect(page.getByRole("heading", { name: "Application form" })).toBeVisible();
  for (const question of QUESTIONS) {
    await page.getByRole("button", { name: "Add question" }).click();
    await page.getByRole("textbox", { name: "Question" }).last().fill(question.text);
    await page
      .getByRole("combobox", { name: "Answer type" })
      .last()
      .selectOption({ label: question.type });
    if ("required" in question && question.required) {
      await page.getByRole("checkbox", { name: "Required" }).last().check();
    }
    for (const [index, option] of ("options" in question ? question.options : []).entries()) {
      await page.getByRole("button", { name: "Add option" }).last().click();
      await page.getByRole("textbox", { name: `Option ${index + 1}` }).last().fill(option);
    }
  }
  await page.getByRole("button", { name: "Save questions" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Save questions" }).click();
  await expect(dialog).toBeHidden();
}

/** Answer the form as a student and submit it. */
async function applyWithAnswers(page: Page, jobId: string, jobTitle: string, full: boolean) {
  await page.goto(`/jobs/${jobId}`);
  await expect(page.getByRole("heading", { name: jobTitle })).toBeVisible();
  const form = page.locator("#application-form form");
  await form.getByRole("textbox", { name: "Why this internship?" }).fill("Robotics is the reason I came here.");
  await form.getByRole("textbox", { name: "Portfolio link" }).fill("https://example.com/portfolio");
  if (full) {
    await form.getByRole("textbox", { name: "Describe something you built" }).fill("A line-following robot with a custom PID loop.");
    await form.getByRole("combobox", { name: "Preferred team" }).selectOption("Firmware");
    await form.getByRole("checkbox", { name: "C" }).check();
    await form.getByRole("checkbox", { name: "Python" }).check();
    await form.getByRole("combobox", { name: "Available for eight weeks?" }).selectOption("true");
    await form.getByRole("spinbutton", { name: "Years of embedded experience" }).fill("2");
    await form.getByLabel("Earliest start date").fill("2027-05-10");
    await form.getByRole("textbox", { name: "Email for scheduling" }).fill("scheduling@example.com");
  }
  await form.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(
    page.getByText("You already have an application for this job.", { exact: false }),
  ).toBeVisible();
}

/** Move a named set out of the round they are sitting in. */
async function advanceOnBoard(
  page: Page,
  jobId: string,
  who: readonly (keyof typeof students)[],
) {
  await page.goto(`/staff/jobs/${jobId}/board`);
  for (const key of who) {
    await page.getByRole("checkbox", { name: `Select ${students[key][1]}` }).check();
  }
  await page.getByRole("button", { name: "Advance", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(`Will move (${who.length})`)).toBeVisible();
  await dialog.getByRole("button", { name: "Advance", exact: true }).click();
  await expect(dialog).toBeHidden();
}

/** Extend an offer to a named set from wherever they currently sit. */
async function extendOffers(
  page: Page,
  jobId: string,
  who: readonly (keyof typeof students)[],
) {
  await page.goto(`/staff/jobs/${jobId}/offers`);
  for (const key of who) {
    await page.getByRole("checkbox", { name: `Select ${students[key][1]}` }).check();
  }
  await page.getByRole("button", { name: "Extend / rollout" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(`Will be offered (${who.length})`)).toBeVisible();
  for (const key of who) {
    await expect(dialog.getByText(students[key][1], { exact: false })).toBeVisible();
  }
  await dialog.getByRole("button", { name: "Extend offers" }).click();
  await expect(dialog).toBeHidden();
}

async function staffCycleId(page: Page, cycleName: string): Promise<string> {
  await page.goto("/staff/cycles");
  const href = await page.getByRole("link", { name: cycleName, exact: true }).getAttribute("href");
  const id = href?.match(/\/staff\/cycles\/([^/?]+)/)?.[1];
  if (!id) throw new Error(`Could not resolve cycle ${cycleName}`);
  return id;
}

async function applyToJob(page: Page, jobId: string, jobTitle: string) {
  await page.goto(`/jobs/${jobId}`);
  await expect(page.getByRole("heading", { name: jobTitle })).toBeVisible();
  const form = page.locator("#application-form form");
  await expect(form).toBeVisible();
  await form.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(
    page.getByText("You already have an application for this job.", { exact: false }),
  ).toBeVisible();
}

/** Accept one currently offered job from the student's dashboard. */
async function acceptDashboardOffer(page: Page, jobTitle: string) {
  await page.goto("/dashboard");
  const row = page
    .getByRole("link", { name: jobTitle, exact: true })
    .locator("xpath=ancestor::li[1]");
  await row.getByRole("button", { name: "Accept", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Accept offer" }).click();
  await expect(dialog).toBeHidden();
  await expect(
    page.getByText(jobTitle, { exact: true }).locator("xpath=ancestor::li[1]"),
  ).toContainText("Accepted");
}

/** Build the open export dialog and exercise the browser download path. */
async function buildAndDownloadExport(page: Page) {
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Build export" }).click();
  const downloadLink = dialog.getByRole("link", { name: "Download" });
  await expect(downloadLink).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    downloadLink.click(),
  ]);
  expect(await download.failure()).toBeNull();
}

function applicationCard(page: Page, jobTitle: string) {
  return page
    .getByRole("link", { name: jobTitle, exact: true })
    .locator("xpath=ancestor::div[.//button or .//details][1]");
}

async function recordOpenOutcome(
  page: Page,
  jobId: string,
  student: string,
  studentEmail: string,
  outcome: "accepted" | "rejected",
) {
  await page.goto(`/staff/jobs/${jobId}/offers`);
  const row = page.getByText(studentEmail, { exact: false }).locator("xpath=ancestor::li[1]");
  await row.getByRole("checkbox", { name: `Select ${student}` }).check();
  await page.getByRole("combobox", { name: "Outcome" }).selectOption(outcome);
  await page.getByRole("button", { name: "Record outcome" }).click();
  const dialog = page.getByRole("dialog");
  if (outcome === "rejected") {
    await dialog.getByRole("textbox", { name: "Reason" }).fill("Not selected by company");
  }
  await dialog.getByRole("button", { name: "Record outcome" }).click();
  await expect(dialog).toBeHidden();
}

test.describe.serial("Part D — named four-cycle lifecycle", () => {
  test.setTimeout(180_000);

  test("D.1-D.6 onboarding, field ownership, restricted resume, idempotent bulk upsert, and audit", async ({ page }) => {
    page.setDefaultTimeout(8_000);
    // D.1: every named identity, including both coordinators and the admin, can use dev-login.
    for (const email of [
      ...Object.values(students).map(([studentEmail]) => studentEmail),
      PRIMARY_COORDINATOR,
      COORD2,
      ADMIN,
    ]) {
      await login(page, email);
      await logout(page);
    }

    // D.2: only P5 and P10 begin undeclared and complete the real form.
    await declareProfile(page, {
      email: students.p5[0], program: "BTech", branch: "Mechanical", cpi: "7.10", active: "1", total: "1",
    });
    await declareProfile(page, {
      email: students.p10[0], program: "BTech", branch: "Civil", cpi: "7.40", active: "0", total: "2",
    });

    // D.3: the server-provided ownership model locks P1's roster identity and
    // tells them who owns it, while the semesterly figures stay theirs to keep
    // current -- CPI renders as the input holding today's value, not a fact.
    await login(page, students.p1[0]);
    await page.getByRole("link", { name: "My profile", exact: true }).click();
    await expect(page.getByText("Locked fields now belong to the administration", { exact: false })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Program" })).toHaveCount(0);
    const programFact = page.getByText("Program", { exact: true }).locator("..");
    await expect(programFact).toContainText("BTech");
    await expect(page.getByRole("spinbutton", { name: "CPI" })).toHaveValue("8.60");
    await logout(page);

    // D.4: URL shape is all that is checked; a restricted Drive file is accepted silently.
    await login(page, students.p6[0]);
    await page.getByRole("link", { name: "My profile", exact: true }).click();
    const restricted = "https://drive.google.com/file/d/1RestrictedLifecycleResume0000001/view";
    await page.getByRole("textbox", { name: "Label" }).fill("Restricted resume");
    await page.getByRole("textbox", { name: "Google Drive / Docs file link" }).fill(restricted);
    await page.getByRole("button", { name: "Add resume" }).click();
    await expect(page.getByRole("link", { name: restricted })).toBeVisible();
    await logout(page);

    await login(page, ADMIN);
    await page.goto("/admin/bulk-upsert");
    await expect(page.getByRole("heading", { name: "Bulk profile upsert" })).toBeVisible();

    // Establish deliberately stale values through the same browser surface; the Part D file below corrects them.
    await uploadCsv(page, "stale.csv", [
      "institute_email,roll_number,cpi",
      `${students.p1[0]},99000001,8.50`,
      `${students.p4[0]},99000004,7.70`,
      `${students.p8[0]},99000008,7.84`,
    ].join("\n"));
    let dialog = await previewAndCommit(page);
    await dialog.getByRole("button", { name: "Commit batch" }).click();
    await expect(page.getByText("Commit report")).toBeVisible();

    // D.5: one file produces updates, staging, and two distinct row errors.
    const correction = [
      "institute_email,roll_number,cpi,program",
      `${students.p1[0]},99000001,8.60,`,
      `${students.p4[0]},99000004,7.80,`,
      `${students.p8[0]},99000008,7.94,`,
      "demo.future@example.edu,99000999,8.00,BTech",
      `${students.p2[0]},WRONG-ROLL,8.20,`,
      `${students.p3[0]},99000003,7.95,Unknown Program`,
    ].join("\n");
    await uploadCsv(page, "part-a4-corrections.csv", correction);
    dialog = await previewAndCommit(page);
    await expect(dialog.getByText(`${students.p1[0]} → updated`, { exact: false })).toBeVisible();
    await expect(dialog.getByText(`${students.p4[0]} → updated`, { exact: false })).toBeVisible();
    await expect(dialog.getByText(`${students.p8[0]} → updated`, { exact: false })).toBeVisible();
    await expect(
      dialog.getByText("demo.future@example.edu → staged", { exact: false }),
    ).toBeVisible();
    await expect(dialog.getByText(/demo.student02.* → error.*roll number does not match/i)).toBeVisible();
    await expect(dialog.getByText(/demo.student03.* → error.*Program 'Unknown Program' is not an active option/i)).toBeVisible();
    await dialog.getByRole("button", { name: "Commit batch" }).click();
    await expect(page.getByText("Commit report")).toBeVisible();

    await uploadCsv(page, "part-a4-corrections.csv", correction);
    dialog = await previewAndCommit(page);
    await expect(dialog.getByText(`${students.p1[0]} → unchanged`, { exact: false })).toBeVisible();
    await expect(dialog.getByText(`${students.p4[0]} → unchanged`, { exact: false })).toBeVisible();
    await expect(dialog.getByText(`${students.p8[0]} → unchanged`, { exact: false })).toBeVisible();
    await expect(
      dialog.getByText("demo.future@example.edu → unchanged", { exact: false }),
    ).toBeVisible();
    await dialog.getByRole("button", { name: "Commit batch" }).click();

    // D.6: render the dispute screen and verify the audit gives actor and before/after values.
    const p1Enrollment = await enrollmentId(page, students.p1[0]);
    await page.goto(`/staff/student/${p1Enrollment}`);
    await expect(page.getByRole("heading", { name: students.p1[1] })).toBeVisible();
    const correctionAuditRow = page
      .getByText("Bulk upsert profiles.row", { exact: true })
      .last()
      .locator("xpath=ancestor::li[1]");
    await expect(correctionAuditRow).toContainText("CDS Administrator");
    await expect(correctionAuditRow).toContainText("8.50");
    await expect(correctionAuditRow).toContainText("8.60");
  });

  test("D.7-D.13 open-cycle memberships, uncapped outcomes, and external offer capture", async ({ page }) => {
    page.setDefaultTimeout(8_000);

    // D.7: the open-cycle create form exposes its otherwise-unfixed outcome,
    // permits no deadline, and publishes the new internship job.
    await login(page, PRIMARY_COORDINATOR);
    await page.goto("/staff/cycles");
    await page.getByRole("link", { name: OPEN_CYCLE, exact: true }).click();
    await page.getByRole("link", { name: "Jobs", exact: true }).click();

    const jobOneHref = await page
      .getByRole("link", { name: OPEN_JOB_ONE, exact: true })
      .getAttribute("href");
    const jobOneId = jobOneHref?.match(/\/staff\/jobs\/([^?]+)/)?.[1];
    if (!jobOneId) throw new Error("Could not resolve seeded open-cycle job");

    await page.getByRole("button", { name: "New job" }).click();
    await page.getByRole("textbox", { name: "Title" }).fill(OPEN_JOB_TWO);
    await page.getByRole("combobox", { name: "Company" }).selectOption({ label: "BluePeak Analytics" });
    const outcome = page.getByRole("combobox", { name: "Outcome" });
    await expect(outcome).toBeVisible();
    await outcome.selectOption("internship");
    await page.getByRole("textbox", { name: "Description" }).fill("An open-cycle internship without an application deadline.");
    await expect(page.getByLabel("Application deadline")).toHaveValue("");
    await page.getByRole("button", { name: "Create job" }).click();

    const jobTwoLink = page.getByRole("link", { name: OPEN_JOB_TWO, exact: true });
    await expect(jobTwoLink).toBeVisible();
    const jobTwoHref = await jobTwoLink.getAttribute("href");
    const jobTwoId = jobTwoHref?.match(/\/staff\/jobs\/([^?]+)/)?.[1];
    if (!jobTwoId) throw new Error("Could not resolve second open-cycle job");
    await jobTwoLink.click();
    await page.getByRole("button", { name: "Publish", exact: true }).click();
    let dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Publish", exact: true }).click();
    await expect(page.getByRole("button", { name: "Unpublish" })).toBeVisible();

    // The third open job differs from the second in exactly one field, which
    // is the point: an open cycle fixes no outcome (JOB-6), so the same screen
    // produces an internship and a placement side by side. P2's application to
    // this one is what Step 42's cross-cycle cascade reaches.
    await page.goto(`/staff/cycles/${await staffCycleId(page, OPEN_CYCLE)}/jobs`);
    await page.getByRole("button", { name: "New job" }).click();
    await page.getByRole("textbox", { name: "Title" }).fill(OPEN_JOB_THREE);
    await page.getByRole("combobox", { name: "Company" }).selectOption({ label: "Ashbourne Capital" });
    await page.getByRole("combobox", { name: "Outcome" }).selectOption("placement");
    await page
      .getByRole("textbox", { name: "Description" })
      .fill("An open-cycle graduate placement, carried outside the placement season.");
    await page.getByRole("button", { name: "Create job" }).click();

    const jobThreeLink = page.getByRole("link", { name: OPEN_JOB_THREE, exact: true });
    await expect(jobThreeLink).toBeVisible();
    const jobThreeHref = await jobThreeLink.getAttribute("href");
    const jobThreeId = jobThreeHref?.match(/\/staff\/jobs\/([^?]+)/)?.[1];
    if (!jobThreeId) throw new Error("Could not resolve third open-cycle job");
    await jobThreeLink.click();
    await page.getByRole("button", { name: "Publish", exact: true }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Publish", exact: true }).click();
    await expect(page.getByRole("button", { name: "Unpublish" })).toBeVisible();
    await logout(page);

    // D.8-D.9: open registration activates immediately; the named students
    // apply in the requested distribution and P6 withdraws her application.
    // P2 takes one job of each outcome, which is what lets Step 42 cascade one
    // of them while Step 58 still has the other to archive.
    for (const [key, jobs] of [
      ["p1", [[jobOneId, OPEN_JOB_ONE], [jobTwoId, OPEN_JOB_TWO]]],
      ["p2", [[jobOneId, OPEN_JOB_ONE], [jobThreeId, OPEN_JOB_THREE]]],
      ["p4", [[jobOneId, OPEN_JOB_ONE]]],
      ["p6", [[jobOneId, OPEN_JOB_ONE]]],
    ] as const) {
      const student = students[key];
      await login(page, student[0]);
      await joinCycle(page, OPEN_CYCLE);
      for (const [jobId, title] of jobs) await applyToJob(page, jobId, title);
      if (key === "p6") {
        await page.goto("/applications");
        const card = applicationCard(page, OPEN_JOB_ONE);
        await card.getByRole("button", { name: "Withdraw", exact: true }).click();
        dialog = page.getByRole("dialog");
        await dialog.getByRole("button", { name: "Withdraw", exact: true }).click();
        await expect(card.getByText("Withdrawn", { exact: true }).first()).toBeVisible();
      }
      await logout(page);
    }

    // D.10: direct acceptance creates offer-extension and acceptance events,
    // while an internship application in the same uncapped open cycle keeps running.
    await login(page, PRIMARY_COORDINATOR);
    await recordOpenOutcome(page, jobOneId, students.p1[1], students.p1[0], "accepted");
    await logout(page);
    await login(page, students.p1[0]);
    await page.goto("/applications");
    const first = applicationCard(page, OPEN_JOB_ONE);
    const second = applicationCard(page, OPEN_JOB_TWO);
    await expect(first.getByText("Accepted", { exact: true }).first()).toBeVisible();
    await expect(second.getByText("In progress", { exact: true }).first()).toBeVisible();
    await first.locator("summary").click();
    const timeline = first.locator("ol");
    await expect(timeline.getByText("Offer extended", { exact: true })).toBeVisible();
    await expect(
      timeline.locator("span.text-foreground", { hasText: /^Accepted$/ }),
    ).toBeVisible();
    await logout(page);

    // D.11: a second acceptance is allowed because open cycles are uncapped.
    await login(page, PRIMARY_COORDINATOR);
    await recordOpenOutcome(page, jobTwoId, students.p1[1], students.p1[0], "accepted");
    await logout(page);
    await login(page, students.p1[0]);
    await page.goto("/applications");
    await expect(applicationCard(page, OPEN_JOB_ONE).getByText("Accepted", { exact: true }).first()).toBeVisible();
    await expect(applicationCard(page, OPEN_JOB_TWO).getByText("Accepted", { exact: true }).first()).toBeVisible();
    await logout(page);

    // D.12: P4's rejection is recorded. SES delivery remains a separate,
    // human-only check until the guessed institute addresses are confirmed.
    await login(page, PRIMARY_COORDINATOR);
    await recordOpenOutcome(page, jobOneId, students.p4[1], students.p4[0], "rejected");
    await logout(page);
    await login(page, students.p4[0]);
    await page.goto("/applications");
    await expect(applicationCard(page, OPEN_JOB_ONE).getByText("Rejected", { exact: true }).first()).toBeVisible();
    await logout(page);

    // D.13: an off-campus internship must carry its own stipend. Keep this
    // assertion: the current screen cannot express that command field.
    await login(page, PRIMARY_COORDINATOR);
    await page.goto("/staff/external");
    await page.getByRole("button", { name: "Record external offer" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("combobox", { name: "Student *", exact: true }).selectOption({ label: `${students.p2[1]} (99000002)` });
    await dialog.getByRole("combobox", { name: "Company *", exact: true }).selectOption({ label: "BluePeak Analytics" });
    await dialog.getByRole("combobox", { name: "Outcome *", exact: true }).selectOption("internship");
    await dialog.getByRole("combobox", { name: "Source *", exact: true }).selectOption("off_campus");
    await dialog.getByRole("combobox", { name: "Status *", exact: true }).selectOption("accepted");
    await dialog.getByRole("spinbutton", { name: "Stipend per month (INR)" }).fill("65000");
    await dialog.getByRole("textbox", { name: "Reason / evidence *", exact: true }).fill("Verified off-campus internship offer");
    await expect(dialog.getByText("What will happen")).toBeVisible();
    await dialog.getByRole("button", { name: "Record offer" }).click();
    await expect(dialog).toBeHidden();
    await logout(page);

    await login(page, students.p2[0]);
    await page.goto("/dashboard");
    const external = page
      .getByText("BluePeak Analytics", { exact: true })
      .locator("xpath=ancestor::li[1]");
    await expect(external).toContainText("Off campus \u00b7 Internship");
    await expect(external).toContainText("65000");
    await expect(external.getByRole("button")).toHaveCount(0);
  });

  test("D.14-D.15 summer-cycle policy and the approval queue every student waits in", async ({ page }) => {
    page.setDefaultTimeout(8_000);

    // D.14: the five policy settings Stage 2 depends on, read off the cycle
    // the humans will run it in rather than assumed from the seed.
    await login(page, PRIMARY_COORDINATOR);
    const summerId = await staffCycleId(page, SUMMER_CYCLE);
    await page.goto(`/staff/cycles/${summerId}`);
    await expect(page.getByRole("heading", { name: SUMMER_CYCLE })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "Membership needs approval" })).toBeChecked();
    await expect(page.getByRole("checkbox", { name: "Absence earns a strike" })).toBeChecked();
    await expect(
      page.getByRole("checkbox", { name: "Allow withdrawal after the deadline" }),
    ).not.toBeChecked();
    await expect(page.getByRole("spinbutton", { name: "Accepted-offer cap" })).toHaveValue("1");
    await expect(page.getByRole("combobox", { name: "When an offer expires" })).toHaveValue(
      "auto_decline",
    );
    await logout(page);

    // D.15: every one of the eleven joins and lands in the queue. A pending
    // member's card carries the status and withholds the jobs link, so the
    // cycle is unreachable from the only place that offers it.
    for (const [email] of Object.values(students)) {
      await login(page, email);
      await joinCycle(page, SUMMER_CYCLE, true);
      await expect(page.getByRole("link", { name: SUMMER_CYCLE, exact: true })).toHaveCount(0);
      await logout(page);
    }

    // The coordinator sees all eleven waiting, and none of them approved.
    await login(page, PRIMARY_COORDINATOR);
    await page.goto(`/staff/cycles/${summerId}/approvals`);
    for (const [, fullName] of Object.values(students)) {
      await expect(page.getByText(fullName, { exact: false }).first()).toBeVisible();
    }
    await logout(page);
  });

  test("D.16 an incomplete profile is refused with the checklist that names it", async ({ page }) => {
    page.setDefaultTimeout(8_000);

    // The script has P5 attempt this join with a profile that was never
    // finished. By D.2 his is, and by D.15 he is already in the queue, so the
    // operator does what P5's card tells them to: clears a locked field. That
    // is `admin_update_profile`, which had no browser surface until now.
    await login(page, ADMIN);
    const p5Enrollment = await enrollmentId(page, students.p5[0]);
    await page.goto(`/staff/student/${p5Enrollment}`);
    await expect(page.getByRole("heading", { name: students.p5[1] })).toBeVisible();
    await page.getByRole("button", { name: "Edit profile" }).click();
    let dialog = page.getByRole("dialog");
    // Seeded with what is true now, not an empty form somebody could save over
    // the record by accident.
    await expect(dialog.getByRole("spinbutton", { name: "CPI" })).toHaveValue("7.10");
    await expect(dialog.getByRole("textbox", { name: "Roll number" })).toHaveValue("99000005");
    await dialog.getByRole("spinbutton", { name: "CPI" }).fill("");
    await expect(dialog.getByText("CPI changes")).toBeVisible();
    await dialog.getByRole("button", { name: "Save profile" }).click();
    await expect(dialog).toBeHidden();

    // The correction is on the record with its actor and both values, which is
    // what a dispute about it would be answered from.
    const clearedRow = page
      .getByText("Admin update profile", { exact: true })
      .first()
      .locator("xpath=ancestor::li[1]");
    await expect(clearedRow).toContainText("CDS Administrator");
    await expect(clearedRow).toContainText("CPI: 7.10 → —");
    await logout(page);

    // D.16: P5 leaves the queue and tries to come back in. Re-entry re-runs
    // the whole join gauntlet (the design review §4.34), so this is the same refusal
    // a first join would give — and the card names every unmet requirement
    // rather than the first one.
    await login(page, students.p5[0]);
    await page.goto("/cycles");
    const card = page.getByRole("heading", { name: SUMMER_CYCLE }).locator("xpath=../..");
    await card.getByRole("button", { name: "Cancel request" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Cancel request" }).click();
    await expect(card.getByText("Withdrawn", { exact: true })).toBeVisible();
    await expect(card.getByText("CPI is required to join a cycle")).toBeVisible();

    await card.getByRole("button", { name: "Register again" }).click();
    dialog = page.getByRole("dialog");
    await dialog
      .getByRole("combobox", { name: "Resume for this cycle *", exact: true })
      .selectOption({ label: "Primary resume" });
    await dialog
      .getByRole("combobox", { name: "Consent *", exact: true })
      .selectOption({ label: "I consent to sharing my application data" });
    // The preview refuses before anything is sent, with the checklist itself.
    await expect(dialog.getByText("CPI is required to join a cycle")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Request again" })).toBeDisabled();
    await page.keyboard.press("Escape");
    await logout(page);

    // Put P5 back where Step 17 expects him: CPI restored, request pending.
    await login(page, ADMIN);
    await page.goto(`/staff/student/${p5Enrollment}`);
    await page.getByRole("button", { name: "Edit profile" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("spinbutton", { name: "CPI" }).fill("7.10");
    await expect(dialog.getByText("CPI changes")).toBeVisible();
    await dialog.getByRole("button", { name: "Save profile" }).click();
    await expect(dialog).toBeHidden();
    await logout(page);

    await login(page, students.p5[0]);
    await page.goto("/cycles");
    const restored = page.getByRole("heading", { name: SUMMER_CYCLE }).locator("xpath=../..");
    await restored.getByRole("button", { name: "Register again" }).click();
    dialog = page.getByRole("dialog");
    await dialog
      .getByRole("combobox", { name: "Resume for this cycle *", exact: true })
      .selectOption({ label: "Primary resume" });
    await dialog
      .getByRole("combobox", { name: "Consent *", exact: true })
      .selectOption({ label: "I consent to sharing my application data" });
    await dialog.getByRole("button", { name: "Request again" }).click();
    await expect(restored.getByText("Pending", { exact: true })).toBeVisible();
    await logout(page);
  });

  test("D.17-D.18 bulk approval names what matched nothing, and a rejection is re-requested", async ({ page }) => {
    page.setDefaultTimeout(8_000);
    await login(page, PRIMARY_COORDINATOR);
    const summerId = await staffCycleId(page, SUMMER_CYCLE);
    await page.goto(`/staff/cycles/${summerId}/approvals`);

    // D.17: ten of the eleven by roll number, plus two that match nobody. P7
    // is left out — Step 18 rejects him before he is ever approved.
    const nonsense = ["25119999", "NOT-A-ROLL"];
    await page.getByRole("button", { name: "Paste roll numbers or emails" }).click();
    await page
      .getByRole("textbox", { name: "Paste roll numbers or emails" })
      .fill([...ROLLS_EXCEPT_P7, ...nonsense].join("\n"));
    await page.getByRole("button", { name: "Add to selection" }).click();

    await page.getByRole("button", { name: "Approve selected" }).click();
    let dialog = page.getByRole("dialog");
    // Listed individually, never counted (the design review §4.21, widened by §4.37):
    // two typos in a paste of twelve are the two to go and check.
    await expect(dialog.getByText("Matched nothing (2)")).toBeVisible();
    for (const identifier of nonsense) {
      await expect(dialog.getByText(identifier, { exact: true })).toBeVisible();
    }
    // And the ten that will apply arrive as people, not as membership ids.
    await expect(dialog.getByText("Will approve (10)")).toBeVisible();
    for (const key of Object.keys(students) as (keyof typeof students)[]) {
      if (key === "p7") continue;
      await expect(dialog.getByText(students[key][1], { exact: true })).toBeVisible();
    }
    await dialog.getByRole("button", { name: "Approve" }).click();
    await expect(dialog).toBeHidden();

    // Ten active, and P7 still the only one waiting.
    await page.getByRole("combobox", { name: "Membership status" }).selectOption("active");
    await expect(page.getByText("10 active members in this cycle.")).toBeVisible();
    await page.getByRole("combobox", { name: "Membership status" }).selectOption("pending");
    await expect(page.getByText("1 request waiting on a decision.")).toBeVisible();

    // D.18: P7 is rejected with a reason he can act on.
    const p7Row = page.getByText(students.p7[0], { exact: false }).locator("xpath=ancestor::tr[1]");
    await p7Row.getByRole("button", { name: "Reject" }).click();
    dialog = page.getByRole("dialog");
    await dialog
      .getByRole("textbox", { name: "Reason *", exact: true })
      .fill("MTech intake needs the department's sign-off first");
    await dialog.getByRole("button", { name: "Reject request" }).click();
    await expect(dialog).toBeHidden();
    await logout(page);

    // P7 reads the reason on his own card and asks again.
    await login(page, students.p7[0]);
    await page.goto("/cycles");
    const card = page.getByRole("heading", { name: SUMMER_CYCLE }).locator("xpath=../..");
    await expect(card.getByText("Rejected", { exact: true })).toBeVisible();
    await expect(
      card.getByText("Reason: MTech intake needs the department's sign-off first"),
    ).toBeVisible();
    await card.getByRole("button", { name: "Request again" }).click();
    dialog = page.getByRole("dialog");
    await dialog
      .getByRole("combobox", { name: "Resume for this cycle *", exact: true })
      .selectOption({ label: "Primary resume" });
    await dialog
      .getByRole("combobox", { name: "Consent *", exact: true })
      .selectOption({ label: "I consent to sharing my application data" });
    await dialog.getByRole("button", { name: "Request again" }).click();
    await expect(card.getByText("Pending", { exact: true })).toBeVisible();
    await logout(page);

    // Approved on the second pass, so all eleven are members going into Stage 2.
    await login(page, PRIMARY_COORDINATOR);
    await page.goto(`/staff/cycles/${summerId}/approvals`);
    await page.getByRole("checkbox", { name: `Select ${students.p7[1]}` }).check();
    await page.getByRole("button", { name: "Approve selected" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Will approve (1)")).toBeVisible();
    await expect(dialog.getByText(students.p7[1], { exact: true })).toBeVisible();
    await dialog.getByRole("button", { name: "Approve" }).click();
    await expect(dialog).toBeHidden();
    await page.getByRole("combobox", { name: "Membership status" }).selectOption("active");
    await expect(page.getByText("11 active members in this cycle.")).toBeVisible();
    await logout(page);
  });

  test("D.19-D.21 the nested rule, its reasons, and the two broader jobs", async ({ page }) => {
    page.setDefaultTimeout(8_000);
    await login(page, PRIMARY_COORDINATOR);
    const summerId = await staffCycleId(page, SUMMER_CYCLE);
    const { programs, branches } = await taxonomyIds(page);

    // D.19: job 1 carries Stage 2's nested rule. "Dual Major" is not a program
    // in this model — it is a flag on the profile (observation O.1) — so the
    // program clause is BTech, which is what P4 is enrolled in.
    const jobOneId = await createJob(page, summerId, {
      title: SUMMER_JOB_ONE,
      company: "Solstice Robotics",
      description: "Firmware and board bring-up for the summer robotics programme.",
      deadline: "2027-06-30T17:00",
    });
    // Built through the clause and group controls, which is Step 19's own
    // question. Until the group controls existed this step wrote the tree as
    // JSON because that was the only path the implementation offered (O.5).
    await buildNestedRule(page, summerId, jobOneId, {
      // The seeded taxonomy names these "CSE" and "EE" — which is what
      // `branches.CSE` was indexing when this step wrote the tree as JSON.
      //
      // The builder compiles a typed number, so "8.0" is stored as 8 and the
      // stored summary and P4's refusal both read "CPI at least 8". O.5 noted
      // this the other way round, from a JSON author's seat: writing "8.0" as
      // a *string* keeps the trailing zero. It is the same threshold either
      // way, and a numeric field in a stored rule is worth more than a
      // trailing zero — the jobs in D.39 that still write JSON keep theirs.
      program: "BTech",
      branchA: "CSE",
      cpiA: "8.0",
      branchB: "EE",
      cpiB: "7.5",
    });

    // The impact panel is the server's own evaluation of the unsaved rule
    // against the eleven members: P1 (CSE 8.60), P2 (CSE 8.20), P6 (CSE 9.10),
    // P3 (EE 7.95) and P8 (EE 7.94) clear it; P4's CSE 7.80 does not, P7 is
    // MTech, P5 carries a backlog, and P9/P10/P11 are in other branches.
    const impact = page.getByRole("heading", { name: "Who qualifies" }).locator("xpath=../..");
    await expect(impact.getByText("Unsaved rule")).toBeVisible();
    await expect(impact.getByText("of 11 active members qualify")).toBeVisible();
    await expect(impact.getByText("5", { exact: true })).toBeVisible();
    await expect(
      impact.getByText(
        "Eligible when program one of BTech and ((primary branch one of CSE and CPI at least 8) or (primary branch one of EE and CPI at least 7.5)) and active backlogs at most 0.",
      ),
    ).toBeVisible();
    for (const key of ["p1", "p2", "p3", "p6", "p8"] as const) {
      const row = impact.getByText(students[key][1], { exact: true }).locator("xpath=ancestor::li[1]");
      await expect(row.getByText("Qualifies")).toBeVisible();
    }

    await page.getByRole("button", { name: "Save rule" }).click();
    let dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Save rule" }).click();
    await expect(dialog).toBeHidden();
    // Saved, the same sentence is what the job now says it requires — the one
    // string ELG-2 stores and JOB-4 reads back to a student.
    await expect(
      page
        .getByText("What students will read")
        .locator("..")
        .getByText(/^Eligible when program one of BTech and \(\(primary branch one of CSE/),
    ).toBeVisible();
    await addRounds(page, summerId, jobOneId, ROUNDS);
    await publishJob(page, summerId, jobOneId);
    await logout(page);

    // D.20: P4 reads the reasons himself. The `any` is reported as the choice
    // it is, with his own CPI in it, and nothing claims his branch is wrong on
    // its own (the design review §4.19).
    await login(page, students.p4[0]);
    await page.goto("/cycles");
    await page.getByRole("link", { name: SUMMER_CYCLE, exact: true }).click();
    const blocked = jobCard(page, SUMMER_JOB_ONE);
    const reasons = blocked.getByText("Why you cannot apply").locator("..");
    await expect(reasons.getByRole("listitem")).toHaveCount(1);
    await expect(
      reasons.getByText(
        "Must satisfy one of: CPI at least 8 (yours is 7.8); or primary branch one of EE (yours is CSE).",
      ),
    ).toBeVisible();
    // Grouped, not flattened: no standalone claim about his primary branch.
    await expect(reasons.getByText(/^Requires primary branch/)).toHaveCount(0);
    await logout(page);

    // D.21: job 2 admits a second major. P4's secondary branch is EE, so the
    // same student the first rule refused clears this one.
    await login(page, PRIMARY_COORDINATOR);
    const jobTwoId = await createJob(page, summerId, {
      title: SUMMER_JOB_TWO,
      company: "Solstice Robotics",
      description: "Motion control for the summer robotics programme; second majors welcome.",
      deadline: "2027-06-30T17:00",
    });
    await writeRule(page, summerId, jobTwoId, {
      all: [
        { field: "program_id", op: "in", value: [programs.BTech] },
        {
          any: [
            { field: "primary_branch_id", op: "in", value: [branches.EE] },
            { field: "secondary_branch_id", op: "in", value: [branches.EE] },
          ],
        },
        { field: "cpi", op: "gte", value: "7.5" },
        { field: "active_backlogs", op: "lte", value: 0 },
      ],
    });
    const impactTwo = page.getByRole("heading", { name: "Who qualifies" }).locator("xpath=../..");
    await expect(impactTwo.getByText("of 11 active members qualify")).toBeVisible();
    await expect(impactTwo.getByText("3", { exact: true })).toBeVisible();
    const p4Row = impactTwo
      .getByText(students.p4[1], { exact: true })
      .locator("xpath=ancestor::li[1]");
    await expect(p4Row.getByText("Qualifies")).toBeVisible();
    await page.getByRole("button", { name: "Save rule" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Save rule" }).click();
    await expect(dialog).toBeHidden();
    await addRounds(page, summerId, jobTwoId, ROUNDS);
    await publishJob(page, summerId, jobTwoId);
    await logout(page);

    // Job 3 is the script correction ruled for Steps 27–28: an ordinary
    // lower-threshold route for the students neither earlier rule admits.
    // It deliberately names no program, branch, or backlog restriction.
    await login(page, PRIMARY_COORDINATOR);
    const jobThreeId = await createJob(page, summerId, {
      title: SUMMER_JOB_THREE,
      company: "BluePeak Analytics",
      description: "Cross-disciplinary operations work for the summer engineering programme.",
      deadline: "2027-06-30T17:00",
    });
    await writeRule(page, summerId, jobThreeId, {
      all: [{ field: "cpi", op: "gte", value: "7.0" }],
    });
    const impactThree = page.getByRole("heading", { name: "Who qualifies" }).locator("xpath=../..");
    await expect(impactThree.getByText("of 11 active members qualify")).toBeVisible();
    await expect(impactThree.getByText("11", { exact: true })).toBeVisible();
    for (const key of ["p5", "p9", "p10"] as const) {
      const row = impactThree
        .getByText(students[key][1], { exact: true })
        .locator("xpath=ancestor::li[1]");
      await expect(row.getByText("Qualifies")).toBeVisible();
    }
    await page.getByRole("button", { name: "Save rule" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Save rule" }).click();
    await expect(dialog).toBeHidden();
    await addRounds(page, summerId, jobThreeId, ROUNDS);
    await publishJob(page, summerId, jobThreeId);
    await logout(page);

    // P4 sees both broader jobs as ones he can apply to.
    await login(page, students.p4[0]);
    await page.goto("/cycles");
    await page.getByRole("link", { name: SUMMER_CYCLE, exact: true }).click();
    for (const title of [SUMMER_JOB_TWO, SUMMER_JOB_THREE]) {
      await expect(jobCard(page, title).getByText("Why you cannot apply")).toHaveCount(0);
    }
    await logout(page);
  });

  test("D.22 every question type, a required answer withheld, and a link that is not one", async ({ page }) => {
    page.setDefaultTimeout(8_000);
    await login(page, PRIMARY_COORDINATOR);
    const summerId = await staffCycleId(page, SUMMER_CYCLE);
    const jobOneId = await staffJobId(page, summerId, SUMMER_JOB_ONE);
    const jobThreeId = await staffJobId(page, summerId, SUMMER_JOB_THREE);
    await addQuestions(page, summerId, jobOneId);
    await expect(page.getByRole("tab", { name: /^Questions/ })).toContainText("9");
    await logout(page);

    // P1 answers every one of the nine, which is the pass that proves each
    // type round-trips through the form the coordinator just built.
    await login(page, students.p1[0]);
    await page.goto(`/jobs/${jobOneId}`);
    const form = page.locator("#application-form form");

    // Required-field validation: the two starred answers hold the submission
    // until they are given, and the form says which they are.
    await expect(form.getByRole("button", { name: "Apply", exact: true })).toBeDisabled();
    await form
      .getByRole("textbox", { name: "Why this internship?" })
      .fill("Robotics is the reason I came here.");
    await expect(form.getByRole("button", { name: "Apply", exact: true })).toBeDisabled();

    // URL answers are shape-checked: a link that is not a link never leaves
    // the browser, and the server refuses the same value if one ever does
    // (`Answer with an https link.`).
    const link = form.getByRole("textbox", { name: "Portfolio link" });
    await link.fill("not-a-link");
    expect(await link.evaluate((node: HTMLInputElement) => node.checkValidity())).toBe(false);
    await form.getByRole("button", { name: "Apply", exact: true }).click();
    await expect(form).toBeVisible();
    await link.fill("https://example.com/portfolio");
    expect(await link.evaluate((node: HTMLInputElement) => node.checkValidity())).toBe(true);
    await expect(form.getByRole("button", { name: "Apply", exact: true })).toBeEnabled();

    await form
      .getByRole("textbox", { name: "Describe something you built" })
      .fill("A line-following robot with a custom PID loop.");
    await form.getByRole("combobox", { name: "Preferred team" }).selectOption("Firmware");
    await form.getByRole("checkbox", { name: "C", exact: true }).check();
    await form.getByRole("checkbox", { name: "Python" }).check();
    await form.getByRole("combobox", { name: "Available for eight weeks?" }).selectOption("true");
    await form.getByRole("spinbutton", { name: "Years of embedded experience" }).fill("2");
    await form.getByLabel("Earliest start date").fill("2027-05-10");
    await form.getByRole("textbox", { name: "Email for scheduling" }).fill("scheduling@example.com");
    await form.getByRole("button", { name: "Apply", exact: true }).click();
    await expect(
      page.getByText("You already have an application for this job.", { exact: false }),
    ).toBeVisible();
    await logout(page);

    // Every other eligible member of job 1 applies with the two required
    // answers. P3 is deliberately left out: Step 24 has him arrive late.
    for (const key of ["p2", "p6", "p8"] as const) {
      await login(page, students[key][0]);
      await applyWithAnswers(page, jobOneId, SUMMER_JOB_ONE, false);
      await logout(page);
    }

    // Job 2, which admits P4's second major, takes his application.
    const jobTwoId = await staffJobIdAsStudent(page, students.p4[0], SUMMER_JOB_TWO);
    await login(page, students.p4[0]);
    await applyToJob(page, jobTwoId, SUMMER_JOB_TWO);
    await logout(page);

    // The corrected third job is the common round used in Steps 25–29. It
    // admits the lower half ordinarily, while also putting the attendance
    // matrix and its waitlisted control row in one round to finalize.
    for (const key of ["p1", "p2", "p4", "p5", "p6", "p8", "p9", "p10", "p11"] as const) {
      await login(page, students[key][0]);
      await applyToJob(page, jobThreeId, SUMMER_JOB_THREE);
      await logout(page);
    }
  });

  test("D.23-D.24 two overrides let a refused student and a late one through", async ({ page }) => {
    page.setDefaultTimeout(8_000);
    await login(page, PRIMARY_COORDINATOR);
    const summerId = await staffCycleId(page, SUMMER_CYCLE);
    const jobOneId = await staffJobId(page, summerId, SUMMER_JOB_ONE);
    await logout(page);

    // D.23: P11's branch is Mechanical, so both alternatives of the `any`
    // fail — and only on the branch, since his 8.05 clears either CPI floor.
    await login(page, students.p11[0]);
    await page.goto(`/jobs/${jobOneId}`);
    // The job page states each failing reason twice — once in the card's
    // refusal panel and once beside the requirement it belongs to — so this
    // asks whether it is there, not how many times.
    await expect(
      page
        .getByText(
          "Must satisfy one of: primary branch one of CSE (yours is Mechanical); or primary branch one of EE (yours is Mechanical).",
        )
        .first(),
    ).toBeVisible();
    await expect(page.locator("#application-form form")).toHaveCount(0);
    await logout(page);

    // The exception is granted on P11's own record and narrowed to job 1.
    // the design review §4.52 makes this pre-application student-plus-job target a
    // first-class scope rather than forcing an enrollment-wide substitute.
    await login(page, ADMIN);
    const p11Enrollment = await enrollmentId(page, students.p11[0]);
    await page.goto(`/staff/student/${p11Enrollment}`);
    await page.getByRole("button", { name: "Grant job override" }).click();
    let dialog = page.getByRole("dialog");
    await dialog.getByRole("combobox", { name: "Job *", exact: true }).selectOption(jobOneId);
    await dialog.getByRole("combobox", { name: "Rule domain *", exact: true }).selectOption("eligibility");
    await dialog
      .getByRole("combobox", { name: "Decision *", exact: true })
      .selectOption({ label: "Allow past this gate" });
    await dialog
      .getByRole("textbox", { name: "Reason *", exact: true })
      .fill("Company asked for him by name after the robotics showcase");
    await expect(dialog.getByText("What will happen")).toBeVisible();
    await dialog.getByRole("button", { name: "Grant" }).click();
    await expect(dialog).toBeHidden();
    await logout(page);

    // With the override standing, the same student applies to the same job.
    await login(page, students.p11[0]);
    await applyWithAnswers(page, jobOneId, SUMMER_JOB_ONE, false);
    await logout(page);

    // Step 23's last check: the override is stamped into P11's application
    // event, and the timeline says so in words. `apply` writes
    // `applied_override_ids` as INT-2 requires; the design review §4.35 (widened)
    // makes the screen resolve those ids and read the grant out, reason
    // included, rather than delivering a payload nothing renders.
    await login(page, ADMIN);
    await page.goto(`/staff/student/${p11Enrollment}`);
    await expect(
      page.getByText(
        /Eligibility requirement waived — override granted by CDS Administrator.*reason: Company asked for him by name after the robotics showcase/,
      ),
    ).toBeVisible();
    await logout(page);

    // D.24: the deadline passes. A live run waits for it; here the coordinator
    // moves it, which is the same command with the same effect.
    await login(page, PRIMARY_COORDINATOR);
    await page.goto(`/staff/jobs/${jobOneId}?cycle_id=${summerId}`);
    await page.getByLabel("Application deadline").fill("2026-01-05T17:00");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);
    await logout(page);

    // P3 arrives late and is told so.
    await login(page, students.p3[0]);
    await page.goto(`/jobs/${jobOneId}`);
    await expect(page.getByText("The application deadline has passed.").first()).toBeVisible();
    await expect(page.locator("#application-form form")).toHaveCount(0);
    await logout(page);

    await login(page, ADMIN);
    const p3Enrollment = await enrollmentId(page, students.p3[0]);
    await page.goto(`/staff/student/${p3Enrollment}`);
    await page.getByRole("button", { name: "Grant job override" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("combobox", { name: "Job *", exact: true }).selectOption(jobOneId);
    await dialog
      .getByRole("combobox", { name: "Rule domain *", exact: true })
      .selectOption("application_deadline");
    await dialog
      .getByRole("combobox", { name: "Decision *", exact: true })
      .selectOption({ label: "Allow past this gate" });
    await dialog
      .getByRole("textbox", { name: "Reason *", exact: true })
      .fill("Was in hospital the week the form closed");
    await dialog.getByRole("button", { name: "Grant" }).click();
    await expect(dialog).toBeHidden();
    await logout(page);

    await login(page, students.p3[0]);
    await applyWithAnswers(page, jobOneId, SUMMER_JOB_ONE, false);
    await logout(page);

    // Both grants are on the register, each with the reason it was given for.
    await login(page, ADMIN);
    await page.goto("/admin/overrides");
    await expect(page.getByRole("heading", { name: "Overrides", level: 1 })).toBeVisible();
    await expect(
      page.getByText("Company asked for him by name after the robotics showcase"),
    ).toBeVisible();
    await expect(page.getByText("Was in hospital the week the form closed")).toBeVisible();
    await logout(page);
  });


  test("D.25-D.26 rounds are scheduled before the pasted and individual results", async ({ page }) => {
    page.setDefaultTimeout(8_000);
    await login(page, PRIMARY_COORDINATOR);
    const summerId = await staffCycleId(page, SUMMER_CYCLE);
    const jobOneId = await staffJobId(page, summerId, SUMMER_JOB_ONE);
    await page.goto(`/staff/jobs/${jobOneId}/board`);
    await expect(page.getByRole("heading", { name: SUMMER_JOB_ONE })).toBeVisible();
    // Job 1's six applicants are already in round 1: `apply` puts them there,
    // which is why the rounds are built with the job (see `addRounds`).
    await expect(page.getByText("1. Online Assessment (6)")).toBeVisible();

    // D.25 schedules the round before D.26 runs it. The script now states
    // this operational ordering explicitly (observations O.7 and O.8).
    //
    // The sheet carries the three broken rows Step 25 asks for: a time nobody
    // can read, a row that asks for nothing at all, and — legitimately — a row
    // carrying only a venue, which must survive.
    const sheet = [
      "identifier,venue,time",
      `${ROLL.p1},AB 5 / 204,2027-07-01 09:30`,
      `${ROLL.p2},AB 5 / 204,half past nine`,
      `${ROLL.p3},,`,
      `${ROLL.p6},AB 5 / 204,`,
    ].join("\n");
    await uploadVenueSheet(page, "venues.csv", sheet);
    // Named one by one with the row they are on, never counted (the design review §4.5).
    const report = page.getByText("Could not read (2)").locator("..");
    await expect(report.getByText(/^Row 3 — 'half past nine' is not a time/)).toBeVisible();
    await expect(report.getByText("Row 4 — Give a venue, a time, or both")).toBeVisible();
    await expect(page.getByText("2 rows read from the file")).toBeVisible();

    let dialog = await publishSlots(page);
    await expect(dialog.getByText("Will publish (2)")).toBeVisible();
    await expect(dialog.getByText(students.p1[1], { exact: false })).toContainText("AB 5 / 204");
    // A venue with no time is the whole row, not half a rejected one.
    await expect(dialog.getByText(students.p6[1], { exact: false })).toContainText("AB 5 / 204");
    // Nobody has been told yet, so no row carries the repeat flag. Asserted per
    // row: the dialog's own description says the word "update" as well.
    for (const key of ["p1", "p6"] as const) {
      await expect(dialog.getByText(students[key][1], { exact: false })).not.toContainText("update");
    }
    await dialog.getByRole("button", { name: "Publish", exact: true }).click();
    await expect(dialog).toBeHidden();

    // The corrected sheet: the time P2's row could not state, and RND-4's
    // repeat flag on the two students already told.
    const corrected = [
      "identifier,venue,time",
      `${ROLL.p1},AB 5 / 204,2027-07-01 09:30`,
      `${ROLL.p2},AB 5 / 204,2027-07-01 10:00`,
      `${ROLL.p3},AB 5 / 204,2027-07-01 10:30`,
      `${ROLL.p6},AB 5 / 204,2027-07-01 11:00`,
    ].join("\n");
    await uploadVenueSheet(page, "venues-corrected.csv", corrected);
    await expect(page.getByText("4 rows read from the file")).toBeVisible();
    await expect(page.getByText(/Could not read/)).toHaveCount(0);
    dialog = await publishSlots(page);
    // Three of the four move something. P1's row is character-for-character
    // the row that already published, so it publishes nothing and mails
    // nobody (the design review §4.46): a corrected sheet must not re-mail the room.
    await expect(dialog.getByText("Will publish (3)")).toBeVisible();
    await expect(dialog.getByText("Already up to date (1)")).toBeVisible();
    await expect(dialog.getByText(students.p1[1], { exact: false })).toContainText(
      "will not be emailed again",
    );
    // P6 had a venue and no time; the time is new, and they have been told
    // once, so theirs is the row that carries RND-4's repeat flag.
    await expect(dialog.getByText(students.p6[1], { exact: false })).toContainText("update");
    await expect(dialog.getByText(students.p2[1], { exact: false })).not.toContainText("update");
    await dialog.getByRole("button", { name: "Publish", exact: true }).click();
    await expect(dialog).toBeHidden();
    // And the board itself now states the slot beside each name.
    await expect(page.getByText("01 Jul 2027", { exact: false }).first()).toBeVisible();

    // Give Step 30 a real attendance fact to preserve when P11 is returned to
    // this round; pending→pending would not demonstrate the invariant.
    await page.getByRole("button", { name: `Mark ${students.p11[1]} present` }).click();
    await expect(
      page.getByRole("button", { name: `Mark ${students.p11[1]} present` }),
    ).toHaveCount(0);

    // D.26: the four who cleared the assessment, pasted as the room pastes
    // them, with two numbers that are nobody. P6 stays behind for Step 29's
    // waitlist and P8 for the absence Step 27 records.
    await page.getByRole("button", { name: "Paste roll numbers or emails" }).click();
    await page
      .getByRole("textbox", { name: "Paste roll numbers or emails" })
      .fill([ROLL.p1, ROLL.p2, ROLL.p3, ROLL.p11, "25110999", "NOT-A-ROLL"].join("\n"));
    await page.getByRole("button", { name: "Add to selection" }).click();
    await page.getByRole("button", { name: "Advance", exact: true }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("What will happen")).toBeVisible();
    // Per-row effects, never an aggregate: every mover named with the round it
    // lands in (the design review §4.21, widened by §4.37).
    await expect(dialog.getByText("Will move (4)")).toBeVisible();
    for (const key of ["p1", "p2", "p3", "p11"] as const) {
      await expect(
        dialog.getByText(`${students[key][1]} (${ROLL[key]})`, { exact: false }),
      ).toContainText("→ Technical");
    }
    // And the two typos are named one by one.
    await expect(dialog.getByText("Matched nothing (2)")).toBeVisible();
    await expect(dialog.getByText("25110999", { exact: true })).toBeVisible();
    await expect(dialog.getByText("NOT-A-ROLL", { exact: true })).toBeVisible();
    await dialog.getByRole("button", { name: "Advance", exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText("2. Technical (4)")).toBeVisible();

    // Job 3 is the common attendance round introduced by the Steps 27–28
    // ruling. Schedule everyone before recording any result there.
    const jobThreeId = await staffJobId(page, summerId, SUMMER_JOB_THREE);
    await page.goto(`/staff/jobs/${jobThreeId}/board`);
    await expect(page.getByRole("heading", { name: SUMMER_JOB_THREE })).toBeVisible();
    await expect(page.getByText("1. Online Assessment (9)")).toBeVisible();
    const commonRound = [
      "identifier,venue,time",
      ...(["p1", "p2", "p4", "p5", "p6", "p8", "p9", "p10", "p11"] as const)
        .map((key, index) => `${ROLL[key]},AB 7 / 101,2027-07-02 ${String(9 + index).padStart(2, "0")}:00`),
    ].join("\n");
    await uploadVenueSheet(page, "job-3-round-1.csv", commonRound);
    await expect(page.getByText("9 rows read from the file")).toBeVisible();
    dialog = await publishSlots(page);
    await expect(dialog.getByText("Will publish (9)")).toBeVisible();
    await dialog.getByRole("button", { name: "Publish", exact: true }).click();
    await expect(dialog).toBeHidden();

    // P5's outcome-map result is an ordinary round-one elimination. P6 is the
    // waitlisted control row that finalization must name and skip in D.28.
    await page.getByRole("checkbox", { name: `Select ${students.p5[1]}` }).check();
    await page.getByRole("button", { name: "Eliminate", exact: true }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("textbox", { name: "Reason" }).fill("Did not clear the assessment");
    await expect(dialog.getByText("Will move (1)")).toBeVisible();
    await expect(dialog.getByText(students.p5[1], { exact: false })).toContainText("rejected");
    await dialog.getByRole("button", { name: "Eliminate", exact: true }).click();
    await expect(dialog).toBeHidden();

    await page.getByRole("checkbox", { name: `Select ${students.p6[1]}` }).check();
    await page.getByRole("button", { name: "Waitlist", exact: true }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Will move (1)")).toBeVisible();
    await dialog.getByRole("button", { name: "Waitlist", exact: true }).click();
    await expect(dialog).toBeHidden();
    const p6Row = page
      .getByText(students.p6[1], { exact: true })
      .locator("xpath=ancestor::li[1]");
    await expect(p6Row.getByText("Waitlisted", { exact: true })).toBeVisible();
    await logout(page);
  });

  test("D.27-D.28 attendance finalizes absent, pending, and excused side by side", async ({ page }) => {
    page.setDefaultTimeout(8_000);
    await login(page, PRIMARY_COORDINATOR);
    const summerId = await staffCycleId(page, SUMMER_CYCLE);
    const jobThreeId = await staffJobId(page, summerId, SUMMER_JOB_THREE);
    await page.goto(`/staff/jobs/${jobThreeId}/board`);
    await expect(page.getByRole("heading", { name: SUMMER_JOB_THREE })).toBeVisible();

    // D.27: every mark is made by name on the common round. P10 is
    // deliberately untouched so finalization itself changes pending→absent.
    for (const key of ["p1", "p2", "p4", "p11"] as const) {
      await page.getByRole("button", { name: `Mark ${students[key][1]} present` }).click();
      await expect(
        page.getByRole("button", { name: `Mark ${students[key][1]} present` }),
      ).toHaveCount(0);
    }
    await page.getByRole("button", { name: `Mark ${students.p8[1]} absent` }).click();
    await expect(
      page.getByRole("button", { name: `Mark ${students.p8[1]} absent` }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: `Mark ${students.p9[1]} excused` }).click();
    await expect(
      page.getByRole("button", { name: `Mark ${students.p9[1]} excused` }),
    ).toHaveCount(0);

    const p10Row = page
      .getByText(students.p10[1], { exact: true })
      .locator("xpath=ancestor::li[1]");
    await expect(p10Row.getByText("Pending", { exact: true }).first()).toBeVisible();
    await expect(
      page.getByRole("button", { name: `Mark ${students.p10[1]} not marked` }),
    ).toHaveCount(0);

    // D.28: the preview is the prediction exercise in the script. It names
    // each consequence, both strikes, every present row, and the waitlist it
    // refuses to resolve.
    await page.getByRole("button", { name: "Finalize round" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("3 finalized · 2 strikes · 0 penalties")).toBeVisible();
    await expect(dialog.getByText("Will finalize (3)")).toBeVisible();
    await expect(dialog.getByText("Will remain untouched (6)")).toBeVisible();

    const previewRow = (key: "p1" | "p2" | "p4" | "p5" | "p6" | "p8" | "p9" | "p10" | "p11") =>
      dialog.locator("li").filter({ hasText: students[key][1] });
    await expect(previewRow("p8")).toContainText("attendance absent → absent; Rejected (absence)");
    await expect(previewRow("p8")).toContainText("will earn a strike");
    await expect(previewRow("p10")).toContainText("attendance pending → absent; Rejected (absence)");
    await expect(previewRow("p10")).toContainText("will earn a strike");
    await expect(previewRow("p9")).toContainText("attendance excused → excused; Rejected (excused)");
    await expect(previewRow("p9")).not.toContainText("will earn a strike");
    for (const key of ["p1", "p2", "p4", "p11"] as const) {
      await expect(previewRow(key)).toContainText("attendance present → present; In progress (present)");
    }
    await expect(previewRow("p6")).toContainText("In progress (waitlisted)");
    await expect(previewRow("p5")).toContainText("Rejected (already decided)");

    await dialog.getByRole("button", { name: "Finalize round" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText(/Closed .* by Demo Coordinator 01/)).toBeVisible();
    for (const key of ["p8", "p9", "p10"] as const) {
      const row = page
        .getByText(students[key][1], { exact: true })
        .locator("xpath=ancestor::li[1]");
      await expect(row.getByText("Rejected", { exact: true })).toBeVisible();
    }
    await logout(page);

    // The preview promised two strikes; the admin discipline surface confirms
    // both authoritative rows exist after commit, while the excused student
    // has none.
    await login(page, ADMIN);
    for (const key of ["p8", "p10"] as const) {
      const id = await enrollmentId(page, students[key][0]);
      await page.goto(`/admin/discipline?enrollment_id=${id}`);
      await expect(page.getByRole("heading", { name: "Discipline" })).toBeVisible();
      await expect(page.getByText("Active strikes1", { exact: true })).toBeVisible();
      await expect(page.getByText(`Absent from Online Assessment (${SUMMER_JOB_THREE})`)).toBeVisible();
    }
    const p9Enrollment = await enrollmentId(page, students.p9[0]);
    await page.goto(`/admin/discipline?enrollment_id=${p9Enrollment}`);
    await expect(page.getByText("No strikes have been awarded.")).toBeVisible();
    await logout(page);
  });

  test("D.29 waitlist promotion keeps the application in progress", async ({ page }) => {
    page.setDefaultTimeout(8_000);
    await login(page, PRIMARY_COORDINATOR);
    const summerId = await staffCycleId(page, SUMMER_CYCLE);

    // D.29: finalizing the round did not resolve P6's waitlist. Promotion now
    // moves her to Technical while the application remains in progress.
    const jobThreeId = await staffJobId(page, summerId, SUMMER_JOB_THREE);
    await page.goto(`/staff/jobs/${jobThreeId}/board`);
    const p6 = page
      .getByText(students.p6[1], { exact: true })
      .locator("xpath=ancestor::li[1]");
    await expect(p6.getByText("Waitlisted", { exact: true })).toBeVisible();
    await expect(p6.getByText("In progress", { exact: true })).toBeVisible();
    await p6.getByRole("checkbox", { name: `Select ${students.p6[1]}` }).check();
    await page.getByRole("button", { name: "Promote", exact: true }).click();
    let dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Will move (1)")).toBeVisible();
    await expect(dialog.getByText(students.p6[1], { exact: false })).toContainText("→ Technical");
    await dialog.getByRole("button", { name: "Promote", exact: true }).click();
    await expect(dialog).toBeHidden();
    const technical = page
      .getByText("2. Technical (1)")
      .locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' bg-card ')][1]");
    await expect(technical.getByText(students.p6[1], { exact: true })).toBeVisible();
    await expect(technical.getByText("In progress", { exact: true })).toBeVisible();
    await logout(page);
  });

  test("D.30-D.31 reinstatement exposes its ledger repair before a direct offer", async ({ page }) => {
    page.setDefaultTimeout(8_000);
    await login(page, PRIMARY_COORDINATOR);
    const summerId = await staffCycleId(page, SUMMER_CYCLE);
    const jobOneId = await staffJobId(page, summerId, SUMMER_JOB_ONE);

    // P11 reached Technical in D.26. Rejecting him there leaves both round
    // ledger rows available for the reinstatement preview to distinguish.
    await page.goto(`/staff/jobs/${jobOneId}/board`);
    const p11 = page
      .getByText(students.p11[1], { exact: true })
      .locator("xpath=ancestor::li[1]");
    await p11.getByRole("checkbox", { name: `Select ${students.p11[1]}` }).check();
    await page.getByRole("button", { name: "Eliminate", exact: true }).click();
    let dialog = page.getByRole("dialog");
    await dialog.getByRole("textbox", { name: "Reason" }).fill("Mock run reinstatement exercise");
    await expect(dialog.getByText("Will move (1)")).toBeVisible();
    await dialog.getByRole("button", { name: "Eliminate", exact: true }).click();
    await expect(dialog).toBeHidden();
    await logout(page);

    // D.30: the dedicated renderer names each side of the ledger boundary and
    // gives the result and attendance carried by each row. A count alone would
    // not let the administrator verify which evidence is about to be deleted.
    await login(page, ADMIN);
    const p11Enrollment = await enrollmentId(page, students.p11[0]);
    await page.goto(`/staff/student/${p11Enrollment}`);
    const application = page
      .getByRole("heading", { name: SUMMER_JOB_ONE, exact: true })
      .locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' bg-card ')][1]");
    await application.getByRole("button", { name: "Reinstate" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("combobox", { name: "Return to round *", exact: true }).selectOption({ label: "1. Online Assessment" });
    await dialog.getByRole("textbox", { name: "Reason *", exact: true }).fill("Return to the first round after review");
    const clearedStates = dialog
      .getByText("Round states cleared", { exact: true })
      .locator("xpath=ancestor::section[1]");
    await expect(clearedStates).toContainText("Round states cleared (1)");
    await expect(clearedStates.getByRole("listitem")).toContainText(
      "Technical · result: eliminated · attendance: pending",
    );
    const keptStates = dialog
      .getByText("Round states kept", { exact: true })
      .locator("xpath=ancestor::section[1]");
    await expect(keptStates).toContainText("Round states kept (0)");
    await expect(keptStates.getByText("No earlier round states are present.")).toBeVisible();
    await dialog.getByRole("button", { name: "Reinstate", exact: true }).click();
    await expect(dialog).toBeHidden();

    // The kept row still carries its pending attendance after commit, and the
    // timeline records both the rejection and the explicit repair reason.
    const restoredRound = application
      .getByText("1. Online Assessment", { exact: true })
      .locator("xpath=ancestor::li[1]");
    await expect(restoredRound.getByText("Pending", { exact: true })).toBeVisible();
    await expect(restoredRound.getByText("Present", { exact: true })).toBeVisible();
    await expect(application.getByText("Technical", { exact: true })).toHaveCount(0);
    await expect(application.getByText("Mock run reinstatement exercise", { exact: true })).toBeVisible();
    await expect(application.getByText("Return to the first round after review", { exact: true })).toBeVisible();
    await logout(page);

    // D.31 deliberately skips the remaining round. Staff may extend an offer
    // to an in-progress application, and accepting it names the other summer
    // application that the OFR-3 cascade will auto-withdraw.
    await login(page, PRIMARY_COORDINATOR);
    await page.goto(`/staff/jobs/${jobOneId}/offers`);
    const offerRow = page
      .getByText(students.p11[0], { exact: false })
      .locator("xpath=ancestor::li[1]");
    await offerRow.getByRole("checkbox", { name: `Select ${students.p11[1]}` }).check();
    await page.getByRole("button", { name: "Extend / rollout" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Will be offered (1)")).toBeVisible();
    await dialog.getByRole("button", { name: "Extend offers" }).click();
    await expect(dialog).toBeHidden();
    await logout(page);

    await login(page, students.p11[0]);
    await page.goto("/dashboard");
    await page.getByRole("button", { name: "Accept", exact: true }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Other applications affected (1)")).toBeVisible();
    await expect(
      dialog
        .getByText(SUMMER_JOB_THREE, { exact: true })
        .locator("xpath=ancestor::li[1]"),
    ).toContainText("in progress → auto withdrawn");
    await dialog.getByRole("button", { name: "Accept offer" }).click();
    await expect(dialog).toBeHidden();
    await page.reload();
    const acceptedApplication = page
      .locator("li")
      .filter({ has: page.getByText(SUMMER_JOB_ONE, { exact: true }) })
      .filter({ hasText: "Accepted" });
    await expect(acceptedApplication).toBeVisible();
    await logout(page);
  });

  test("D.32 summer acceptances cascade within the cycle and leave the open cycle untouched", async ({ page }) => {
    // No limiter wait here: the design review §4.39 stopped charging dry runs, so the
    // roll-outs cost one request each. What is left is the worker's own clock.
    test.setTimeout(240_000);
    page.setDefaultTimeout(8_000);
    await login(page, PRIMARY_COORDINATOR);
    const summerId = await staffCycleId(page, SUMMER_CYCLE);
    const jobOneId = await staffJobId(page, summerId, SUMMER_JOB_ONE);
    const jobThreeId = await staffJobId(page, summerId, SUMMER_JOB_THREE);

    // D.32: direct offers are valid from an in-progress round. P1 and P2 take
    // job 1; P2 simultaneously holds job 3's offer so acceptance has an
    // offered application to auto-decline rather than merely auto-withdraw.
    await page.goto(`/staff/jobs/${jobOneId}/offers`);
    for (const key of ["p1", "p2"] as const) {
      await page.getByRole("checkbox", { name: `Select ${students[key][1]}` }).check();
    }
    await page.getByRole("button", { name: "Extend / rollout" }).click();
    let dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Will be offered (2)")).toBeVisible();
    for (const key of ["p1", "p2"] as const) {
      await expect(dialog.getByText(students[key][1], { exact: false })).toBeVisible();
    }
    await dialog.getByRole("button", { name: "Extend offers" }).click();
    await expect(dialog).toBeHidden();

    // P6 is offered here too — the end of the waitlist arc her card promises,
    // which no step used to reach (finding C.1). Her offer is on the job she
    // was waitlisted and then promoted in.
    await page.goto(`/staff/jobs/${jobThreeId}/offers`);
    for (const key of ["p2", "p6"] as const) {
      await page.getByRole("checkbox", { name: `Select ${students[key][1]}` }).check();
    }
    await page.getByRole("button", { name: "Extend / rollout" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Will be offered (2)")).toBeVisible();
    for (const key of ["p2", "p6"] as const) {
      await expect(dialog.getByText(students[key][1], { exact: false })).toBeVisible();
    }
    await dialog.getByRole("button", { name: "Extend offers" }).click();
    await expect(dialog).toBeHidden();
    await logout(page);

    // P1 accepts job 1. His other summer application is withdrawn, while the
    // accepted open-cycle internship remains outside the dedicated-cycle
    // cascade exactly as OFR-3 requires.
    await login(page, students.p1[0]);
    await page.goto("/dashboard");
    const p1Offer = page
      .getByRole("link", { name: SUMMER_JOB_ONE, exact: true })
      .locator("xpath=ancestor::li[1]");
    await p1Offer.getByRole("button", { name: "Accept", exact: true }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Other applications affected (1)")).toBeVisible();
    await expect(
      dialog.getByText(SUMMER_JOB_THREE, { exact: true }).locator("xpath=ancestor::li[1]"),
    ).toContainText("in progress → auto withdrawn");
    await dialog.getByRole("button", { name: "Accept offer" }).click();
    await expect(dialog).toBeHidden();
    const p1Summer = page
      .getByText(SUMMER_JOB_ONE, { exact: true })
      .locator("xpath=ancestor::li[1]");
    await expect(p1Summer.getByText("Accepted", { exact: true })).toBeVisible();
    const p1Open = page
      .getByText(OPEN_JOB_ONE, { exact: true })
      .locator("xpath=ancestor::li[1]");
    await expect(p1Open.getByText("Accepted", { exact: true })).toBeVisible();
    await logout(page);

    // P2 accepts one of two live summer offers. The sibling offer declines,
    // not withdraws, and his Stage 1 open-cycle application stays live.
    await login(page, students.p2[0]);
    await page.goto("/dashboard");
    const p2Offer = page
      .getByRole("link", { name: SUMMER_JOB_ONE, exact: true })
      .locator("xpath=ancestor::li[1]");
    await p2Offer.getByRole("button", { name: "Accept", exact: true }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Other applications affected (1)")).toBeVisible();
    await expect(
      dialog.getByText(SUMMER_JOB_THREE, { exact: true }).locator("xpath=ancestor::li[1]"),
    ).toContainText("offered → declined");
    await dialog.getByRole("button", { name: "Accept offer" }).click();
    await expect(dialog).toBeHidden();
    const p2OtherSummer = page
      .getByText(SUMMER_JOB_THREE, { exact: true })
      .locator("xpath=ancestor::li[1]");
    await expect(p2OtherSummer.getByText("Declined", { exact: true })).toBeVisible();

    // Keep this assertion as written in Step 32. Step 9 created both of P2's
    // open applications, and no intervening runsheet step records an
    // acceptance. Neither moves here: an internship accepted in a dedicated
    // cycle cascades only inside that cycle, so the placement-outcome one
    // survives too — it is Step 42 that takes it, and Step 58 the other.
    for (const title of [OPEN_JOB_ONE, OPEN_JOB_THREE]) {
      const p2Open = page.getByText(title, { exact: true }).locator("xpath=ancestor::li[1]");
      await expect(p2Open.getByText("In progress", { exact: true })).toBeVisible();
    }
    await logout(page);

    // P6 closes the waitlist arc: waitlisted at Step 26, promoted at Step 29,
    // offered and accepting here. Her other summer application — job 1, still
    // sitting in round 1 — is auto-withdrawn by the same in-cycle cascade.
    await login(page, students.p6[0]);
    await page.goto("/dashboard");
    const p6Offer = page
      .getByRole("link", { name: SUMMER_JOB_THREE, exact: true })
      .locator("xpath=ancestor::li[1]");
    await p6Offer.getByRole("button", { name: "Accept", exact: true }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Other applications affected (1)")).toBeVisible();
    await expect(
      dialog.getByText(SUMMER_JOB_ONE, { exact: true }).locator("xpath=ancestor::li[1]"),
    ).toContainText("in progress → auto withdrawn");
    await dialog.getByRole("button", { name: "Accept offer" }).click();
    await expect(dialog).toBeHidden();
    await expect(
      page.getByText(SUMMER_JOB_THREE, { exact: true }).locator("xpath=ancestor::li[1]"),
    ).toContainText("Accepted");
    await logout(page);

    // P4's offer exercises the worker rather than a student response. The live
    // room waits four minutes; the browser uses the next short clock boundary
    // so the same scheduled command can be observed inside the test timeout.
    await login(page, PRIMARY_COORDINATOR);
    const jobTwoId = await staffJobId(page, summerId, SUMMER_JOB_TWO);
    await page.goto(`/staff/jobs/${jobTwoId}?cycle_id=${summerId}`);
    const now = Date.now();
    await page
      .getByLabel("Application deadline")
      .fill(new Date(now - 60_000).toISOString().slice(0, 16));
    await page
      .getByLabel("Offer acceptance deadline")
      .fill(new Date(now + 90_000).toISOString().slice(0, 16));
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);

    await page.goto(`/staff/jobs/${jobOneId}/offers`);
    await page.getByRole("checkbox", { name: `Select ${students.p3[1]}` }).check();
    await page.getByRole("button", { name: "Extend / rollout" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Will be offered (1)")).toBeVisible();
    await dialog.getByRole("button", { name: "Extend offers" }).click();
    await expect(dialog).toBeHidden();

    await page.goto(`/staff/jobs/${jobTwoId}/offers`);
    await page.getByRole("checkbox", { name: `Select ${students.p4[1]}` }).check();
    await page.getByRole("button", { name: "Extend / rollout" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Will be offered (1)")).toBeVisible();
    await dialog.getByRole("button", { name: "Extend offers" }).click();
    await expect(dialog).toBeHidden();
    const p4OfferRow = page
      .getByText(students.p4[0], { exact: false })
      .locator("xpath=ancestor::li[1]");
    await expect(p4OfferRow.getByText("Deadline", { exact: false })).toBeVisible();
    await logout(page);

    // P3 responds ordinarily while P4 deliberately does nothing.
    await login(page, students.p3[0]);
    await page.goto("/dashboard");
    const p3Offer = page
      .getByRole("link", { name: SUMMER_JOB_ONE, exact: true })
      .locator("xpath=ancestor::li[1]");
    await p3Offer.getByRole("button", { name: "Accept", exact: true }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Accept offer" }).click();
    await expect(dialog).toBeHidden();
    await expect(
      page.getByText(SUMMER_JOB_ONE, { exact: true }).locator("xpath=ancestor::li[1]"),
    ).toContainText("Accepted");
    await logout(page);

    // The e2e worker claims the scheduled expiry and applies OFR-4 as the
    // system actor. Reloading is intentional: no websocket/polling contract
    // promises a pushed status change to an already-open dashboard.
    await login(page, students.p4[0]);
    await page.goto("/dashboard");
    await expect.poll(async () => {
      await page.reload();
      const statuses = page
        .getByRole("heading", { name: "Application status" })
        .locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' bg-card ')][1]");
      return statuses
        .getByText(SUMMER_JOB_TWO, { exact: true })
        .locator("xpath=ancestor::li[1]")
        .innerText();
    }, { timeout: 120_000 }).toContain("DECLINED");
    await expect(page.getByRole("link", { name: SUMMER_JOB_TWO, exact: true })).toHaveCount(0);
    await logout(page);

    // Step 32 also closes job 1's Round 1, which nothing else resolves
    // (finding C.2). P6's row there auto-withdrew when she accepted on job 3,
    // so P8 is the only one left in it.
    //
    // The order is the point. `decide_round_finalization` turns a pending
    // attendance into an absence and awards a strike for it, so finalizing
    // while P8's attendance was still blank would give him a second summer
    // strike -- the one D.45 exists to award -- and the penalty that creates
    // would then block his D.40 applications. He sat the assessment and did
    // not clear it, so that is what gets recorded, and finalization is left
    // with nothing to do.
    await login(page, PRIMARY_COORDINATOR);
    await page.goto(`/staff/jobs/${jobOneId}/board`);
    await expect(page.getByRole("heading", { name: SUMMER_JOB_ONE })).toBeVisible();
    // The column count is everyone who ever *reached* the round, so it does not
    // shrink when a row leaves. P8 still offering an attendance control is what
    // says he is the one live row left in it.
    await expect(
      page.getByRole("button", { name: `Mark ${students.p8[1]} present` }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: `Mark ${students.p6[1]} present` }),
    ).toHaveCount(0);

    await page.getByRole("button", { name: `Mark ${students.p8[1]} present` }).click();
    await expect(
      page.getByRole("button", { name: `Mark ${students.p8[1]} present` }),
    ).toHaveCount(0);

    await page.getByRole("checkbox", { name: `Select ${students.p8[1]}` }).check();
    await page.getByRole("button", { name: "Eliminate", exact: true }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("textbox", { name: "Reason" }).fill("Did not clear the assessment");
    await expect(dialog.getByText("Will move (1)")).toBeVisible();
    await expect(dialog.getByText(students.p8[1], { exact: false })).toContainText("rejected");
    await dialog.getByRole("button", { name: "Eliminate", exact: true }).click();
    await expect(dialog).toBeHidden();

    // Nobody is left to finalize, and the preview says so rather than
    // inventing a consequence. No strike is awarded here.
    await page.getByRole("button", { name: "Finalize round" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("0 finalized · 0 strikes · 0 penalties")).toBeVisible();
    await expect(dialog.getByText("Will finalize (0)")).toBeVisible();
    await dialog.getByRole("button", { name: "Finalize round" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText(/Closed .* by Demo Coordinator 01/)).toBeVisible();
    await logout(page);

    // P8 leaves the summer with exactly one strike, from job 3's absence.
    await login(page, ADMIN);
    const p8Enrollment = await enrollmentId(page, students.p8[0]);
    await page.goto(`/admin/discipline?enrollment_id=${p8Enrollment}`);
    await expect(page.getByText("Active strikes1", { exact: true })).toBeVisible();
    await logout(page);
  });

  // Steps 33 and 34 are human-only: reviewing the emails as a group, and
  // timing the coordinator's stage. No notifications surface exists and none
  // is planned (observation O.4), so neither has anything to automate.

  test("D.35-D.36 an unattached PPO places P1, and P7's external internship joins the summer cap", async ({ page }) => {
    page.setDefaultTimeout(8_000);

    // D.35: the PPO is recorded from P1's own summer application, which is
    // where the board offers it — only ever on an internship-outcome job. It
    // carries no cycle: `create_external_offer` has no such field, which is
    // exactly what leaves it in Step 38's pool.
    await login(page, ADMIN);
    const summerId = await staffCycleId(page, SUMMER_CYCLE);
    const jobOneId = await staffJobId(page, summerId, SUMMER_JOB_ONE);
    await page.goto(`/staff/jobs/${jobOneId}/board`);
    // The board carries a row per round an applicant has occupied, and P1 has
    // passed through two, so his name matches twice. Both rows describe the
    // same application; the dialog's own linked-application line below is what
    // proves which one the PPO attaches to.
    const p1Row = page
      .getByText(students.p1[1], { exact: true })
      .locator("xpath=ancestor::li[1]")
      .first();
    await p1Row.getByRole("button", { name: "Record PPO" }).click();
    let dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: `Record ${students.p1[1]}'s PPO` })).toBeVisible();
    // The dialog states what it is linking itself to, so the operator is not
    // trusting a preset they cannot see.
    await expect(dialog).toContainText(`${students.p1[1]} · Solstice Robotics · linked to this internship application`);

    // Outcome placement is the preset, and it is what makes this a PPO rather
    // than a second internship: the compensation field follows the outcome, so
    // a full-time CTC is the only one offered.
    await expect(dialog.getByRole("combobox", { name: "Outcome *", exact: true })).toHaveValue("placement");
    await expect(dialog.getByRole("combobox", { name: "Source *", exact: true })).toHaveValue("ppo");
    await expect(dialog.getByRole("spinbutton", { name: "Stipend per month (INR)" })).toHaveCount(0);
    await dialog.getByRole("spinbutton", { name: "CTC (LPA)" }).fill("24.5");
    await dialog.getByRole("combobox", { name: "Status *", exact: true }).selectOption("accepted");
    await dialog
      .getByRole("textbox", { name: "Reason / evidence *", exact: true })
      .fill("PPO letter from Solstice Robotics, countersigned");
    await expect(dialog.getByText("What will happen")).toBeVisible();
    await dialog.getByRole("button", { name: "Record offer" }).click();
    await expect(dialog).toBeHidden();

    // Unattached, and stated as such on the record — the pool Step 38 goes to.
    const p1Enrollment = await enrollmentId(page, students.p1[0]);
    await page.goto(`/staff/student/${p1Enrollment}`);
    const p1External = page
      .getByText("Solstice Robotics", { exact: true })
      .locator("xpath=ancestor::li[1]");
    await expect(p1External).toContainText("PPO · Placement · unattached");
    await expect(p1External.getByText("Accepted", { exact: true })).toBeVisible();

    // "Placement-placed immediately" is a derivation, not a stored flag, and
    // this is the only surface that reads it before the offer is attached to
    // any cycle: DER-1 counts an unattached accepted placement globally.
    // The cycle-scoped funnels cannot answer it: an unattached offer carries
    // no cycle, so every one of them filters it out. `portal_wide_placed` is
    // the one figure the page computes without a cycle filter, and it is
    // labelled as such — "regardless of attachment — the DER-1 dimensions".
    await page.goto("/admin/analytics");
    await expect(page.getByRole("heading", { name: "Portal analytics" })).toBeVisible();
    await expect(
      page.getByText(/1 student is placed,\s*1 of them externally/),
    ).toBeVisible();
    await logout(page);

    // P1 reads the same offer, read-only, with its full-time CTC.
    await login(page, students.p1[0]);
    await page.goto("/dashboard");
    const p1Dashboard = page
      .getByText("Solstice Robotics", { exact: true })
      .locator("xpath=ancestor::li[1]");
    await expect(p1Dashboard).toContainText("PPO · Placement");
    await expect(p1Dashboard).toContainText("24.50 LPA");
    await expect(p1Dashboard.getByRole("button")).toHaveCount(0);
    await logout(page);

    // D.36: P7's off-campus internship is recorded standalone and then
    // attached to the summer cycle. He was approved into it at Step 18, so
    // nothing is auto-created here — that is Step 38's to show.
    await login(page, ADMIN);
    await page.goto("/staff/external");
    await page.getByRole("button", { name: "Record external offer" }).click();
    dialog = page.getByRole("dialog");
    await dialog
      .getByRole("combobox", { name: "Student *", exact: true })
      .selectOption({ label: `${students.p7[1]} (${ROLL.p7})` });
    await dialog
      .getByRole("combobox", { name: "Company *", exact: true })
      .selectOption({ label: "Terra Nova Materials" });
    await dialog.getByRole("combobox", { name: "Outcome *", exact: true }).selectOption("internship");
    await dialog.getByRole("combobox", { name: "Source *", exact: true }).selectOption("off_campus");
    await dialog.getByRole("combobox", { name: "Status *", exact: true }).selectOption("accepted");
    await dialog.getByRole("spinbutton", { name: "Stipend per month (INR)" }).fill("55000");
    await dialog
      .getByRole("textbox", { name: "Reason / evidence *", exact: true })
      .fill("Verified off-campus summer internship offer");
    await dialog.getByRole("button", { name: "Record offer" }).click();
    await expect(dialog).toBeHidden();

    // The cycle's own external screen states the cap it is attaching against,
    // and the matching pool is where an unattached internship waits.
    await page.goto(`/staff/cycles/${summerId}/external`);
    await expect(page.getByText("Accepted-offer cap: 1")).toBeVisible();
    await page
      .getByRole("checkbox", { name: `Select ${students.p7[1]} at Terra Nova Materials` })
      .check();
    await page.getByRole("button", { name: "Attach selected" }).click();
    dialog = page.getByRole("dialog");
    await dialog
      .getByRole("textbox", { name: "Reason *", exact: true })
      .fill("Confirmed with the student and the company");
    await expect(dialog.getByText("Will be attached (1)")).toBeVisible();
    await expect(
      dialog.getByText(`${students.p7[1]} — Terra Nova Materials`, { exact: false }),
    ).toBeVisible();
    await dialog.getByRole("button", { name: "Attach selected" }).click();
    await expect(dialog).toBeHidden();

    // Attached, and now counting: P1's PPO is a placement and stays out of the
    // internship cycle's pool entirely, so what moved here is P7's alone.
    const attached = page
      .getByText("Attached (1)", { exact: false })
      .locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' bg-card ')][1]");
    await expect(attached.getByText(students.p7[1], { exact: false })).toBeVisible();
    await logout(page);

    // The cap is what "counts toward" means: P7 now has an accepted offer in
    // the summer cycle, so the cycle closes to him the way it closed to P1.
    await login(page, students.p7[0]);
    await page.goto("/dashboard");
    const p7External = page
      .getByText("Terra Nova Materials", { exact: true })
      .locator("xpath=ancestor::li[1]");
    await expect(p7External).toContainText("Off campus \u00b7 Internship");
    await expect(p7External).toContainText(SUMMER_CYCLE);
    await expect(p7External).toContainText("55000");
    await logout(page);
  });

  test("D.37-D.38 the placement cycle admits everyone but P1, whose PPO admits itself", async ({ page }) => {
    page.setDefaultTimeout(8_000);

    // D.37: the cycle the admin created up front, read rather than assumed —
    // `create_cycle` is admin-only because a cycle is global configuration,
    // which is the same reason coord2 does not create the winter one.
    await login(page, PRIMARY_COORDINATOR);
    const placementId = await staffCycleId(page, PLACEMENT_CYCLE);
    await page.goto(`/staff/cycles/${placementId}`);
    await expect(page.getByRole("heading", { name: PLACEMENT_CYCLE })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "Membership needs approval" })).toBeChecked();
    await expect(page.getByRole("spinbutton", { name: "Accepted-offer cap" })).toHaveValue("1");
    await logout(page);

    // Everyone but P1 joins. He stays out deliberately: Step 38's attachment
    // is what creates his membership, and a membership he already had would
    // make that invisible.
    const joining = (Object.keys(students) as (keyof typeof students)[]).filter(
      (key) => key !== "p1",
    );
    for (const key of joining) {
      await login(page, students[key][0]);
      await joinCycle(page, PLACEMENT_CYCLE, true);
      await logout(page);
    }

    await login(page, PRIMARY_COORDINATOR);
    await page.goto(`/staff/cycles/${placementId}/approvals`);
    await page.getByRole("button", { name: "Paste roll numbers or emails" }).click();
    await page
      .getByRole("textbox", { name: "Paste roll numbers or emails" })
      .fill(joining.map((key) => ROLL[key]).join("\n"));
    await page.getByRole("button", { name: "Add to selection" }).click();
    await page.getByRole("button", { name: "Approve selected" }).click();
    let dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Will approve (10)")).toBeVisible();
    await dialog.getByRole("button", { name: "Approve" }).click();
    await expect(dialog).toBeHidden();
    await page.getByRole("combobox", { name: "Membership status" }).selectOption("active");
    await expect(page.getByText("10 active members in this cycle.")).toBeVisible();

    // D.38: the pool. P1's PPO is the only thing in it — P7's external is an
    // internship and matches the summer cycle, not this one, which is what
    // "matching" means on this screen.
    await page.goto(`/staff/cycles/${placementId}/external`);
    await expect(page.getByText("Matching unattached pool (1)")).toBeVisible();
    await expect(page.getByText("Attached (0)")).toBeVisible();
    await page
      .getByRole("checkbox", { name: `Select ${students.p1[1]} at Solstice Robotics` })
      .check();
    await page.getByRole("button", { name: "Attach selected" }).click();
    dialog = page.getByRole("dialog");
    await dialog
      .getByRole("textbox", { name: "Reason *", exact: true })
      .fill("PPO confirmed for the placement season");
    await expect(dialog.getByText("Will be attached (1)")).toBeVisible();
    await expect(
      dialog.getByText(`${students.p1[1]} — Solstice Robotics`, { exact: false }),
    ).toBeVisible();
    await dialog.getByRole("button", { name: "Attach selected" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText("Attached (1)")).toBeVisible();
    await expect(page.getByText("Matching unattached pool (0)")).toBeVisible();

    // The membership the attachment created, and it says so: eleven members
    // now, where the approval queue only ever saw ten.
    await page.goto(`/staff/cycles/${placementId}/approvals`);
    await page.getByRole("combobox", { name: "Membership status" }).selectOption("active");
    await expect(page.getByText("11 active members in this cycle.")).toBeVisible();
    await logout(page);

    // The enrollment lookup is `admin/users`, which a coordinator is refused.
    await login(page, ADMIN);
    const p1Enrollment = await enrollmentId(page, students.p1[0]);
    await page.goto(`/staff/student/${p1Enrollment}`);
    const placementMembership = page
      .getByText(PLACEMENT_CYCLE, { exact: true })
      .locator("xpath=ancestor::li[1]");
    await expect(placementMembership).toContainText("created from an external attachment");
    await expect(placementMembership.getByText("Active", { exact: true })).toBeVisible();

    // And the offer now names the cycle whose cap it counts against.
    const p1External = page
      .getByText("Solstice Robotics", { exact: true })
      .locator("xpath=ancestor::li[1]");
    await expect(p1External).toContainText(`PPO · Placement · attached to ${PLACEMENT_CYCLE}`);
    await logout(page);
  });

  test("D.39-D.40 three placement jobs, one carrying the floor P8 fails, and the gate that closes P1 out", async ({ page }) => {
    test.setTimeout(240_000);
    page.setDefaultTimeout(8_000);
    await login(page, PRIMARY_COORDINATOR);
    const placementId = await staffCycleId(page, PLACEMENT_CYCLE);
    const { branches } = await taxonomyIds(page);

    // D.39: three jobs. A and C admit everyone; B carries the CPI floor that
    // Part A.4 built the cast around — P3's 7.95 clears it after half-up
    // rounding to one decimal and P8's 7.94 does not, which is the pair Step
    // 45 needs and the reason those two values are one hundredth apart.
    const jobs: Record<"a" | "b" | "c", string> = { a: "", b: "", c: "" };
    for (const [key, title, company, description] of [
      ["a", PLACEMENT_JOB_A, "Solstice Robotics", "Platform and systems work for the graduate intake."],
      ["b", PLACEMENT_JOB_B, "Ashbourne Capital", "Systematic research for the graduate intake."],
      ["c", PLACEMENT_JOB_C, "Vantage Point Consulting", "Operations and delivery for the graduate intake."],
    ] as const) {
      jobs[key] = await createJob(page, placementId, {
        title,
        company,
        description,
        deadline: "2028-01-31T17:00",
      });
      // A placement cycle fixes the outcome, so no job here states one —
      // that choice only appears in an open cycle (Step 7).
      await expect(page.getByRole("combobox", { name: "Outcome" })).toHaveCount(0);
      await addRounds(page, placementId, jobs[key], ROUNDS);
    }

    await writeRule(page, placementId, jobs.b, {
      all: [{ field: "cpi", op: "gte", value: "8.0" }],
    });
    const impact = page.getByRole("heading", { name: "Who qualifies" }).locator("xpath=../..");
    await expect(impact.getByText("of 11 active members qualify")).toBeVisible();
    // P1, P2, P3, P6, P7 and P11 clear 8.0; P4, P5, P8, P9 and P10 do not.
    await expect(impact.getByText("6", { exact: true })).toBeVisible();
    for (const key of ["p2", "p3", "p6", "p7", "p11"] as const) {
      const row = impact.getByText(students[key][1], { exact: true }).locator("xpath=ancestor::li[1]");
      await expect(row.getByText("Qualifies")).toBeVisible();
    }
    // The two that matter to Step 45 are named on the other side by hand: a
    // hundredth of a CPI decides which of them the rule admits.
    const p8Row = impact.getByText(students.p8[1], { exact: true }).locator("xpath=ancestor::li[1]");
    await expect(p8Row.getByText("Qualifies")).toHaveCount(0);
    await page.getByRole("button", { name: "Save rule" }).click();
    let dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Save rule" }).click();
    await expect(dialog).toBeHidden();

    for (const key of ["a", "b", "c"] as const) {
      await publishJob(page, placementId, jobs[key]);
    }
    // Nothing above named a branch; the taxonomy read is only here to prove
    // the rule was written against real ids rather than a literal.
    expect(Object.keys(branches).length).toBeGreaterThan(0);
    await logout(page);

    // Everyone but P1 applies, to every job their CPI admits. P4 and P8 are
    // deliberately short of one each: P4 needs a job left for Step 41's gate
    // to refuse, and P8 needs job B untouched for Step 45.
    for (const [key, applicants] of Object.entries(PLACEMENT_APPLICANTS) as [
      "a" | "b" | "c",
      readonly (keyof typeof students)[],
    ][]) {
      for (const who of applicants) {
        await login(page, students[who][0]);
        await applyToJob(page, jobs[key], { a: PLACEMENT_JOB_A, b: PLACEMENT_JOB_B, c: PLACEMENT_JOB_C }[key]);
        await logout(page);
      }
    }

    // P8 reads job B's refusal now, before any discipline exists, so Step 45
    // can show the same rule arriving *beside* a penalty rather than alone.
    await login(page, students.p8[0]);
    await page.goto("/cycles");
    await page.getByRole("link", { name: PLACEMENT_CYCLE, exact: true }).click();
    const p8Blocked = jobCard(page, PLACEMENT_JOB_B);
    await expect(
      p8Blocked.getByText("Why you cannot apply").locator("..").getByRole("listitem"),
    ).toHaveCount(1);
    // Standalone form, not the inline one D.20 read: a leaf that is a
    // requirement in its own right reads "Requires …; yours is …", where the
    // same leaf under an `any` is parenthesised into the choice it belongs to.
    await expect(p8Blocked.getByText(/^Requires CPI at least 8\.0; yours is 7\.9/)).toBeVisible();
    await logout(page);

    // D.40: P1 is placement-placed by an external offer he never applied for,
    // and the gate says so in those words. Job C carries no rule, so the
    // outcome gate is the only thing that can be refusing him.
    await login(page, students.p1[0]);
    await page.goto("/cycles");
    await page.getByRole("link", { name: PLACEMENT_CYCLE, exact: true }).click();
    const p1Blocked = jobCard(page, PLACEMENT_JOB_C);
    const p1Reasons = p1Blocked.getByText("Why you cannot apply").locator("..");
    // Two reasons, both true and both his own doing: the PPO placed him, and
    // attaching it to this cycle spent its single accepted-offer allowance.
    // Neither is a consequence of the other, so the card states both rather
    // than picking one and leaving him to discover the second later.
    await expect(p1Reasons.getByRole("listitem")).toHaveCount(2);
    await expect(
      p1Reasons.getByText(
        "You have already accepted a placement offer, so placement roles are closed to you.",
      ),
    ).toBeVisible();
    await expect(
      p1Reasons.getByText("You have accepted the maximum of 1 offer allowed in this cycle."),
    ).toBeVisible();
    await expect(p1Blocked.getByRole("button", { name: "Apply", exact: true })).toHaveCount(0);
    await logout(page);
  });

  test("D.41-D.42 an unattached off-campus placement gates P4, and P2's acceptance reaches the open cycle", async ({ page }) => {
    test.setTimeout(240_000);
    page.setDefaultTimeout(8_000);
    await login(page, ADMIN);
    const placementId = await staffCycleId(page, PLACEMENT_CYCLE);

    // D.41: recorded, and deliberately *not* attached — Step 36 and Step 38
    // say "attach" where they mean it, and this step does not. The difference
    // is legible in the refusal below: P1's attached PPO also spent his
    // cycle's cap, while P4 meets the outcome gate on its own.
    await page.goto("/staff/external");
    await page.getByRole("button", { name: "Record external offer" }).click();
    let dialog = page.getByRole("dialog");
    await dialog
      .getByRole("combobox", { name: "Student *", exact: true })
      .selectOption({ label: `${students.p4[1]} (${ROLL.p4})` });
    // Not Ferrous Dynamics, which the seed deactivates: CMP keeps a
    // deactivated company attached to everything it ever touched and hides it
    // from pickers, so it is correctly absent from this one.
    await expect(
      dialog.getByRole("combobox", { name: "Company *", exact: true }).getByText("Ferrous Dynamics"),
    ).toHaveCount(0);
    await dialog
      .getByRole("combobox", { name: "Company *", exact: true })
      .selectOption({ label: "Terra Nova Materials" });
    await dialog.getByRole("combobox", { name: "Outcome *", exact: true }).selectOption("placement");
    await dialog.getByRole("combobox", { name: "Source *", exact: true }).selectOption("off_campus");
    await dialog.getByRole("combobox", { name: "Status *", exact: true }).selectOption("accepted");
    await dialog.getByRole("spinbutton", { name: "CTC (LPA)" }).fill("18.75");
    await dialog
      .getByRole("textbox", { name: "Reason / evidence *", exact: true })
      .fill("Off-campus placement letter verified with the company");
    await dialog.getByRole("button", { name: "Record offer" }).click();
    await expect(dialog).toBeHidden();
    await logout(page);

    // The gate alone, where P1 read the gate and the cap together.
    await login(page, students.p4[0]);
    await page.goto("/cycles");
    await page.getByRole("link", { name: PLACEMENT_CYCLE, exact: true }).click();
    const p4Blocked = jobCard(page, PLACEMENT_JOB_C);
    const p4Reasons = p4Blocked.getByText("Why you cannot apply").locator("..");
    await expect(p4Reasons.getByRole("listitem")).toHaveCount(1);
    await expect(
      p4Reasons.getByText(
        "You have already accepted a placement offer, so placement roles are closed to you.",
      ),
    ).toBeVisible();

    // Read-only on his dashboard, with its own CTC and no cycle beside it.
    await page.goto("/dashboard");
    const p4External = page
      .getByText("Terra Nova Materials", { exact: true })
      .locator("xpath=ancestor::li[1]");
    await expect(p4External).toContainText("Off campus \u00b7 Placement");
    await expect(p4External).toContainText("18.75 LPA");
    await expect(p4External).not.toContainText(PLACEMENT_CYCLE);
    await expect(p4External.getByRole("button")).toHaveCount(0);
    await logout(page);

    // D.42: the rounds, then the roll-out the corrected Step 42 names.
    await login(page, PRIMARY_COORDINATOR);
    const jobA = await staffJobId(page, placementId, PLACEMENT_JOB_A);
    const jobB = await staffJobId(page, placementId, PLACEMENT_JOB_B);
    const jobC = await staffJobId(page, placementId, PLACEMENT_JOB_C);

    await advanceOnBoard(page, jobA, ["p2", "p3", "p6"]);
    await advanceOnBoard(page, jobB, ["p3", "p7"]);
    await extendOffers(page, jobA, ["p2", "p3", "p6"]);
    await extendOffers(page, jobB, ["p3", "p7"]);
    // P10's offer is the one Step 49 finds unanswered when it cancels job C.
    await extendOffers(page, jobC, ["p10"]);
    await logout(page);

    // P2 accepts job A holding two other placement applications and the
    // open-cycle placement job from Step 9. OFR-3 filters on outcome, not on
    // cycle, so the open-cycle one goes with the rest — and his open-cycle
    // *internship* stays exactly where it is.
    await login(page, students.p2[0]);
    await page.goto("/dashboard");
    const p2Offer = page
      .getByRole("link", { name: PLACEMENT_JOB_A, exact: true })
      .locator("xpath=ancestor::li[1]");
    await p2Offer.getByRole("button", { name: "Accept", exact: true }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Other applications affected (3)")).toBeVisible();
    for (const title of [PLACEMENT_JOB_B, PLACEMENT_JOB_C, OPEN_JOB_THREE]) {
      await expect(
        dialog.getByText(title, { exact: true }).locator("xpath=ancestor::li[1]"),
      ).toContainText("in progress → auto withdrawn");
    }
    // Named, not counted: the open-cycle row states its own cycle, which is
    // the only thing distinguishing it from the two in this one.
    await expect(
      dialog.getByText(OPEN_JOB_THREE, { exact: true }).locator("xpath=ancestor::li[1]"),
    ).toContainText(OPEN_CYCLE);
    await dialog.getByRole("button", { name: "Accept offer" }).click();
    await expect(dialog).toBeHidden();

    await page.reload();
    const statuses = page
      .getByRole("heading", { name: "Application status" })
      .locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' bg-card ')][1]");
    const status = (title: string) =>
      statuses.getByText(title, { exact: true }).locator("xpath=ancestor::li[1]");
    await expect(status(PLACEMENT_JOB_A)).toContainText("Accepted");
    await expect(status(OPEN_JOB_THREE)).toContainText("Auto-withdrawn");
    // Untouched, and this is the whole point of the step: the internship half
    // of his record is not the placement cascade's business, in any cycle.
    await expect(status(OPEN_JOB_ONE)).toContainText("In progress");
    await expect(status(SUMMER_JOB_ONE)).toContainText("Accepted");
    await logout(page);
  });

  test("D.43 the termination restores one application, leaves another, and unplaces P3", async ({ page }) => {
    test.setTimeout(240_000);
    page.setDefaultTimeout(8_000);

    // P3 accepts job A first. He is holding job B's offer and job C's live
    // application, so his acceptance produces one auto-decline and one
    // auto-withdrawal — the two different kinds of damage the termination
    // then has to offer to undo.
    await login(page, students.p3[0]);
    await page.goto("/dashboard");
    const p3Offer = page
      .getByRole("link", { name: PLACEMENT_JOB_A, exact: true })
      .locator("xpath=ancestor::li[1]");
    await p3Offer.getByRole("button", { name: "Accept", exact: true }).click();
    let dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Other applications affected (2)")).toBeVisible();
    await expect(
      dialog.getByText(PLACEMENT_JOB_B, { exact: true }).locator("xpath=ancestor::li[1]"),
    ).toContainText("offered → declined");
    await expect(
      dialog.getByText(PLACEMENT_JOB_C, { exact: true }).locator("xpath=ancestor::li[1]"),
    ).toContainText("in progress → auto withdrawn");
    await dialog.getByRole("button", { name: "Accept offer" }).click();
    await expect(dialog).toBeHidden();
    await logout(page);

    // D.43: the company revokes. The dialog has to read to a non-technical
    // person as two different things — what happens regardless, and what the
    // coordinator is choosing — so both halves are asserted as such.
    await login(page, PRIMARY_COORDINATOR);
    const placementId = await staffCycleId(page, PLACEMENT_CYCLE);
    const jobA = await staffJobId(page, placementId, PLACEMENT_JOB_A);
    await page.goto(`/staff/jobs/${jobA}/offers`);
    const p3Row = page
      .getByText(students.p3[0], { exact: false })
      .locator("xpath=ancestor::li[1]");
    await p3Row.getByRole("button", { name: "Terminate" }).click();
    dialog = page.getByRole("dialog");
    await dialog
      .getByRole("combobox", { name: "Kind *", exact: true })
      .selectOption("company_revoked");
    await dialog
      .getByRole("textbox", { name: "Reason *", exact: true })
      .fill("Company revoked the offer before joining");

    // Both candidates are offered, and each says what restoring it would
    // mean: the withdrawn one goes back to the round it left, the declined
    // one needs a new offer row because the old one is answered and stays so.
    await expect(
      dialog.getByRole("checkbox", { name: `Restore ${PLACEMENT_JOB_B}` }),
    ).toBeVisible();
    await expect(
      dialog.getByRole("checkbox", { name: `Restore ${PLACEMENT_JOB_C}` }),
    ).toBeVisible();
    await dialog.getByRole("checkbox", { name: `Restore ${PLACEMENT_JOB_B}` }).check();

    const decisions = dialog
      .getByText("Restoration decisions", { exact: true })
      .locator("xpath=ancestor::section[1]");
    await expect(
      decisions
        .getByText(`Restore ${PLACEMENT_JOB_B}`, { exact: false })
        .locator("xpath=ancestor::li[1]"),
    ).toContainText("fresh offer");
    await expect(decisions.getByText(`Leave ${PLACEMENT_JOB_C}`, { exact: false })).toBeVisible();
    const willRestore = dialog
      .getByText("Will restore", { exact: true })
      .locator("xpath=ancestor::section[1]");
    await expect(willRestore.getByRole("listitem")).toHaveCount(1);
    await expect(willRestore.getByText(PLACEMENT_JOB_B, { exact: false })).toBeVisible();
    const automatic = dialog
      .getByText("Automatic effects", { exact: true })
      .locator("xpath=ancestor::section[1]");
    await expect(automatic.getByRole("listitem").first()).toBeVisible();

    await dialog.getByRole("button", { name: "Terminate offer" }).click();
    await expect(dialog).toBeHidden();
    await logout(page);

    // P3 reads the result. Job B is live again on a fresh offer he can still
    // answer; job C is exactly where the acceptance left it; and the original
    // job-A acceptance is terminated rather than erased.
    await login(page, students.p3[0]);
    await page.goto("/dashboard");
    const p3Statuses = page
      .getByRole("heading", { name: "Application status" })
      .locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' bg-card ')][1]");
    const p3Status = (title: string) =>
      p3Statuses.getByText(title, { exact: true }).locator("xpath=ancestor::li[1]");
    await expect(p3Status(PLACEMENT_JOB_B)).toContainText("Offered");
    // Untouched means untouched: the candidate nobody selected did not move.
    await expect(p3Status(PLACEMENT_JOB_C)).toContainText("Auto-withdrawn");

    // The cap is released, which is the fact that makes him unplaced rather
    // than merely offerless: job C's card offers no route back, but the
    // placement cycle is open to him again on the strength of the derivation.
    await page.goto("/cycles");
    await page.getByRole("link", { name: PLACEMENT_CYCLE, exact: true }).click();
    const p3Card = jobCard(page, PLACEMENT_JOB_A);
    await expect(p3Card.getByText("Why you cannot apply")).toHaveCount(0);
    await logout(page);

    // And the history keeps both offers on job B: the declined one the
    // acceptance produced, and the fresh one the restoration created.
    await login(page, ADMIN);
    const p3Enrollment = await enrollmentId(page, students.p3[0]);
    await page.goto(`/staff/student/${p3Enrollment}`);
    const jobBApplication = page
      .getByRole("heading", { name: PLACEMENT_JOB_B, exact: true })
      .locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' bg-card ')][1]");
    await expect(jobBApplication.getByText("auto declined", { exact: false })).toBeVisible();
    await expect(jobBApplication.getByText("offer extended", { exact: false })).toHaveCount(2);
    await logout(page);
  });

  test("D.44-D.46 a renege with a strike, a penalty appealed away, and the boring happy path", async ({ page }) => {
    test.setTimeout(240_000);
    page.setDefaultTimeout(8_000);

    // D.44: P6 accepts job A, then changes her mind.
    await login(page, students.p6[0]);
    await page.goto("/dashboard");
    await page
      .getByRole("link", { name: PLACEMENT_JOB_A, exact: true })
      .locator("xpath=ancestor::li[1]")
      .getByRole("button", { name: "Accept", exact: true })
      .click();
    let dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Accept offer" }).click();
    await expect(dialog).toBeHidden();
    await logout(page);

    // The strike is the coordinator's judgement, made after hearing her, which
    // is why it is a choice on the dialog and not a consequence of the kind.
    await login(page, PRIMARY_COORDINATOR);
    const placementId = await staffCycleId(page, PLACEMENT_CYCLE);
    const jobA = await staffJobId(page, placementId, PLACEMENT_JOB_A);
    const jobB = await staffJobId(page, placementId, PLACEMENT_JOB_B);
    const jobC = await staffJobId(page, placementId, PLACEMENT_JOB_C);
    await page.goto(`/staff/jobs/${jobA}/offers`);
    await page
      .getByText(students.p6[0], { exact: false })
      .locator("xpath=ancestor::li[1]")
      .getByRole("button", { name: "Terminate" })
      .click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("combobox", { name: "Kind *", exact: true }).selectOption("student_renege");
    await dialog
      .getByRole("textbox", { name: "Reason *", exact: true })
      .fill("Withdrew to take up a postgraduate place");
    await dialog.getByRole("combobox", { name: "Discipline (optional)" }).selectOption("strike");
    await dialog.getByRole("button", { name: "Terminate offer" }).click();
    await expect(dialog).toBeHidden();

    await logout(page);

    // Tagged on the membership row, because ANA-3's seeking-adjusted rate
    // divides by exactly this difference: she is not an unplaced student, she
    // is one who stopped looking.
    await login(page, ADMIN);
    const p6Enrollment = await enrollmentId(page, students.p6[0]);
    await page.goto(`/staff/student/${p6Enrollment}`);
    const p6Membership = page
      .getByText(PLACEMENT_CYCLE, { exact: true })
      .locator("xpath=ancestor::li[1]");
    await p6Membership.getByRole("button", { name: "Not tagged" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("combobox", { name: "Outcome" }).selectOption("higher_studies");
    await dialog.getByRole("button", { name: "Save tag" }).click();
    await expect(dialog).toBeHidden();
    await expect(p6Membership.getByRole("button", { name: "Higher studies" })).toBeVisible();
    await logout(page);

    // D.45: the second strike is the admin's — a coordinator is refused, which
    // Stage 6 tests directly. Two strikes complete the global threshold and
    // convert on their own.
    await login(page, ADMIN);
    const p8Enrollment = await enrollmentId(page, students.p8[0]);
    await page.goto(`/admin/discipline?enrollment_id=${p8Enrollment}`);
    await expect(page.getByText("Active strikes1", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Award strike" }).click();
    dialog = page.getByRole("dialog");
    await dialog
      .getByRole("textbox", { name: "Reason *", exact: true })
      .fill("Missed the pre-placement talk without notice");
    await dialog.getByRole("button", { name: "Award strike" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText("Active penalties1", { exact: true })).toBeVisible();
    await logout(page);

    // Both reasons, side by side: the penalty he has just earned, and the CPI
    // floor he was already short of. Neither hides the other.
    await login(page, students.p8[0]);
    await page.goto("/cycles");
    await page.getByRole("link", { name: PLACEMENT_CYCLE, exact: true }).click();
    const p8Blocked = jobCard(page, PLACEMENT_JOB_B);
    const p8Reasons = p8Blocked.getByText("Why you cannot apply").locator("..");
    await expect(p8Reasons.getByRole("listitem")).toHaveCount(2);
    await expect(p8Reasons.getByText(/^Requires CPI at least 8\.0; yours is 7\.9/)).toBeVisible();
    await expect(p8Reasons.getByText(/penalt/i)).toBeVisible();
    await logout(page);

    // The appeal. Revoking the penalty dissolves it and the strikes it
    // consumed go back to being strikes, which is DIS's own arithmetic.
    await login(page, ADMIN);
    await page.goto(`/admin/discipline?enrollment_id=${p8Enrollment}`);
    // The penalty's own row, not a strike's: both offer a "Revoke", and the
    // one that matters says it was converted rather than awarded directly.
    const penaltyRow = page
      .getByText("Converted from strikes", { exact: false })
      .locator("xpath=ancestor::li[1]");
    await penaltyRow.getByRole("button", { name: "Revoke", exact: true }).click();
    dialog = page.getByRole("dialog");
    await dialog
      .getByRole("textbox", { name: "Reason *", exact: true })
      .fill("Appeal upheld: the talk clashed with a department viva");
    await dialog.getByRole("button", { name: "Revoke penalty" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText("Active penalties0", { exact: true })).toBeVisible();
    await logout(page);

    // And now job C, which has no rule, takes him.
    await login(page, students.p8[0]);
    await applyToJob(page, jobC, PLACEMENT_JOB_C);
    await logout(page);

    // D.46: P7's pipeline, which should be uneventful from end to end. He was
    // offered job B at Step 42; he simply accepts it.
    await login(page, students.p7[0]);
    await page.goto("/dashboard");
    await page
      .getByRole("link", { name: PLACEMENT_JOB_B, exact: true })
      .locator("xpath=ancestor::li[1]")
      .getByRole("button", { name: "Accept", exact: true })
      .click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Accept offer" }).click();
    await expect(dialog).toBeHidden();
    await expect(
      page.getByText(PLACEMENT_JOB_B, { exact: true }).locator("xpath=ancestor::li[1]"),
    ).toContainText("Accepted");
    await logout(page);

    // P8 is offered job C and accepts, which is the acceptance Step 49 finds
    // untouched when the job is cancelled out from under it.
    await login(page, PRIMARY_COORDINATOR);
    await extendOffers(page, jobC, ["p8"]);
    await logout(page);
    await login(page, students.p8[0]);
    await page.goto("/dashboard");
    await page
      .getByRole("link", { name: PLACEMENT_JOB_C, exact: true })
      .locator("xpath=ancestor::li[1]")
      .getByRole("button", { name: "Accept", exact: true })
      .click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Accept offer" }).click();
    await expect(dialog).toBeHidden();
    await expect(
      page.getByText(PLACEMENT_JOB_C, { exact: true }).locator("xpath=ancestor::li[1]"),
    ).toContainText("Accepted");
    await logout(page);
    expect(jobB).toBeTruthy();
  });

  test("D.48-D.50 a forced status, a cancelled job, and the unplaced three", async ({ page }) => {
    test.setTimeout(240_000);
    page.setDefaultTimeout(8_000);
    await login(page, ADMIN);
    const placementId = await staffCycleId(page, PLACEMENT_CYCLE);
    await logout(page);

    // D.48: the forced transition, on P11's placement application — the
    // "emergency override" his card warns him about.
    await login(page, ADMIN);
    const p11Enrollment = await enrollmentId(page, students.p11[0]);
    await page.goto(`/staff/student/${p11Enrollment}`);
    const p11Application = page
      .getByRole("heading", { name: PLACEMENT_JOB_C, exact: true })
      .locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' bg-card ')][1]");
    await p11Application.getByRole("button", { name: "Force transition" }).click();
    let dialog = page.getByRole("dialog");
    await dialog
      .getByRole("combobox", { name: "Destination status *", exact: true })
      .selectOption("withdrawn");
    await dialog
      .getByRole("textbox", { name: "Reason *", exact: true })
      .fill("Recorded by hand after the student withdrew in person");
    // The preview's job is to say plainly that this is a status write and
    // nothing else — and to name the consequences it is *not* performing, so
    // the operator knows what a sanctioned command would have done for them.
    await expect(dialog).toContainText(/consequence/i);
    await dialog.getByRole("button", { name: "Force transition" }).click();
    await expect(dialog).toBeHidden();

    // Forced, and recorded as forced: an ordinary withdrawal and a hand-written
    // one have to be tellable apart afterwards.
    await expect(p11Application.getByText("forced", { exact: false }).first()).toBeVisible();
    await expect(
      p11Application.getByText("Recorded by hand after the student withdrew in person", {
        exact: true,
      }),
    ).toBeVisible();
    await logout(page);

    // D.49: job C carries every shape the cancellation has to distinguish —
    // P8's accepted offer, P10's unanswered one, and two applications still
    // live in a round.
    await login(page, PRIMARY_COORDINATOR);
    const jobC = await staffJobId(page, placementId, PLACEMENT_JOB_C);
    await page.goto(`/staff/jobs/${jobC}?cycle_id=${placementId}`);
    await page.getByRole("button", { name: "Cancel job" }).click();
    dialog = page.getByRole("dialog");
    await dialog
      .getByRole("textbox", { name: "Reason *", exact: true })
      .fill("Company withdrew the role for this season");
    // Stated before the rows: what will be rejected, and what this command
    // deliberately will not unwind.
    await expect(dialog).toContainText("left untouched — unwinding those is terminate_offer's job");
    for (const key of ["p5", "p9", "p10"] as const) {
      await expect(dialog.getByText(students[key][1], { exact: false })).toBeVisible();
    }
    // The accepted one is named too, in the bucket that says nothing happens
    // to it — JOB-5's whole point is which applications a cancellation misses.
    await expect(dialog.getByText(students.p8[1], { exact: false })).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel job" }).click();
    await expect(dialog).toBeHidden();
    await logout(page);

    // P10's offer is gone with the job; P8's acceptance is not.
    await login(page, students.p10[0]);
    await page.goto("/dashboard");
    await expect(
      page.getByText(PLACEMENT_JOB_C, { exact: true }).locator("xpath=ancestor::li[1]"),
    ).toContainText("Rejected");
    await expect(page.getByRole("link", { name: PLACEMENT_JOB_C, exact: true })).toHaveCount(0);
    await logout(page);

    await login(page, students.p8[0]);
    await page.goto("/dashboard");
    await expect(
      page.getByText(PLACEMENT_JOB_C, { exact: true }).locator("xpath=ancestor::li[1]"),
    ).toContainText("Accepted");
    await logout(page);

    // D.50: the three who end the season unplaced, and the one of them who is
    // not looking. P5's tag is what keeps him out of ANA-3's denominator.
    await login(page, ADMIN);
    const p5Enrollment = await enrollmentId(page, students.p5[0]);
    await page.goto(`/staff/student/${p5Enrollment}`);
    const p5Membership = page
      .getByText(PLACEMENT_CYCLE, { exact: true })
      .locator("xpath=ancestor::li[1]");
    await p5Membership.getByRole("button", { name: "Not tagged" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("combobox", { name: "Outcome" }).selectOption("not_seeking");
    await dialog.getByRole("button", { name: "Save tag" }).click();
    await expect(dialog).toBeHidden();
    await expect(p5Membership.getByRole("button", { name: "Not seeking" })).toBeVisible();

    // None of the three holds an accepted placement offer, portal or external.
    for (const key of ["p5", "p9", "p10"] as const) {
      const id = await enrollmentId(page, students[key][0]);
      await page.goto(`/staff/student/${id}`);
      await expect(page.getByText("No external offers.")).toBeVisible();
      const offers = page
        .getByRole("heading", { name: "Offers" })
        .locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' bg-card ')][1]");
      await expect(offers.getByText("Accepted", { exact: true })).toHaveCount(0);
    }
    await logout(page);
  });

  test("D.51-D.54 coord2 runs the winter internship from membership to acceptance", async ({ page }) => {
    test.setTimeout(240_000);
    page.setDefaultTimeout(8_000);

    // D.51: creation and assignment are global administration, and therefore
    // already belong to the seed (R.18). coord2 proves that assignment by
    // opening the cycle, while the policy proves every student must enter via
    // the queue rather than becoming active on join.
    await login(page, COORD2);
    const winterId = await staffCycleId(page, WINTER_CYCLE);
    await page.goto(`/staff/cycles/${winterId}`);
    await expect(page.getByRole("heading", { name: WINTER_CYCLE })).toBeVisible();
    const assignedCoordinator = page.getByText(COORD2, { exact: true }).locator("xpath=ancestor::li[1]");
    await expect(assignedCoordinator).toContainText("Demo Coordinator 02");
    await expect(page.getByRole("checkbox", { name: "Membership needs approval" })).toBeChecked();
    await expect(page.getByRole("spinbutton", { name: "Accepted-offer cap" })).toHaveValue("1");

    const winterJob = await createJob(page, winterId, {
      title: WINTER_JOB,
      company: "Terra Nova Materials",
      description: "Systems engineering for the winter internship programme.",
      deadline: "2027-12-31T17:00",
    });
    await addRounds(page, winterId, winterJob, ["Technical"]);
    await publishJob(page, winterId, winterJob);
    await logout(page);

    const winterApplicants = ["p1", "p2", "p9", "p10"] as const;
    for (const key of winterApplicants) {
      await login(page, students[key][0]);
      await joinCycle(page, WINTER_CYCLE, true);
      await logout(page);
    }

    // R.19 makes the approvals explicit: without them the published job is
    // visible, but all four applications are correctly gated by membership.
    await login(page, COORD2);
    await page.goto(`/staff/cycles/${winterId}/approvals`);
    await page.getByRole("button", { name: "Paste roll numbers or emails" }).click();
    await page
      .getByRole("textbox", { name: "Paste roll numbers or emails" })
      .fill(winterApplicants.map((key) => ROLL[key]).join("\n"));
    await page.getByRole("button", { name: "Add to selection" }).click();
    await page.getByRole("button", { name: "Approve selected" }).click();
    let dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Will approve (4)")).toBeVisible();
    for (const key of winterApplicants) {
      await expect(dialog.getByText(students[key][1], { exact: true })).toBeVisible();
    }
    await dialog.getByRole("button", { name: "Approve" }).click();
    await expect(dialog).toBeHidden();
    await page.getByRole("combobox", { name: "Membership status" }).selectOption("active");
    await expect(page.getByText("4 active members in this cycle.")).toBeVisible();
    await logout(page);

    // D.52-D.53: neither a placement outcome anywhere nor an internship
    // accepted in another cycle gates a winter internship. Reaching the real
    // application form — with no refusal list — is the browser-level proof.
    for (const key of winterApplicants) {
      await login(page, students[key][0]);
      await page.goto(`/jobs/${winterJob}`);
      await expect(page.getByText("Why you cannot apply")).toHaveCount(0);
      await applyToJob(page, winterJob, WINTER_JOB);
      await logout(page);
    }

    // D.54: one round has no next round, so coord2 uses the sanctioned direct
    // offer path. P9 and P10 both answer on their own dashboards.
    await login(page, COORD2);
    await extendOffers(page, winterJob, ["p9", "p10"]);
    await logout(page);
    for (const key of ["p9", "p10"] as const) {
      await login(page, students[key][0]);
      await acceptDashboardOffer(page, WINTER_JOB);
      await logout(page);
    }
  });

  test("D.55-D.57 analytics, reconstructable records, and a reusable job export", async ({ page }) => {
    test.setTimeout(300_000);
    page.setDefaultTimeout(8_000);
    await login(page, ADMIN);

    const openId = await staffCycleId(page, OPEN_CYCLE);
    const summerId = await staffCycleId(page, SUMMER_CYCLE);
    const placementId = await staffCycleId(page, PLACEMENT_CYCLE);
    const winterId = await staffCycleId(page, WINTER_CYCLE);
    const winterJob = await staffJobId(page, winterId, WINTER_JOB);

    // D.55: the portal-wide placement derivation includes the unattached
    // off-campus offer as well as P1's attached PPO. These are students, not
    // acceptance rows, so repeated acceptances never inflate the five.
    await page.goto("/admin/analytics");
    await expect(page.getByRole("heading", { name: "Portal analytics" })).toBeVisible();
    const placedAcrossPortal = page
      .getByRole("heading", { name: "Placed across the portal" })
      .locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' bg-card ')][1]");
    await expect(placedAcrossPortal).toContainText("5 students are placed, 2 of them externally");

    // Every cycle dashboard is opened. The winter figures are the exact four
    // applications and two direct offers just watched; the placement split is
    // non-zero on both sides because P1's PPO is attached there.
    for (const cycleId of [openId, summerId, placementId, winterId]) {
      await page.goto(`/staff/cycles/${cycleId}/analytics`);
      await expect(page.getByRole("heading", { name: "Analytics" })).toBeVisible();
      await expect(page.getByRole("table", { name: "Funnel counts" })).toBeVisible();
      await expect(page.getByRole("table", { name: "By program" })).toBeVisible();
      await expect(page.getByRole("table", { name: "By branch" })).toBeVisible();
      await expect(page.getByRole("table", { name: "By gender" })).toBeVisible();
    }

    await page.goto(`/staff/cycles/${winterId}/analytics`);
    const winterFunnel = page.getByRole("table", { name: "Funnel counts" });
    await expect(winterFunnel.getByRole("row", { name: "Registered 4" })).toBeVisible();
    await expect(winterFunnel.getByRole("row", { name: "Applied 4" })).toBeVisible();
    await expect(winterFunnel.getByRole("row", { name: "Offered 2" })).toBeVisible();
    await expect(winterFunnel.getByRole("row", { name: "Placed 2" })).toBeVisible();
    const byProgram = page.getByRole("table", { name: "By program" });
    for (const [column, total] of [[1, 4], [2, 4], [3, 2], [4, 2]] as const) {
      const cells = await byProgram.locator(`tbody tr td:nth-child(${column + 1})`).allTextContents();
      expect(cells.reduce((sum, cell) => sum + Number(cell.trim()), 0)).toBe(total);
    }

    // The job funnel is the same population at job scope, and the company
    // screen carries hiring history alongside its ordinary company record.
    await page.goto(`/staff/jobs/${winterJob}/analytics`);
    const jobFunnel = page.getByRole("table", { name: "Job funnel" });
    await expect(jobFunnel.getByRole("row", { name: "Applied 4" })).toBeVisible();
    await expect(jobFunnel.getByRole("row", { name: "Offered 2" })).toBeVisible();
    await expect(jobFunnel.getByRole("row", { name: "Accepted 2" })).toBeVisible();
    await page.goto("/staff/companies");
    await page.getByRole("link", { name: "Solstice Robotics", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Compensation history" })).toBeVisible();
    const companyHistory = page.getByRole("table", { name: "Compensation by cycle" });
    await expect(companyHistory).toContainText(OPEN_CYCLE);
    await expect(companyHistory).toContainText(SUMMER_CYCLE);
    await expect(companyHistory).toContainText(PLACEMENT_CYCLE);

    // D.56: reopening the records is the assertion that the stories survive
    // outside their action screens. The consequential human reasons and their
    // actors are still attached to the event rows that need them.
    const p3Enrollment = await enrollmentId(page, students.p3[0]);
    await page.goto(`/staff/student/${p3Enrollment}`);
    await expect(page.getByRole("heading", { name: students.p3[1] })).toBeVisible();
    await expect(page.getByText("Company revoked the offer before joining", { exact: true }).first()).toBeVisible();

    const p8Enrollment = await enrollmentId(page, students.p8[0]);
    await page.goto(`/staff/student/${p8Enrollment}`);
    await expect(page.getByRole("heading", { name: students.p8[1] })).toBeVisible();
    const appeal = page
      .getByText("Revoke penalty", { exact: true })
      .first()
      .locator("xpath=ancestor::li[1]");
    await expect(appeal).toContainText("CDS Administrator");
    await appeal.locator("summary").click();
    await expect(appeal.getByText("Appeal upheld: the talk clashed with a department viva", { exact: true })).toBeVisible();

    const p1Enrollment = await enrollmentId(page, students.p1[0]);
    await page.goto(`/staff/student/${p1Enrollment}`);
    await page.getByRole("button", { name: "Edit profile" }).click();
    let dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("spinbutton", { name: "CPI" })).toHaveValue("8.60");
    await dialog.getByRole("spinbutton", { name: "CPI" }).fill("8.65");
    await expect(dialog.getByText("CPI changes")).toBeVisible();
    await dialog.getByRole("button", { name: "Save profile" }).click();
    await expect(dialog).toBeHidden();

    for (const title of [OPEN_JOB_ONE, OPEN_JOB_TWO, SUMMER_JOB_ONE, SUMMER_JOB_THREE, WINTER_JOB]) {
      const application = page
        .getByRole("heading", { name: title, exact: true })
        .locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' bg-card ')][1]");
      const cpi = application.getByText("CPI", { exact: true }).locator("xpath=ancestor::tr[1]");
      await expect(cpi).toContainText("8.60");
      await expect(cpi).toContainText("8.65");
      await expect(cpi).toContainText("Changed");
    }

    // D.57: job 1 owns all question types, so its registry must expose those
    // questions as selectable columns. Save the order, build and download,
    // then reopen the modal and prove the preset drives a second export.
    const summerJob = await staffJobId(page, summerId, SUMMER_JOB_ONE);
    await page.goto(`/staff/jobs/${summerJob}/board`);
    await page.getByRole("button", { name: "Export students" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("checkbox", { name: "Why this internship?" }).check();
    await dialog.getByRole("checkbox", { name: "Portfolio link" }).check();
    const savePreset = page.waitForResponse((response) =>
      response.url().includes("/api/v1/commands/save_export_preset") && response.request().method() === "POST",
    );
    await dialog.getByRole("button", { name: "Save for this job" }).click();
    expect((await savePreset).ok()).toBeTruthy();
    await buildAndDownloadExport(page);
    await dialog.getByText("Close", { exact: true }).click();

    await page.getByRole("button", { name: "Export students" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("checkbox", { name: "Why this internship?" })).toBeChecked();
    await expect(dialog.getByRole("checkbox", { name: "Portfolio link" })).toBeChecked();
    await buildAndDownloadExport(page);
    await dialog.getByText("Close", { exact: true }).click();
    await logout(page);
  });

  test("D.58-D.60 archive safety, the canned report, and a clean consistency pass", async ({ page }) => {
    test.setTimeout(240_000);
    page.setDefaultTimeout(8_000);
    await login(page, ADMIN);
    const openId = await staffCycleId(page, OPEN_CYCLE);

    // D.58: only P2's internship application remains non-terminal. The other
    // open placement application was swept by Step 42, while P1's two accepted
    // applications are explicitly outside the archive cascade.
    await page.goto(`/staff/cycles/${openId}`);
    await page.getByRole("button", { name: "Archive", exact: true }).click();
    let dialog = page.getByRole("dialog");
    const withdrawn = dialog.getByText("Will auto-withdraw (1)").locator("xpath=ancestor::section[1]");
    await expect(withdrawn).toContainText(students.p2[1]);
    await expect(withdrawn).toContainText(OPEN_JOB_ONE);
    const untouched = dialog.getByText("Will remain untouched (2)").locator("xpath=ancestor::section[1]");
    await expect(untouched).toContainText(students.p1[1]);
    await expect(untouched).toContainText(OPEN_JOB_ONE);
    await expect(untouched).toContainText(OPEN_JOB_TWO);
    await dialog.getByRole("button", { name: "Archive cycle" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText("This cycle is archived", { exact: true })).toBeVisible();

    // Read operations, including exports, survive archival.
    await page.goto(`/staff/cycles/${openId}/analytics`);
    await expect(page.getByText("1 student placed", { exact: false })).toBeVisible();
    await expect(page.getByText("1 further acceptance not counted", { exact: false })).toBeVisible();
    await page.getByRole("button", { name: "Export members" }).click();
    dialog = page.getByRole("dialog");
    await buildAndDownloadExport(page);
    await dialog.getByText("Close", { exact: true }).click();

    // A real write is still presented by the jobs list, so use it to verify
    // the server's universal archived-cycle guard rather than merely checking
    // that controls on the cycle detail happen to be disabled.
    await page.goto(`/staff/cycles/${openId}/jobs`);
    await page.getByRole("button", { name: "New job" }).click();
    await page.getByRole("textbox", { name: "Title" }).fill("Archive mutation probe");
    await page.getByRole("combobox", { name: "Company" }).selectOption({ label: "Solstice Robotics" });
    await page.getByRole("combobox", { name: "Outcome" }).selectOption("internship");
    await page.getByRole("textbox", { name: "Description" }).fill("This write must be refused.");
    await page.getByRole("button", { name: "Create job" }).click();
    await expect(page.getByText("The cycle is archived and is now read-only", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Archive mutation probe" })).toHaveCount(0);

    // D.59: the report is generated from the same analytics object as every
    // funnel. The conservative flat rate leads; the adjusted denominator is
    // explicitly secondary; and nine unique in-cycle placed students means
    // P1's repeated open-cycle acceptance was not counted twice. P4's
    // unattached offer belongs only to the portal-wide DER-1 figure above.
    await page.goto("/admin/analytics");
    const report = page.getByRole("table", { name: "Per-batch, per-programme outcomes" });
    await expect(report).toBeVisible();
    const headers = await report.getByRole("columnheader").allTextContents();
    expect(headers.indexOf("Placement rate")).toBeLessThan(headers.indexOf("Placement rate (seeking only)"));
    const total = report.getByRole("row").filter({ has: page.getByRole("cell", { name: "All", exact: true }) }).last();
    const placedTotalColumn = headers.indexOf("Placed (total)");
    expect(placedTotalColumn).toBeGreaterThan(0);
    await expect(total.getByRole("cell").nth(placedTotalColumn)).toHaveText("9");
    await expect(page.getByText("Placed ÷ all active registrations", { exact: true })).toBeVisible();
    await expect(page.getByText(/Seeking only — excludes higher studies/)).toBeVisible();

    // D.60: the operational trigger runs the same complete pass as the nightly
    // worker. Its dry run must say zero before confirmation, and the recorded
    // pass leaves the open-findings view empty afterwards.
    await page.goto("/admin/findings");
    await page.getByRole("button", { name: "Run now" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Every invariant holds. Nothing will be recorded.")).toBeVisible();
    await expect(dialog.getByText(/0 violations/)).toBeVisible();
    await dialog.getByRole("button", { name: "Run the checker" }).click();
    await expect(dialog).toBeHidden();
    await expect(
      page.getByText("Nothing has drifted. The last pass asserted every invariant and found no violation."),
    ).toBeVisible();
    await logout(page);
  });

  /**
   * CYC-3.7 and 3.8 through the browser, which had no surface until now.
   *
   * Placed after D.60 deliberately: it mutates a membership and cascades an
   * application, so running it earlier would move the analytics numbers
   * D.55-D.57 assert. It therefore runs the consistency checker itself rather
   * than leaning on D.60's pass — a removal that leaves the database drifted
   * is the failure worth catching, and the step that caused it is the one that
   * should catch it.
   */
  test("D.61 a member is removed with their applications named, and restored", async ({ page }) => {
    test.setTimeout(120_000);
    page.setDefaultTimeout(8_000);

    await login(page, COORD2);
    const winterId = await staffCycleId(page, WINTER_CYCLE);
    await page.goto(`/staff/cycles/${winterId}/approvals`);
    await page.getByRole("combobox", { name: "Membership status" }).selectOption("active");
    await expect(page.getByText("4 active members in this cycle.")).toBeVisible();

    // P1 applied to the winter job and was never offered, so the membership
    // carries exactly one live application for the cascade to close.
    const row = page.getByRole("row").filter({ hasText: students.p1[1] });
    await row.getByRole("button", { name: "Remove" }).click();
    let dialog = page.getByRole("dialog");
    await expect(dialog.getByText(`Remove ${students.p1[1]} from this cycle?`)).toBeVisible();
    await dialog
      .getByRole("textbox", { name: /^Reason/ })
      .fill("Left the institute mid-season");
    // Named, never counted (the design review §4.21, widened by §4.37).
    await expect(dialog.getByText("Applications this closes (1)")).toBeVisible();
    await expect(dialog.getByText(WINTER_JOB, { exact: false })).toBeVisible();
    await dialog.getByRole("button", { name: "Remove member" }).click();
    await expect(dialog).toBeHidden();

    // The roster moves them out, and the cascade actually ran.
    await page.getByRole("combobox", { name: "Membership status" }).selectOption("removed");
    await expect(page.getByText("1 removed member in this cycle.")).toBeVisible();
    await expect(page.getByRole("row").filter({ hasText: students.p1[1] })).toBeVisible();
    await logout(page);

    await login(page, ADMIN);
    const p1Enrollment = await enrollmentId(page, students.p1[0]);
    await page.goto(`/staff/student/${p1Enrollment}`);
    // Applications are cards on this screen, each a region named by its own
    // job heading, so one application can be addressed out of several.
    const winterApplication = page.getByRole("region", { name: WINTER_JOB });
    await expect(winterApplication).toContainText("Auto-withdrawn");
    await logout(page);

    // CYC-3.8: restoring returns the membership and deliberately leaves the
    // applications closed — reinstatement is per application (INT-1), and the
    // dialog says so rather than implying an undo.
    await login(page, COORD2);
    await page.goto(`/staff/cycles/${winterId}/approvals`);
    await page.getByRole("combobox", { name: "Membership status" }).selectOption("removed");
    await page
      .getByRole("row")
      .filter({ hasText: students.p1[1] })
      .getByRole("button", { name: "Restore" })
      .click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText(/Applications closed when they left stay closed/)).toBeVisible();
    await dialog.getByRole("button", { name: "Restore membership" }).click();
    await expect(dialog).toBeHidden();
    await page.getByRole("combobox", { name: "Membership status" }).selectOption("active");
    await expect(page.getByText("4 active members in this cycle.")).toBeVisible();
    await logout(page);

    // A pending row offers neither control, and says which rule refuses it.
    await login(page, ADMIN);
    await page.goto("/admin/findings");
    await page.getByRole("button", { name: "Run now" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText(/0 violations/)).toBeVisible();
    await dialog.getByRole("button", { name: "Run the checker" }).click();
    await expect(dialog).toBeHidden();
    await expect(
      page.getByText("Nothing has drifted. The last pass asserted every invariant and found no violation."),
    ).toBeVisible();
    await logout(page);
  });

  /** D.47 remains last and read-only so its adversarial scope check is isolated. */
  test("D.47 a coordinator is refused a cycle he does not run", async ({ page }) => {
    page.setDefaultTimeout(8_000);

    // The winter cycle's id has to come from someone allowed to see it, which
    // is the point of the step.
    await login(page, ADMIN);
    const winterId = await staffCycleId(page, WINTER_CYCLE);
    await logout(page);

    // Scope, not role. The primary coordinator has three assigned cycles;
    // this one is coord2's, and the server says so rather than rendering an
    // empty board.
    await login(page, PRIMARY_COORDINATOR);
    await page.goto(`/staff/cycles/${winterId}`);
    await expect(page.getByRole("heading", { name: WINTER_CYCLE })).toHaveCount(0);
    const refusal = page.getByRole("alert");
    await expect(refusal).toBeVisible();
    await expect(refusal.getByText("You cannot access this page")).toBeVisible();

    // The jobs list refuses its data the same way — and then offers to create
    // a job in the cycle it has just refused him. Keep this assertion as the
    // script states it: Step 47 asks for a clean 403, and a create control on
    // a refused page is not one. The server would reject the create, so this
    // is presentation and not access, but it is the operator-facing half of
    // the same wall.
    await page.goto(`/staff/cycles/${winterId}/jobs`);
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("button", { name: "New job" })).toHaveCount(0);
    await logout(page);
  });
});
