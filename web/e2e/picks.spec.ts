import { expect, test, type Page } from '@playwright/test'
import {
  resetData,
  seedFeatures,
  seedModel,
  seedOutcome,
  seedPick,
  seedPortfolio,
  seedPrediction,
  seedRun,
  seedVerdict,
} from './db'

test.beforeEach(async () => {
  await resetData()
  await seedPortfolio()
})

const hourAgo = () => new Date(Date.now() - 3_600_000).toISOString()

/** A published run: the US gate passes with an AAPL Position pick and an MSFT Swing pick; TSX's fails. */
async function seedPicksRun() {
  const runId = await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: hourAgo() })
  await seedModel('stock_us', { picks_enabled: true })
  await seedModel('stock_tsx', { picks_enabled: false, picks_reason: 'only 12 backtest picks (needs 30)' })
  await seedPrediction(runId, 'AAPL', 63, { q10: -0.068, q50: 0.049, q90: 0.16, p: 0.62 })
  await seedPrediction(runId, 'MSFT', 10, { q10: -0.031, q50: 0.024, q90: 0.079, p: 0.6 })
  const factors = [
    { feature: 'ex_bench_63', contribution: 0.02 },
    { feature: 'rev_growth', contribution: 0.01 },
    { feature: 'vol_20', contribution: -0.005 },
  ]
  await seedFeatures(runId, 'AAPL', 'stock', {
    ex_bench_63: 0.098,
    rev_growth: 0.14,
    vol_20: 0.31,
    advice: { horizon: 63, top_factors: factors, catalysts: [], round_trip_cost: 0.031 },
  })
  const pickId = await seedPick(runId, {
    symbol: 'AAPL',
    market: 'US',
    style: 'position',
    horizon: 63,
    rank: 1,
    exitBy: '2027-01-19',
    entry: 229.5,
    stop: 205.1,
    riskLevel: 'medium',
    maxPct: 3,
    topFactors: factors,
    catalysts: [{ type: 'earnings', date: '2026-10-28' }],
  })
  await seedPick(runId, {
    symbol: 'MSFT',
    market: 'US',
    style: 'swing',
    horizon: 10,
    rank: 1,
    exitBy: '2026-11-10',
    entry: 410,
    stop: 380.2,
    riskLevel: 'low',
    maxPct: 5,
  })
  await seedVerdict(runId, {
    symbol: 'TD.TO',
    assetType: 'stock',
    verdict: 'hold',
    reasons: ["doesn't qualify as a buy", 'P(beat XIU.TO) 0.54 is under 0.58 at every horizon'],
    details: { market_picks_enabled: false },
  })
  return { runId, pickId }
}

const usCard = (page: Page, symbol: string) => page.locator('[data-panel="us"] article.pick', { hasText: symbol })

test('picks page before any run says picks appear once the model runs', async ({ page }) => {
  await page.goto('/picks')
  await expect(page.getByRole('heading', { name: "Today's Picks", level: 1 })).toBeVisible()
  await expect(page.getByText('Picks appear once the model runs')).toBeVisible()
  await expect(page.locator('article.pick')).toHaveCount(0)
})

test('a US pick card shows its range, odds, hold, stop, size and cost', async ({ page }) => {
  await seedPicksRun()
  await page.goto('/picks')
  await expect(page.getByText(/^From the \d\d:\d\d pre-close run · at most 10 Swing and 10 Position picks per market, 3 per sector$/)).toBeVisible()
  const card = usCard(page, 'AAPL')
  await expect(card).toContainText('#1')
  await expect(card).toContainText('Apple Inc.')
  await expect(card).toContainText('Likely 63-day return relative to SPY')
  await expect(card.getByRole('img', { name: /^Likely range relative to SPY: q10 −6\.8%, median \+4\.9%, q90 \+16\.0%$/ })).toBeVisible()
  await expect(card.locator('.pick-facts')).toContainText('Beats SPY62%')
  await expect(card).toContainText('~3 months · exit by Jan 19')
  await expect(card).toContainText('US$205.10')
  await expect(card.locator('.pick-facts')).toContainText(/Max size3% · C\$[\d,]+/)
  await expect(card).toContainText('3.1% round trip USD conversion 1.5% each way + spread')
  await expect(card.locator('.pick-why li')).toHaveText([
    'Return vs SPY over 63 days +9.8%',
    'Revenue growth, year over year +14.0%',
    '20-day volatility, annualised 31.0%',
  ])
  await expect(card).toContainText('Earnings Oct 28, inside the hold')
  await expect(card).toContainText('A long hold keeps TFSA trades low')

  const us = page.locator('[data-panel="us"]')
  await expect(us.locator('[data-style="swing"] .paper-banner')).toHaveText(
    'Not yet validated. 0 of 100 Swing picks graded live; treat these as a paper trial.',
  )
  await expect(us.locator('[data-style="position"] .paper-banner')).toHaveText(
    'Validated on backtest only. 0 of 50 Position picks graded live.',
  )
  // a pick without a stored cost or factors still shows what it has
  await expect(usCard(page, 'MSFT')).toContainText('No catalysts inside the hold')
  await expect(usCard(page, 'MSFT')).not.toContainText('round trip')
})

