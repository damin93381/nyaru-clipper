import { defineConfig } from "@playwright/test";

const chromeExecutablePath = process.env.PLAYWRIGHT_CHROME_EXECUTABLE;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  use: {
    baseURL: "http://127.0.0.1:5173",
    ...(chromeExecutablePath === undefined ? {} : { executablePath: chromeExecutablePath }),
    trace: "retain-on-failure",
  },
  webServer: {
    command: "pnpm dev --host 0.0.0.0 --port 5173",
    port: 5173,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
