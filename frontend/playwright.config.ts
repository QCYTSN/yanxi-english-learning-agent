import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false,
  retries: 0,
  reporter: 'line',
  use: {
    baseURL: process.env.IELTS_E2E_BASE_URL,
    browserName: 'chromium',
    storageState: process.env.IELTS_E2E_LAUNCH_URL ? './e2e/.auth/state.json' : undefined,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
})
