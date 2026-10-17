import { expect, test } from '@playwright/test'
import { resetData, seedRun } from './db'

test.beforeEach(resetData)

test('the status bar shows the latest run and opens the last four', async ({ page }) => {
  await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: '2026-10-16T12:24:00Z' })
  await seedRun({
    kind: 'pre_close',
    status: 'degraded',
    published: true,
    finished: '2026-10-16T19:31:00Z',
  })
  await page.goto('/')
  const pill = page.getByRole('button', { name: /Pre-close 15:31/ })
  await expect(pill).toContainText('degraded')
  await expect(page.getByText('30/33', { exact: true }).first()).toBeVisible()
  await pill.click()
  const runs = page.getByRole('menu')
  await expect(runs.getByRole('menuitem')).toHaveCount(2)
  await expect(runs).toContainText('Oct 16 · pre-open 08:24')
  await page.keyboard.press('Escape')
  await expect(runs).not.toHaveClass(/open/)
  await expect(page.getByText('US Paper')).toBeVisible()
  await expect(page.getByRole('contentinfo')).toContainText(
    'Not financial or tax advice. Forecasts are probabilistic and can be wrong.',
  )
  await expect(page.getByRole('contentinfo')).toContainText('USD/CAD from the Bank of Canada.')
})

test('a failed run raises the stale banner', async ({ page }) => {
  await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: '2026-10-16T12:24:00Z' })
  await seedRun({
    kind: 'pre_close',
    status: 'failed',
    published: false,
    finished: '2026-10-16T19:31:00Z',
    summary: { failed_reason: ['TSX: universe too small (2 < 300)'] },
  })
  await page.goto('/')
  await expect(page.locator('.banner.danger')).toHaveText(
    'The Oct 16 · pre-close 15:31 run failed: TSX: universe too small (2 < 300). Showing the Oct 16 · pre-open 08:24 results until the next run.',
  )
})

test('before any run, the status bar says so', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('No runs yet')).toBeVisible()
  await expect(page.locator('.banner.danger')).toHaveCount(0)
})

test('dark mode is remembered', async ({ page }) => {
  await page.goto('/')
  const dark = () => page.evaluate(() => document.documentElement.classList.contains('dark'))
  const before = await dark()
  await page.getByRole('banner').getByRole('button', { name: 'Switch between light and dark' }).click()
  await expect.poll(dark).toBe(!before)
  await page.reload()
  await expect.poll(dark).toBe(!before)
})
