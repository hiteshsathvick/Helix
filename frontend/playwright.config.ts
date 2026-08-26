import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    // No `webServer` here: unlike a plain Next.js app, this one needs the
    // whole docker-compose stack (postgres/redis/minio/api) up and healthy,
    // not just `next dev` — CI (and local runs) start that separately via
    // `docker compose up -d` before invoking Playwright.
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
