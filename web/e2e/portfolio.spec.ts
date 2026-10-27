import { expect, test, type Page } from '@playwright/test'
import { addDays, shortDay } from '../lib/dates'
import { daysAgo, resetData, seedCloses, seedFx, seedHoldingAction, seedLot, seedPortfolio, seedRun, seedSymbols, today, weekdays } from './db'

test.beforeEach(resetData)

const holdings = (page: Page) => page.locator('#holdings tbody tr')

test('an empty portfolio invites the first buy', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'My Portfolio' })).toBeVisible()
  await expect(page.getByText('No holdings yet. Add your first buy to start.')).toBeVisible()
  await expect(page.getByText('No actions yet')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sell' })).toHaveCount(0)
})

test('holdings are valued in CAD, charted against both benchmarks, and warned about', async ({ page }) => {
  await seedPortfolio()
  await page.goto('/')

  await expect(page.getByText('Crypto and TFSA accounts · values in CAD at the latest Bank of Canada rate (1.4000)')).toBeVisible()
  await expect(holdings(page)).toHaveCount(3)
  const ry = holdings(page).filter({ hasText: 'RY.TO' })
  await expect(ry).toContainText('Royal Bank of Canada')
  await expect(ry).toContainText('TSX')
  const eth = holdings(page).filter({ hasText: 'ETH' })
  await expect(eth).toContainText(/Loss window to/)
  await expect(eth).toContainText(/Taxable: est\./)

  await expect(page.getByRole('img', { name: 'Portfolio return against XIU.TO and SPY in CAD' })).toBeVisible()
  await expect(page.getByText(/since the first buy, /)).toBeVisible()
  await page.getByRole('tab', { name: '1M' }).click()
  await expect(page.getByText('over the last month')).toBeVisible()
  await expect(page.getByRole('tab', { name: '1M' })).toHaveAttribute('aria-selected', 'true')

  await expect(page.getByText('ETH: superficial-loss window')).toBeVisible()
  const breakdown = page.getByRole('heading', { name: 'Breakdown' }).locator('..')
  await expect(breakdown).toContainText('By market')
  await expect(breakdown).toContainText('TFSA')
})

test('the actions of the latest run fill the Actions card and the holdings table', async ({ page }) => {
  const days = weekdays(daysAgo(30))
  await seedSymbols([
    { symbol: 'SHOP.TO', market: 'TSX', name: 'Shopify Inc.' },
    { symbol: 'MSFT', market: 'US', name: 'Microsoft Corporation' },
    { symbol: 'AAPL', market: 'US', name: 'Apple Inc.' },
  ])
  await seedFx(days, 1.4)
  await seedCloses('SHOP.TO', 'stock', 'CAD', days, 160, -0.5)
  await seedCloses('MSFT', 'stock', 'USD', days, 400, 0.5)
  await seedCloses('AAPL', 'stock', 'USD', days, 200, 0.5)
  await seedLot({ account: 'tfsa', symbol: 'SHOP.TO', asset_type: 'stock', qty: 10, price: 160, currency: 'CAD', bought_at: days[0] })
  await seedLot({ account: 'tfsa', symbol: 'MSFT', asset_type: 'stock', qty: 5, price: 400, currency: 'USD', fx_rate_cad: 1.4, bought_at: days[0] })
  await seedLot({ account: 'tfsa', symbol: 'AAPL', asset_type: 'stock', qty: 5, price: 200, currency: 'USD', fx_rate_cad: 1.4, bought_at: days[0] })
  const runId = await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: new Date().toISOString() })
  await seedHoldingAction(runId, {
    account: 'tfsa',
    symbol: 'SHOP.TO',
    asset_type: 'stock',
    action: 'sell',
    reasons: ['closed at 141.00, under its trailing stop 146.10'],
    trailing_stop: 146.1,
    q10: -0.098,
    q50: -0.026,
    q90: 0.041,
    horizon_days: 10,
    risk_level: 'high',
  })
  await seedHoldingAction(runId, {
    account: 'tfsa',
    symbol: 'MSFT',
    asset_type: 'stock',
    action: 'hold',
    reasons: ['Hold.'],
    warnings: ['Above its max size'],
    trailing_stop: 398.5,
    q10: -0.071,
    q50: 0.014,
    q90: 0.096,
    horizon_days: 40,
    exit_by: addDays(today(), 40),
    risk_level: 'medium',
  })
  await seedHoldingAction(runId, {
    account: 'tfsa',
    symbol: 'AAPL',
    asset_type: 'stock',
    action: 'hold',
    review: true,
    reasons: ['no rule fired', 'earnings on Oct 30'],
    trailing_stop: 209.8,
    q10: -0.048,
    q50: 0.003,
    q90: 0.052,
    horizon_days: 10,
    exit_by: addDays(today(), 10),
    risk_level: 'medium',
  })
  await page.goto('/')

  const actions = page.getByRole('heading', { name: 'Actions' }).locator('../..')
  const sell = actions.locator('.action-card.sell')
  await expect(sell).toHaveCount(1)
  await expect(sell).toContainText('SHOP.TO')
  await expect(sell).toContainText('Closed at 141.00, under its trailing stop 146.10')
  await expect(actions).toContainText(`Sell → Trim → Review → Add → Hold · as of ${shortDay(today())}`)
  const review = actions.locator('.action-card.review')
  await expect(review).toHaveCount(1)
  await expect(review).toContainText('AAPL')
  await expect(review).toContainText('TFSA · Hold')
  await expect(review).toContainText('Earnings on Oct 30')
  await expect(review).not.toContainText('rule fired')
  const toggle = page.getByRole('button', { name: /1 holding · MSFT/ })
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect(page.locator('#hold-list')).toContainText(/hold ~40 days · exit by/)

  const shop = holdings(page).filter({ hasText: 'SHOP.TO' })
  await expect(shop.locator('.chip.sell')).toHaveText('Sell')
  await expect(shop).toContainText('C$146.10')
  await expect(shop).toContainText('High')
  const msft = holdings(page).filter({ hasText: 'MSFT' })
  await expect(msft.locator('.chip.hold')).toHaveText('Hold')
  await expect(msft).toContainText('US$398.50')
  await expect(msft).toContainText('Above its max size')
  const aapl = holdings(page).filter({ hasText: 'AAPL' })
  await expect(aapl.locator('.chip.hold')).toHaveText('Hold')
  await expect(aapl.locator('.chip.review')).toHaveText('Review')
  await expect(page.getByText('appear once the model runs')).toHaveCount(0)
})
