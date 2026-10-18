import { expect, test } from '@playwright/test'
import { resetData, seedHealth, seedRun, seedSources } from './db'

test.beforeEach(resetData)

test("every source shows this run's result, its daily check and its last answer, problems first", async ({ page }) => {
  const finished = new Date(Date.now() - 3_600_000)
  const runId = await seedRun({
    kind: 'pre_close',
    status: 'degraded',
    published: true,
    finished: finished.toISOString(),
    summary: { news: { items: 120, sentiment: 'unavailable' } },
  })
  await seedSources()
  const checkedAt = new Date(finished.getTime() - 60_000).toISOString()
  await seedHealth(null, checkedAt, [
    { source: 'yfinance_bars', status: 'ok' },
    { source: 'google_news', status: 'ok' },
    { source: 'sec_form4', status: 'ok' },
    { source: 'sec_8k', status: 'failed', error: 'HTTPStatusError: 503', consecutive_failures: 2 },
    { source: 'coingecko', status: 'ok' },
  ])
  await seedHealth(runId, finished.toISOString(), [
    { source: 'yfinance_bars', status: 'ok', latency_ms: 185_484, records: 472_845 },
    { source: 'google_news', status: 'ok', latency_ms: 0, records: 7612 },
    { source: 'sec_form4', status: 'partial', error: 'PartialFetch: stopped after 41 of 300 symbols' },
    { source: 'sec_8k', status: 'failed', error: 'HTTPStatusError: 503', consecutive_failures: 3 },
    { source: 'coingecko', status: 'ok' },
  ])

  await page.goto('/sources')
  await expect(page.getByRole('heading', { name: 'Source health', level: 1 })).toBeVisible()
  const summary = page.getByRole('region', { name: 'Summary' })
  await expect(summary.locator('.card').nth(0)).toContainText('3/5 OK1 partial · 1 failed')
  await expect(summary.locator('.card').nth(1)).toContainText('4/5 OK1 failed')
  await expect(summary.locator('.card').nth(2)).toContainText('3/3 OK')
  await expect(summary.locator('.card').nth(3)).toContainText(/\d+(\.\d)? MB/)
  await expect(page.getByRole('note')).toHaveText(/^News sentiment: FinBERT couldn't be loaded/)

  const rows = page.locator('#sources tbody tr')
  await expect(rows.locator('td:first-child .sym')).toHaveText(['sec_8k', 'sec_form4', 'coingecko', 'google_news', 'yfinance_bars'])
  await expect(rows.nth(0)).toContainText('open · 3 fails in a row')
  await expect(rows.nth(0)).toContainText('never') // it has never answered
  await expect(rows.nth(3)).toContainText('from cache')
  await expect(rows.nth(4)).toContainText('3 min 5 s')
  await expect(rows.nth(4)).toContainText('472,845')

  await rows.nth(1).getByRole('button', { name: 'partial' }).click()
  await expect(page.locator('#err-sec_form4')).toHaveText('This run: PartialFetch: stopped after 41 of 300 symbols')
  await page.getByRole('tab', { name: 'Problems 2' }).click()
  await expect(rows.locator('td:first-child .sym')).toHaveText(['sec_8k', 'sec_form4'])
  await page.getByRole('tab', { name: 'Core 3' }).click()
  await expect(rows.locator('td:first-child .sym')).toHaveText(['coingecko', 'google_news', 'yfinance_bars'])
})

test("the status bar's sources pill opens Source health, which waits for the first run", async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('link', { name: /sources$/ })).toHaveCount(0) // no run, no pill
  await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
  await page.reload()
  await page.getByRole('link', { name: '30/33 sources' }).click()
  await expect(page).toHaveURL(/\/sources$/)
  await expect(page.getByText('No sources yet. The next run or daily check lists them here.')).toBeVisible()
})
