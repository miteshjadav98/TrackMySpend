/** Exercise the production app with deterministic API fixtures, on a dedicated local port. */
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  use: {
    baseURL: "http://127.0.0.1:3100",
    browserName: "chromium",
    // CI uses Playwright's pinned browser; local runs can reuse an installed Chrome.
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run start -- --hostname 127.0.0.1 --port 3100",
    url: "http://127.0.0.1:3100/login",
    reuseExistingServer: false,
  },
});
