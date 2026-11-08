import { expect, test, type Page } from '@playwright/test'
import { daysAgo, resetData, seedCloses, seedCoins, seedFeatures, seedPrediction, seedRun, seedSymbols, sql, weekdays } from './db'

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
    { symbol: 'AAPL', horizon_days: 10, q10: -0.05, q50: 0.04, q90: 0.09, p_beat: 0.53, benchmark: 'SPY' },
    { symbol: 'XOM', horizon_days: 21, q10: -0.06, q50: 0.035, q90: 0.1, p_beat: 0.52, benchmark: 'SPY' },
    { symbol: 'JNJ', horizon_days: 40, q10: -0.05, q50: 0.033, q90: 0.08, p_beat: 0.51, benchmark: 'SPY' },
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
  await expect(page.getByLabel('Invest in')).toHaveValue('stocks')
  await expect(page.getByLabel('Crypto share')).toHaveCount(0)
  await expect(page.getByLabel('How long to hold')).toHaveValue('any')
  await expect(page.getByRole('button', { name: 'Split it' })).toBeVisible()
  await expect(page.locator('#invest-lines')).toHaveCount(0)
})

test('an amount is split over five stocks, under the Not validated warning', async ({ page }) => {
  await seedForecasts()
  await page.goto('/invest')
  await page.getByLabel('Amount (C$)').fill('1,000')
  await page.getByRole('button', { name: 'Split it' }).click()
  await expect(page).toHaveURL(/\/invest\?amount=1%2C000&asset=stocks&stocks=5&hold=any$/)

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
  await expect(ry).toContainText('Likely −2.0% to +8.0% relative to XIU.TO over 21 trading days · median +3.0%')
  await expect(ry).toContainText('round-trip cost +0.1%')
  await expect(ry.getByRole('link', { name: 'RY.TO' })).toHaveAttribute('href', '/ticker/RY.TO')
  await expect(stockRows(page).filter({ hasText: 'AAPL' })).toContainText('(incl. currency fee)')

  await expect(page.locator('#invest-lines .invest-row.coin')).toHaveCount(0)

  const amounts = await page.locator('#invest-lines .i-amount b').allTextContents()
  expect(amounts.reduce((sum, text) => sum + Number(text.replace(/[^\d.]/g, '')), 0)).toBe(1000)
  const foot = page.locator('.invest-foot')
  await expect(foot).toContainText('Total C$1,000')
  await expect(foot).toContainText('Not financial or tax advice. Forecasts are probabilistic and can be wrong.')
})

test('crypto is ranked like stocks, and a coin expected to lag is left out', async ({ page }) => {
  await seedForecasts()
  const [{ id }] = await sql`select id from runs order by id desc limit 1`
  await seedCoins([
    { symbol: 'ETH', name: 'Ethereum', marketCap: 1 },
    { symbol: 'SOL', name: 'Solana', marketCap: 1 },
    { symbol: 'DOGE', name: 'Dogecoin', marketCap: 1 },
  ])
  await seedPrediction(id, 'ETH', 14, { q10: 0.03, q50: 0.08, q90: 0.13, p: 0.7 }, 'crypto')
  await seedPrediction(id, 'SOL', 14, { q10: -0.04, q50: 0.06, q90: 0.16, p: 0.62 }, 'crypto')
  await seedPrediction(id, 'DOGE', 14, { q10: -0.1, q50: -0.02, q90: 0.04, p: 0.4 }, 'crypto')
  for (const symbol of ['ETH', 'SOL', 'DOGE']) {
    await seedFeatures(id, symbol, 'crypto', { vol_60: 0.3, log_adv20: 17, jump_5d: 0, price_cad: symbol === 'ETH' ? 4000 : 200 })
  }
  await page.goto('/invest?amount=1000&asset=crypto&stocks=5&hold=any')
  const coins = page.locator('#invest-lines .invest-row.coin')
  await expect(coins).toHaveCount(2)
  await expect(page.locator('#invest-lines .invest-row.stock')).toHaveCount(0)
  await expect(coins.nth(0)).toContainText('Ethereum · Crypto')
  await expect(coins.nth(0)).toContainText('Likely +3.0% to +13.0% relative to BTC over 14 days · median +8.0%')
  await expect(coins.nth(0)).toContainText('≈ 0.125 ETH')
  await expect(coins.nth(0)).toContainText('(incl. crypto fee)')
  await expect(coins.nth(0).getByRole('link', { name: 'ETH' })).toHaveAttribute('href', '/ticker/ETH?asset=crypto')
  await expect(coins.nth(1)).toContainText('SOL')
  await expect(page.getByText(/With two coins the 40% cap/)).toBeVisible()
  const amounts = await page.locator('#invest-lines .i-amount b').allTextContents()
  expect(amounts.reduce((sum, text) => sum + Number(text.replace(/[^\d.]/g, '')), 0)).toBe(1000)
  await expect(coins.nth(0).locator('.order-guide')).toContainText(/Limit buy C\$500 of it at/)
  await expect(page.getByText(/recurring buy/)).toHaveCount(0)

  await page.goto('/invest?amount=1000&asset=crypto&stocks=5&hold=30')
  await expect(page.locator('#invest-uninvested')).toContainText("no coin passes the picks' rule today")
})

