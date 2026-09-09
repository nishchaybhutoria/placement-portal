import { expect, type Locator, type Page, test } from "@playwright/test";

const STUDENT_EMAIL = "e2e.student@example.edu";
const COORDINATOR_EMAIL = "coordinator@example.edu";

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

async function openPlacement(page: Page) {
  await page.getByRole("link", { name: "Manage cycles" }).click();
  await page.getByRole("link", { name: "Placement 2026", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Placement 2026" })).toBeVisible();
}

async function openPlatformBoard(page: Page) {
  await openPlacement(page);
  await page.getByRole("link", { name: "Jobs", exact: true }).click();
  await page.getByRole("link", { name: "Platform Engineer", exact: true }).click();
  await page.getByRole("link", { name: "Board", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Platform Engineer" })).toBeVisible();
}

async function openPlatformOffers(page: Page) {
  await openPlatformBoard(page);
  await page.getByRole("link", { name: "Offers", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Platform Engineer offers" }),
  ).toBeVisible();
}

function cardForLink(page: Page, name: string): Locator {
  return page.getByRole("link", { name, exact: true }).locator("xpath=ancestor::li[1]");
}

function listRow(page: Page, text: string): Locator {
  return page.getByText(text, { exact: true }).locator("xpath=ancestor::li[1]");
}

async function applyTo(page: Page, job: string) {
  await page.getByRole("link", { name: job, exact: true }).click();
  await expect(page.getByRole("heading", { name: job })).toBeVisible();
  const form = page.locator("#application-form form");
  await expect(form).toBeVisible();
  await form.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(
    page.getByText("You already have an application for this job.", { exact: false }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Placement 2026", exact: true }).click();
}

test.describe.serial("F5 critical recruitment flows", () => {
  test("student journey exposes eligibility, acceptance, and the placement cascade", async ({
    page,
  }) => {
    await login(page, STUDENT_EMAIL);
    await page.getByRole("link", { name: "Cycles", exact: true }).click();

    const placementCard = page
      .getByRole("heading", { name: "Placement 2026" })
      .locator("xpath=../..");
    await placementCard.getByRole("button", { name: "Request to join" }).click();
    let dialog = page.getByRole("dialog");
    await dialog
      .getByRole("combobox", { name: "Resume for this cycle" })
      .selectOption({ label: "Primary resume" });
    await dialog
      .getByRole("combobox", { name: "Consent" })
      .selectOption({ label: "I consent to sharing my application data" });
    await expect(dialog.getByText("What will happen")).toBeVisible();
    await dialog.getByRole("button", { name: "Request to join" }).click();
    await expect(placementCard.getByText("Pending", { exact: true })).toBeVisible();

    await logout(page);
    await login(page, COORDINATOR_EMAIL);
    await openPlacement(page);
    await page.getByRole("link", { name: /^Approvals/ }).click();
    const approvalRow = page
      .getByText("End-to-End Student", { exact: true })
      .locator("xpath=ancestor::tr[1]");
    await approvalRow.getByRole("checkbox", { name: "Select End-to-End Student" }).check();
    await page.getByRole("button", { name: "Approve selected" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("What will happen")).toBeVisible();
    await dialog.getByRole("button", { name: "Approve", exact: true }).click();
    // Wait for the dialog to go before asserting page-wide absence: its own
    // preview names the row it is about to approve (the design review §4.37), so a
    // page-wide locator matches it while the dialog is still closing.
    await expect(dialog).toBeHidden();
    await expect(page.getByText("End-to-End Student", { exact: true })).toBeHidden();

    await logout(page);
    await login(page, STUDENT_EMAIL);
    await page.getByRole("link", { name: "Cycles", exact: true }).click();
    await page.getByRole("link", { name: "Placement 2026", exact: true }).click();

    const ineligible = cardForLink(page, "Backend Engineer");
    const reasons = ineligible.getByText("Why you cannot apply").locator("..");
    await expect(reasons.getByRole("listitem")).toHaveCount(2);
    await expect(
      reasons.getByText("Requires active backlogs at most 0; yours is 1."),
    ).toBeVisible();
    await expect(
      reasons.getByText(
        "Requires primary branch one of Computer Science and Engineering, Electrical Engineering; yours is Mechanical Engineering.",
      ),
    ).toBeVisible();

    await applyTo(page, "Quantitative Researcher");
    await applyTo(page, "Platform Engineer");

    await logout(page);
    await login(page, COORDINATOR_EMAIL);
    await openPlatformBoard(page);
    await page.getByRole("checkbox", { name: "Select End-to-End Student" }).check();
    await page.getByRole("button", { name: "Advance", exact: true }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Will move (1)")).toBeVisible();
    await expect(dialog.getByText(/End-to-End Student.*pending offer/)).toBeVisible();
    await dialog.getByRole("button", { name: "Advance", exact: true }).click();

    await page.getByRole("link", { name: "Offers", exact: true }).click();
    await page.getByRole("checkbox", { name: "Select End-to-End Student" }).check();
    await page.getByRole("button", { name: "Extend / rollout" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("What will happen")).toBeVisible();
    await dialog.getByRole("button", { name: "Extend offers" }).click();
    await expect(listRow(page, "End-to-End Student").getByText("Offered")).toBeVisible();

    await logout(page);
    await login(page, STUDENT_EMAIL);
    await page.getByRole("link", { name: "Dashboard", exact: true }).click();
    const offer = cardForLink(page, "Platform Engineer");
    await offer.getByRole("button", { name: "Accept", exact: true }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Auto withdrawn", { exact: true })).toBeVisible();
    await dialog.getByRole("button", { name: "Accept offer" }).click();

    await expect(listRow(page, "Platform Engineer").getByText("Accepted")).toBeVisible();
    await expect(
      listRow(page, "Quantitative Researcher").getByText("Auto-withdrawn"),
    ).toBeVisible();
  });

  test("offer termination separates automatic effects and restores one application", async ({
    page,
  }) => {
    await login(page, COORDINATOR_EMAIL);
    await openPlatformOffers(page);
    const student = listRow(page, "End-to-End Student");
    await student.getByRole("button", { name: "Terminate", exact: true }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Restoration choices (1)")).toBeVisible();
    await dialog
      .getByRole("combobox", { name: "Kind" })
      .selectOption({ label: "Company revoked" });
    await dialog.getByRole("textbox", { name: "Reason" }).fill("Role withdrawn by company");
    await dialog
      .getByRole("checkbox", { name: "Restore Quantitative Researcher" })
      .check();

    await expect(dialog.getByText("Automatic effects", { exact: true })).toBeVisible();
    await expect(dialog.getByText("Restoration decisions", { exact: true })).toBeVisible();
    await expect(
      dialog.locator("li").filter({ hasText: "Restore Quantitative Researcher" }),
    ).toContainText("auto withdrawn → in progress · prior round restored");
    await dialog.getByRole("button", { name: "Terminate offer" }).click();
    await expect(student.getByText("Offer terminated")).toBeVisible();

    await logout(page);
    await login(page, STUDENT_EMAIL);
    await page.getByRole("link", { name: "Dashboard", exact: true }).click();
    await expect(
      listRow(page, "Platform Engineer").getByText("Offer terminated"),
    ).toBeVisible();
    await expect(
      listRow(page, "Quantitative Researcher").getByText("In progress"),
    ).toBeVisible();
  });

  test("bulk advance reports every unmatched roll and every planned move", async ({ page }) => {
    await login(page, COORDINATOR_EMAIL);
    await openPlatformBoard(page);
    await page.getByRole("button", { name: "Paste roll numbers or emails" }).click();
    await page
      .getByRole("textbox", { name: "Paste roll numbers or emails" })
      .fill("22120005\n22120006\nNO-MATCH-01\nNO-MATCH-02");
    await page.getByRole("button", { name: "Add to selection" }).click();
    await expect(page.getByText("4 selected", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Advance", exact: true }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Will move (2)")).toBeVisible();
    await expect(dialog.getByText(/Esha Nair.*pending offer/)).toBeVisible();
    await expect(dialog.getByText(/Farhan Khan.*pending offer/)).toBeVisible();
    await expect(dialog.getByText("Matched nothing (2)")).toBeVisible();
    await expect(dialog.getByText("NO-MATCH-01", { exact: true })).toBeVisible();
    await expect(dialog.getByText("NO-MATCH-02", { exact: true })).toBeVisible();
    await dialog.getByRole("button", { name: "Advance", exact: true }).click();

    await expect(listRow(page, "Esha Nair").getByText("Pending offer")).toBeVisible();
    await expect(listRow(page, "Farhan Khan").getByText("Pending offer")).toBeVisible();
  });
});
