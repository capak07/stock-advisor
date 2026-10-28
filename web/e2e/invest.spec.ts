import { expect, test, type Page } from '@playwright/test'
import { resetData, seedFeatures, seedRun, seedSymbols, sql } from './db'

test.beforeEach(resetData)

const stockRows = (page: Page) => page.locator('#invest-lines .invest-row.stock')

/** Two TSX stocks that pass the bar, three with a positive but unvalidated forecast, one expected to lag. */
async function seedForecasts() {
  await seedSymbols([
    { symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' },
    { symbol: 'SHOP.TO', market: 'TSX', name: 'Shopify Inc.' },
    { symbol: 'AAPL', market: 'US', name: 'Apple Inc.' },
    { symbol: 'XOM', market: 'US', name: 'Exxon Mobil Corporation' },
    { symbol: 'JNJ', market: 'US', name: 'Johnson & Johnson' },
    { symbol: 'PFE', market: 'US', name: 'Pfizer Inc.' },
  ])
  const sectors: Record<string, string> = {
    'RY.TO': 'Financial Services',
    'SHOP.TO': 'Technology',
    AAPL: 'Technology',
    XOM: 'Energy',
    JNJ: 'Healthcare',
    PFE: 'Healthcare',
  }
  for (const [symbol, sector] of Object.entries(sectors)) await sql`update symbols set sector = ${sector} where symbol = ${symbol}`

  const runId = await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
  const rows = [
    { symbol: 'RY.TO', horizon_days: 21, q10: -0.02, q50: 0.03, q90: 0.08, p_beat: 0.62, benchmark: 'XIU.TO' },
    { symbol: 'SHOP.TO', horizon_days: 21, q10: -0.04, q50: 0.03, q90: 0.1, p_beat: 0.62, benchmark: 'XIU.TO' },
    { symbol: 'AAPL', horizon_days: 10, q10: -0.05, q50: 0.02, q90: 0.07, p_beat: 0.53, benchmark: 'SPY' },
    { symbol: 'XOM', horizon_days: 21, q10: -0.06, q50: 0.015, q90: 0.08, p_beat: 0.52, benchmark: 'SPY' },
    { symbol: 'JNJ', horizon_days: 40, q10: -0.05, q50: 0.01, q90: 0.06, p_beat: 0.51, benchmark: 'SPY' },
    { symbol: 'PFE', horizon_days: 10, q10: -0.08, q50: -0.01, q90: 0.04, p_beat: 0.4, benchmark: 'SPY' },
    { symbol: 'PFE', horizon_days: 21, q10: -0.1, q50: -0.02, q90: 0.05, p_beat: 0.38, benchmark: 'SPY' },
  ].map((r) => ({ ...r, run_id: runId, asset_type: 'stock', model_version: 'e2e' }))
  await sql`insert into predictions ${sql(rows)}`
  for (const symbol of Object.keys(sectors)) await seedFeatures(runId, symbol, 'stock', { vol_60: 0.3, log_adv20: 17, jump_5d: 0 })
}

test('Invest is in the navigation and starts with the form only', async ({ page }) => {
  await seedForecasts()
  await page.goto('/')
  await page.getByRole('complementary', { name: 'Main' }).getByRole('link', { name: 'Invest' }).click()
  await expect(page).toHaveURL(/\/invest$/)
  await expect(page.getByRole('heading', { name: 'Invest', level: 1 })).toBeVisible()
  await expect(page.getByLabel('Amount (C$)')).toBeVisible()
  await expect(page.getByLabel('Crypto share')).toHaveValue('10')
  await expect(page.getByRole('button', { name: 'Split it' })).toBeVisible()
  await expect(page.locator('#invest-lines')).toHaveCount(0)
})

test('an amount is split over five stocks and BTC, under the Not validated warning', async ({ page }) => {
  await seedForecasts()
  await page.goto('/invest')
  await page.getByLabel('Amount (C$)').fill('1,000')
  await page.getByRole('button', { name: 'Split it' }).click()
  await expect(page).toHaveURL(/\/invest\?amount=1%2C000&crypto=10$/)

  await expect(page.getByText(/^From the Pre-open run of .+ · returns are vs SPY \(US\) or XIU\.TO \(TSX\), not plain gains$/)).toBeVisible()
  // two of the five pass, so the warning points at their chips
  await expect(page.getByRole('alert').filter({ hasText: 'Not validated: only the stocks marked “passes the bar” meet' })).toBeVisible()
  await expect(stockRows(page)).toHaveCount(5)
  await expect(stockRows(page).filter({ hasText: 'PFE' })).toHaveCount(0)

  // qualifying stocks come first, each marked as passing the bar
  await expect(stockRows(page).nth(0).locator('.chip.buy')).toHaveText('passes the bar')
  await expect(stockRows(page).nth(1).locator('.chip.buy')).toHaveText('passes the bar')
  await expect(page.locator('#invest-lines .chip.buy')).toHaveCount(2)
  const ry = stockRows(page).filter({ hasText: 'RY.TO' })
  await expect(ry).toContainText('Royal Bank of Canada · TSX · Financial Services')
  await expect(ry).toContainText('+3.0% (likely −2.0% to +8.0%) over 21 trading days vs XIU.TO · P(beat) 62%')
  await expect(ry).toContainText('round-trip cost +0.1%')
  await expect(ry.getByRole('link', { name: 'RY.TO' })).toHaveAttribute('href', '/ticker/RY.TO')
  await expect(stockRows(page).filter({ hasText: 'AAPL' })).toContainText('(incl. currency fee)')

  const btc = page.locator('#invest-lines .invest-row.crypto')
  await expect(btc).toContainText('C$100')
  await expect(btc).toContainText('Bitcoin · crypto · no forecast (no crypto model yet)')
  await expect(btc).toContainText(/add BTC to your watchlist to see its price/i)

  const amounts = await page.locator('#invest-lines .i-amount b').allTextContents()
  expect(amounts.reduce((sum, text) => sum + Number(text.replace(/[^\d.]/g, '')), 0)).toBe(1000)
  const foot = page.locator('.invest-foot')
  await expect(foot).toContainText('Total C$1,000')
  await expect(foot).toContainText('Not financial or tax advice. Forecasts are probabilistic and can be wrong.')
})

test('a bad amount shows a field error', async ({ page }) => {
  await seedForecasts()
  await page.goto('/invest?amount=abc')
  await expect(page.getByText('Enter an amount from C$1 to C$10,000,000.')).toBeVisible()
  await expect(page.getByLabel('Amount (C$)')).toHaveValue('abc')
  await expect(page.locator('#invest-lines')).toHaveCount(0)
})

test('before any run forecasts, the page says so', async ({ page }) => {
  await page.goto('/invest?amount=1000')
  await expect(page.getByText('No forecasts yet. They appear after the next run.')).toBeVisible()
  await expect(page.locator('#invest-lines')).toHaveCount(0)
})

test.describe('on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('the split stacks and is no wider than the screen', async ({ page }) => {
    await seedForecasts()
    await sql`update symbols set name = 'Royal Bank of Canada Global Diversified Holdings and Trust Incorporated' where symbol = 'RY.TO'`
    await page.goto('/invest?amount=1000&crypto=10')
    await expect(stockRows(page)).toHaveCount(5)
    await expect(page.getByRole('navigation', { name: 'Main' }).last().getByRole('link', { name: 'Invest' })).toHaveAttribute('aria-current', 'page')
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow).toBeLessThanOrEqual(0)
  })
})
