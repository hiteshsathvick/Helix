import { expect, test } from "@playwright/test";
import { registerAndLogin, uniqueEmail } from "./helpers";

// No AI node in the default graph -- this exercises the durable execution
// path (trigger -> worker -> completed), not the LLM, so it doesn't need
// AI_DEFAULT_PROVIDER=mock the way assistant.spec.ts/agents.spec.ts do.
test("create a workflow, activate it, trigger a run, and see it complete", async ({ page }) => {
  await registerAndLogin(page, uniqueEmail(), "a-strong-password-1");

  await page.goto("/orgs/new");
  await page.getByPlaceholder("Organization name").fill("E2E Workflows Org");
  await page.getByRole("button", { name: "Create organization" }).click();
  await page.waitForURL(/\/orgs\/.+\/members/);
  const orgId = page.url().match(/\/orgs\/([^/]+)\//)?.[1];
  expect(orgId).toBeTruthy();

  await page.goto(`/orgs/${orgId}/workflows`);
  await page.getByTestId("workflow-name-input").fill("E2E Workflow");
  await page.getByTestId("create-workflow-submit").click();

  await page.locator('[data-testid^="workflow-link-"]').first().click();
  await page.waitForURL(/\/workflows\/[^/]+$/);

  await page.getByTestId("set-status-active").click();
  await expect(page.getByTestId("workflow-detail-status")).toHaveText("active");

  await page.getByTestId("trigger-workflow-run").click();

  await page.locator('[data-testid^="run-link-"]').first().click();
  await page.waitForURL(/\/runs\/[^/]+$/);

  await expect(page.getByTestId("run-detail-status")).toHaveText("completed", { timeout: 15_000 });
});
