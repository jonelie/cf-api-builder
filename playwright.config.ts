import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',

  // Run tests sequentially — they share one server instance and one browser
  fullyParallel: false,

  // Retry once on CI so flaky network tests don't fail the whole run
  retries: process.env.CI ? 1 : 0,

  // HTML report: open with `npx playwright show-report`
  reporter: 'html',

  use: {
    // All page.goto('/some-path') calls are relative to this
    baseURL: 'http://localhost:3000',

    // Save a trace ZIP when a test fails on retry — inspect with `npx playwright show-trace`
    trace: 'on-first-retry',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // Auto-start the Express server before tests, shut it down after.
  // reuseExistingServer: if you already have `npm run dev` running locally,
  // Playwright will use that instead of spawning a second server.
  webServer: {
    command: 'node server.js',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    stdout: 'ignore',
    stderr: 'pipe',
  },
});