test('a disabled market shows its gate reason and still lists verdicts', async ({ page }) => {
  const { runId } = await seedPicksRun()
  // written before a retrain turned the gate off: the page goes by the active model's gate
  await seedPick(runId, {
    symbol: 'RY.TO',
    market: 'TSX',
    style: 'swing',
    horizon: 10,
    rank: 1,
    exitBy: '2026-11-10',
    entry: 180,
    stop: 170,
    riskLevel: 'low',
    maxPct: 5,
  })
  await page.goto('/picks')
  await page.getByRole('tab', { name: 'TSX' }).click()
  const tsx = page.locator('[data-panel="tsx"]')
  await expect(tsx.getByText('No TSX picks today: model check failed')).toBeVisible()
  await expect(tsx).toContainText('only 12 backtest picks (needs 30)')
  await expect(tsx).toContainText('Watchlist verdicts and holding actions still run.')
  await expect(tsx.locator('article.pick')).toHaveCount(0)
  const row = tsx.locator('.verdict', { hasText: 'TD.TO' })
  await expect(row.locator('.chip')).toHaveText('Hold')
  await expect(row).toContainText('picks off for TSX this run')
})

test('a market with a passing gate and no picks says nothing cleared the bar', async ({ page }) => {
  await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: hourAgo() })
  await seedModel('stock_us', { picks_enabled: true })
  await page.goto('/picks')
  await expect(page.locator('[data-panel="us"]').getByText('No US picks today', { exact: true })).toBeVisible()
  await expect(page.locator('[data-panel="us"]')).toContainText('Nothing cleared the bar this run')
  await page.getByRole('tab', { name: 'TSX' }).click()
  await expect(page.locator('[data-panel="tsx"]').getByText('No TSX picks yet')).toBeVisible()
  await expect(page.locator('[data-panel="tsx"]')).toContainText('TSX has no trained model yet.')
})

test('an exited pick shows in the Exit early card', async ({ page }) => {
  const earlier = await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: new Date(Date.now() - 3 * 86_400_000).toISOString() })
  const exited = await seedPick(earlier, {
    symbol: 'NVDA',
    market: 'US',
    style: 'swing',
    horizon: 10,
    rank: 2,
    exitBy: '2026-11-03',
    entry: 180,
    stop: 166,
    riskLevel: 'high',
    maxPct: 1.5,
    status: 'exited_early',
  })
  await seedPicksRun()
  await seedOutcome(exited, { exitPrice: 174.24, exitReason: 'exit_early', ret: -0.032, benchRet: 0.004, beat: false })
  await page.goto('/picks')
  const card = page.locator('#exit-early-us')
  await expect(card.getByRole('heading', { name: 'Exit early' })).toBeVisible()
  await expect(card.locator('.verdict')).toHaveCount(1)
  await expect(card).toContainText('NVDA')
  await expect(card).toContainText('Swing · 10d')
  await expect(card).toContainText('P fell to 0.42 or below · exited at US$174.24 · −3.2%')
  // none for TSX, so its card is hidden
  await page.getByRole('tab', { name: 'TSX' }).click()
  await expect(page.locator('#exit-early-tsx')).toHaveCount(0)
})

test('the nav links to Picks', async ({ page }) => {
  await page.goto('/')
  const sidebar = page.getByRole('complementary', { name: 'Main' })
  await expect(sidebar.getByRole('link')).toContainText(['Portfolio', 'Picks', 'Watchlist', 'Invest', 'Sources', 'Settings'])
  await sidebar.getByRole('link', { name: 'Picks' }).click()
  await expect(page.getByRole('heading', { name: "Today's Picks", level: 1 })).toBeVisible()
  await expect(sidebar.getByRole('link', { name: 'Picks' })).toHaveAttribute('aria-current', 'page')
})

test.describe('on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('Picks is a bottom tab, and the page is no wider than the screen', async ({ page }) => {
    await seedPicksRun()
    await page.goto('/')
    const tabs = page.getByRole('navigation', { name: 'Main' }).last()
    await tabs.getByRole('link', { name: 'Picks' }).click()
    await expect(page.getByRole('heading', { name: "Today's Picks", level: 1 })).toBeVisible()
    await expect(tabs.getByRole('link', { name: 'Picks' })).toHaveAttribute('aria-current', 'page')
    await expect(usCard(page, 'AAPL')).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow).toBeLessThanOrEqual(0)  })
})
