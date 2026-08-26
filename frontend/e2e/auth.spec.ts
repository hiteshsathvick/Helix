import { expect, test } from "@playwright/test";
import { registerAndLogin, uniqueEmail } from "./helpers";

test("register, log in, and see the account page", async ({ page }) => {
  const email = uniqueEmail();
  await registerAndLogin(page, email, "a-strong-password-1");

  await expect(page.getByTestId("account-info")).toContainText(email);
});
