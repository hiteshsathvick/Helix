import { expect, test } from "@playwright/test";
import { registerAndLogin, uniqueEmail } from "./helpers";

// Needs AI_DEFAULT_PROVIDER=mock (Phase 20) -- an agent run always calls
// complete_with_tools at least once, real or not.
test("create an agent, trigger a run, and see it complete", async ({ page }) => {
  await registerAndLogin(page, uniqueEmail(), "a-strong-password-1");

  await page.goto("/orgs/new");
  await page.getByPlaceholder("Organization name").fill("E2E Agents Org");
  await page.getByRole("button", { name: "Create organization" }).click();
  await page.waitForURL(/\/orgs\/.+\/members/);
  const orgId = page.url().match(/\/orgs\/([^/]+)\//)?.[1];
  expect(orgId).toBeTruthy();

  await page.goto(`/orgs/${orgId}/agents`);
  await page.getByTestId("agent-name-input").fill("E2E Agent");
  await page.getByTestId("agent-instructions-input").fill("Answer directly, no tools needed.");
  await page.getByTestId("create-agent-submit").click();

  await page.locator('[data-testid^="agent-link-"]').first().click();
  await page.waitForURL(/\/agents\/[^/]+$/);

  await page.getByTestId("run-input").fill("Just answer directly.");
  await page.getByRole("button", { name: "Run" }).click();

  await page.locator('[data-testid^="run-link-"]').first().click();
  await page.waitForURL(/\/runs\/[^/]+$/);

  await expect(page.getByTestId("run-detail-status")).toHaveText("completed", { timeout: 15_000 });
  await expect(page.getByTestId("run-detail-output")).toContainText(
    "This is a mock response from the test LLM provider."
  );
});
