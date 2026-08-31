import { expect, test } from "@playwright/test";
import { registerAndLogin, uniqueEmail } from "./helpers";

// Needs AI_DEFAULT_PROVIDER=mock (Phase 20) so the answer is deterministic
// and free -- see Makefile's test-e2e target / ci.yml's e2e job.
test("ask the assistant a question and see a streamed, cited answer", async ({ page }) => {
  await registerAndLogin(page, uniqueEmail(), "a-strong-password-1");

  await page.goto("/orgs/new");
  await page.getByPlaceholder("Organization name").fill("E2E Assistant Org");
  await page.getByRole("button", { name: "Create organization" }).click();
  await page.waitForURL(/\/orgs\/.+\/members/);
  const orgId = page.url().match(/\/orgs\/([^/]+)\//)?.[1];
  expect(orgId).toBeTruthy();

  await page.goto(`/orgs/${orgId}/documents`);
  await page.getByTestId("upload-input").setInputFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Helix supports a RAG assistant with streaming and citations."),
  });
  await expect(page.getByText(/\(pending\)/)).toHaveCount(0, { timeout: 30_000 });

  await page.goto(`/orgs/${orgId}/assistant`);
  await page.getByTestId("assistant-input").fill("What does Helix support?");
  await page.getByRole("button", { name: "Send" }).click();

  const answer = page.getByTestId("assistant-message-assistant");
  await expect(answer).toContainText("This is a mock response from the test LLM provider.", {
    timeout: 15_000,
  });
});
