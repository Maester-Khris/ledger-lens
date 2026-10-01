import { defineConfig, devices } from '@playwright/test';

/**
 * Browser end-to-end tests (e2e/*.e2e.ts), run with `npm run test:e2e`. They drive a deployed site, not the dev
 * server: E2E_BASE_URL defaults to the public demo. vitest never picks them up (it only matches *.test / *.spec).
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',
  timeout: 180_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [['list']],
  outputDir: 'test-results',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'https://ledgerlens.nknext.dev',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
