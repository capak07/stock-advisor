import { defineConfig, devices } from '@playwright/test'
import { OWNER_STATE, localStack } from './e2e/stack'

const stack = localStack()
const PORT = 3100

/**
 * Browser tests against the local Supabase stack and a production build of the dashboard. The
 * tests share one database, so they run one at a time. On Windows they use the installed Edge;
 * elsewhere (CI) Playwright's Chromium (`npx playwright install chromium`).
 */
export default defineConfig({
  testDir: 'e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel: process.platform === 'win32' ? 'msedge' : undefined,
    locale: 'en-CA',
    timezoneId: 'America/Toronto',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'desktop',
      dependencies: ['setup'],
      use: { ...devices['Desktop Chrome'], channel: process.platform === 'win32' ? 'msedge' : undefined, storageState: OWNER_STATE },
    },
  ],
  webServer: {
    command: `npm run build && npx next start -p ${PORT}`,
    // The icon is served before any page exists, and the proxy lets it through.
    url: `http://127.0.0.1:${PORT}/icon.svg`,
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
    env: { SUPABASE_URL: stack.API_URL, SUPABASE_PUBLISHABLE_KEY: stack.PUBLISHABLE_KEY },
  },
})
