import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    // React Testing Library's automatic unmount-after-each-test relies on a
    // *global* afterEach; without this, DOM from one test leaks into the
    // next (each test file's own explicit `import { it, expect } from
    // "vitest"` isn't enough for that specific internal detection).
    globals: true,
    // Playwright specs live in e2e/ and run via `npm run test:e2e`, not
    // this runner — excluding them keeps `vitest run` from trying (and
    // failing) to execute Playwright's own test() API as a unit test.
    exclude: ["e2e/**", "node_modules/**"],
  },
});
