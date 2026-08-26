import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { registerAndLogin, uniqueEmail } from "./helpers";

test("create an org, upload a document, and find it via search", async ({ page }) => {
  await registerAndLogin(page, uniqueEmail(), "a-strong-password-1");

  await page.goto("/orgs/new");
  await page.getByPlaceholder("Organization name").fill("E2E Test Org");
  await page.getByRole("button", { name: "Create organization" }).click();
  await page.waitForURL(/\/orgs\/.+\/members/);
  const orgId = page.url().match(/\/orgs\/([^/]+)\//)?.[1];
  expect(orgId).toBeTruthy();

  const keyword = `zylophant${randomUUID().slice(0, 8)}`;
  await page.goto(`/orgs/${orgId}/documents`);
  await page.getByTestId("upload-input").setInputFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(`This document mentions a very unique term: ${keyword}.`),
  });

  // Ingestion runs asynchronously in a worker; the documents page itself
  // polls while a document is "pending", so waiting for that text to
  // disappear from the row is the real, non-arbitrary signal it's done.
  await expect(page.getByText(/\(pending\)/)).toHaveCount(0, { timeout: 30_000 });

  await page.goto(`/orgs/${orgId}/search`);
  await page.getByTestId("search-input").fill(keyword);
  await page.getByRole("button", { name: "Search" }).click();

  await expect(page.getByTestId("search-results")).toContainText(keyword);
});