test('each Invest line says how to place it', async ({ page }) => {
  await seedForecasts()
  await seedCloses('RY.TO', 'stock', 'CAD', weekdays(daysAgo(10)), 50, 0)
  await seedCloses('SHOP.TO', 'stock', 'CAD', weekdays(daysAgo(10)), 80, 0) // priced, but with no daily range
  await sql`update features_live set features = features || '{"atr_14_pct": 0.02}'::jsonb where symbol = 'RY.TO'`
  await page.goto('/invest?amount=1000&asset=stocks&stocks=5')
  const ry = stockRows(page).filter({ hasText: 'RY.TO' }).locator('.order-guide')
  await expect(ry).toContainText('How to place it')
  await expect(ry).toContainText(/Limit buy \d+ sh at C\$50\.25 · (Day order|set it to expire at the end of the next trading day)/)
  await expect(ry.locator('.og-step', { hasText: 'stop-limit' })).toHaveCount(0) // the Invest page isn't a pick, so no separate stop order
  // the bracket: the top of its 21-day range (C$50 × 1.08), and the picks' position stop (3 ranges under)
  await expect(ry).toContainText(
    /Or as one bracket order: limit buy \d+ sh at C\$50\.25 · (Day order|set it to expire at the end of the next trading day), take profit C\$54\.00 \(\+7%\), stop loss C\$47\.00 \(−6%\)/,
  )
  // a priced stock without a daily range gets its buy, but no bracket
  const shop = stockRows(page).filter({ hasText: 'SHOP.TO' }).locator('.order-guide')
  await expect(shop).toContainText('Limit buy')
  await expect(shop).not.toContainText('bracket')
  await expect(page.getByText("Order guidance is a rule of thumb for Wealthsimple's order types, not a price forecast.")).toHaveCount(1)
})

test('one stock puts all of the money in the top-ranked one', async ({ page }) => {
  await seedForecasts()
  await page.goto('/invest')
  await expect(page.getByLabel('Number of stocks')).toHaveValue('5')
  await page.getByLabel('Amount (C$)').fill('500')
  await page.getByLabel('Number of stocks').selectOption('1')
  await page.getByRole('button', { name: 'Split it' }).click()
  await expect(page).toHaveURL(/\/invest\?amount=500&asset=stocks&stocks=1&hold=any$/)

  await expect(stockRows(page)).toHaveCount(1)
  await expect(stockRows(page).first()).toContainText('RY.TO') // the best expected return per unit of range
  await expect(stockRows(page).first().locator('.i-amount b')).toHaveText('C$500')
  await expect(page.locator('#invest-concentrated')).toHaveText('All in one stock: no spread of risk.')
  await expect(page.locator('#invest-lines .invest-row.coin')).toHaveCount(0)
})

/** AAPL is best over 10 days; MSFT is best over 63. */
async function seedHoldForecasts() {
  await seedSymbols([
    { symbol: 'AAPL', market: 'US', name: 'Apple Inc.' },
    { symbol: 'MSFT', market: 'US', name: 'Microsoft Corporation' },
  ])
  await sql`update symbols set sector = 'Technology' where symbol in ('AAPL', 'MSFT')`
  const runId = await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
  const rows = [
    { symbol: 'AAPL', horizon_days: 10, q10: -0.02, q50: 0.09, q90: 0.16, p_beat: 0.7, benchmark: 'SPY' },
    { symbol: 'AAPL', horizon_days: 63, q10: -0.04, q50: 0.04, q90: 0.1, p_beat: 0.6, benchmark: 'SPY' },
    { symbol: 'MSFT', horizon_days: 10, q10: -0.03, q50: 0.01, q90: 0.05, p_beat: 0.6, benchmark: 'SPY' },
    { symbol: 'MSFT', horizon_days: 63, q10: -0.03, q50: 0.07, q90: 0.13, p_beat: 0.62, benchmark: 'SPY' },
  ].map((r) => ({ ...r, run_id: runId, asset_type: 'stock', model_version: 'e2e' }))
  await sql`insert into predictions ${sql(rows)}`
  for (const symbol of ['AAPL', 'MSFT']) await seedFeatures(runId, symbol, 'stock', { vol_60: 0.3, log_adv20: 17, jump_5d: 0 })
}

test('holding for 3 months ranks on the 3-month forecast', async ({ page }) => {
  await seedHoldForecasts()
  await page.goto('/invest?amount=1000&asset=stocks&stocks=5&hold=63')
  await expect(stockRows(page).first()).toContainText('MSFT')
  await expect(stockRows(page).first()).toContainText('over 63 trading days')
  await expect(stockRows(page).nth(1)).toContainText('AAPL')
  await expect(stockRows(page).nth(1)).toContainText('over 63 trading days')
})

test('a bad hold value shows its error', async ({ page }) => {
  await seedForecasts()
  await page.goto('/invest?amount=1000&hold=forever')
  await expect(page.getByText('Choose how long to hold.')).toBeVisible()
  await expect(page.locator('#invest-lines')).toHaveCount(0)
})

test('the TFSA note shows for a short hold and not for 3 months', async ({ page }) => {
  await seedForecasts()
  const note =
    'Frequent short-term trades in a TFSA can be treated as a business, which makes the gains taxable; a longer hold avoids that (not tax advice).'
  await page.goto('/invest?amount=1000&asset=stocks&stocks=5&hold=21')
  await expect(page.getByRole('heading', { name: /Where C\$1,000 would go/ })).toBeVisible()
  await expect(page.getByText(note)).toBeVisible()
  await page.goto('/invest?amount=1000&asset=stocks&stocks=5&hold=63')
  await expect(page.getByText(note)).toHaveCount(0)
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
    await page.goto('/invest?amount=1000&asset=stocks')
    await expect(stockRows(page)).toHaveCount(5)
    await expect(page.getByRole('navigation', { name: 'Main' }).last().getByRole('link', { name: 'Invest' })).toHaveAttribute('aria-current', 'page')
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow).toBeLessThanOrEqual(0)
  })
})
