import { expect, test, type Page } from '@playwright/test'
import { addDays, shortDay } from '../lib/dates'
import {
  daysAgo,
  resetData,
  seedCloses,
  seedFeatures,
  seedFx,
  seedHoldingAction,
  seedLot,
  seedPortfolio,
  seedRun,
  seedSymbols,
  today,
  weekdays,
} from './db'

test.beforeEach(resetData)

const holdings = (page: Page) => page.locator('#holdings tbody tr')

test('an empty portfolio invites the first buy', async ({ page }) => {
  await page.goto('/portfolio')
  await expect(page.getByRole('heading', { name: 'My Portfolio' })).toBeVisible()
  await expect(page.getByText('No holdings yet. Add your first buy to start.')).toBeVisible()
  await expect(page.getByText('No actions yet')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sell' })).toHaveCount(0)
})

test('holdings are valued in CAD, charted against both benchmarks, and warned about', async ({ page }) => {
  await seedPortfolio()
  await page.goto('/portfolio')

  await expect(page.getByText('Crypto and TFSA accounts · values in CAD at the latest Bank of Canada rate (1.4000)')).toBeVisible()
  await expect(holdings(page)).toHaveCount(3)
  const ry = holdings(page).filter({ hasText: 'RY.TO' })
  await expect(ry).toContainText('Royal Bank of Canada')
  await expect(ry).toContainText('TSX')
  const eth = holdings(page).filter({ hasText: 'ETH' })
  await expect(eth).toContainText(/Loss window to/)
  await expect(eth).toContainText(/Taxable: est\./)

  const chart = page.getByRole('img', { name: 'Portfolio return against XIU.TO and SPY in CAD' })
  await expect(chart).toBeVisible()
  // the three lines draw in (.draw in ledger.css), each from its own length measured before the first paint
  await expect(chart).toHaveClass(/draw/)
  const lengths = await chart
    .locator('path.line')
    .evaluateAll((paths) => paths.map((p) => Number((p as SVGPathElement).style.getPropertyValue('--len'))))
  expect(lengths).toHaveLength(3)
  for (const len of lengths) expect(len).toBeGreaterThan(0)
  await expect(page.getByText(/since the first buy, /)).toBeVisible()
  await page.getByRole('tab', { name: '1D' }).click()
  await expect(page.getByText('over the last day')).toBeVisible()
  await page.getByRole('tab', { name: '1W' }).click()
  await expect(page.getByText('over the last week')).toBeVisible()
  await page.getByRole('tab', { name: '1M' }).click()
  await expect(page.getByText('over the last month')).toBeVisible()
  await expect(page.getByRole('tab', { name: '1M' })).toHaveAttribute('aria-selected', 'true')

  await expect(page.getByText('ETH: superficial-loss window')).toBeVisible()
  const breakdown = page.getByRole('heading', { name: 'Breakdown' }).locator('..')
  await expect(breakdown).toContainText('By market')
  await expect(breakdown).toContainText('TFSA')
})

test.describe('on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('the holdings become compact rows that never widen the page', async ({ page }) => {
    await seedPortfolio()
    await page.goto('/portfolio')
    await expect(holdings(page)).toHaveCount(3)
    await expect(page.locator('#holdings thead')).toBeHidden()
    const widths = await page.evaluate(() => ({
      page: document.documentElement.scrollWidth,
      screen: window.innerWidth,
      table: document.querySelector('#holdings')!.getBoundingClientRect().right,
    }))
    expect(widths.page, 'page scrolls sideways').toBeLessThanOrEqual(widths.screen)
    expect(widths.table, 'holdings run past the screen').toBeLessThanOrEqual(widths.screen)
  })
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
    review: true,
    reasons: ['closed at 141.00, under its trailing stop 146.10', 'earnings on Oct 28'],
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
  await page.goto('/portfolio')

  const actions = page.getByRole('heading', { name: 'Actions' }).locator('../..')
  const sell = actions.locator('.action-card.sell')
  await expect(sell).toHaveCount(1)
  await expect(sell).toContainText('SHOP.TO')
  await expect(sell).toContainText('Closed at 141.00, under its trailing stop 146.10')
  // a Sell asked to review keeps its group and shows both chips
  await expect(sell.locator('.chip.sell')).toHaveText('Sell')
  await expect(sell.locator('.chip.review')).toHaveText('Review')
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
  await expect(shop.locator('.chip.review')).toHaveText('Review')
  const msft = holdings(page).filter({ hasText: 'MSFT' })
  await expect(msft.locator('.chip.hold')).toHaveText('Hold')
  await expect(msft).toContainText('US$398.50')
  await expect(msft).toContainText('Above its max size')
  const aapl = holdings(page).filter({ hasText: 'AAPL' })
  await expect(aapl.locator('.chip.hold')).toHaveText('Hold')
  await expect(aapl.locator('.chip.review')).toHaveText('Review')
  await expect(page.getByText('appear once the model runs')).toHaveCount(0)
  // each value is marked with its price's last move, so a Refresh flashes it gain-soft or loss-soft
  await expect(shop.locator('.h-value')).toHaveAttribute('data-price', 'down')
  await expect(msft.locator('.h-value')).toHaveAttribute('data-price', 'up')

  // the stock page's Your position shows the same chips as the holdings table, the Review flag included
  await page.goto('/ticker/AAPL')
  const own = page.getByRole('region', { name: 'Your position' }).getByTestId('position')
  await expect(own.locator('.chip.hold')).toHaveText('Hold')
  await expect(own.locator('.chip.review')).toHaveText('Review')
  await page.goto('/ticker/MSFT')
  await expect(own.locator('.chip.hold')).toHaveText('Hold')
  await expect(own.locator('.chip.review')).toHaveCount(0)
})

test('each action says how to place it, and each holding the stop to keep', async ({ page }) => {
  const days = weekdays(daysAgo(30))
  await seedSymbols([
    { symbol: 'SHOP.TO', market: 'TSX', name: 'Shopify Inc.' },
    { symbol: 'MSFT', market: 'US', name: 'Microsoft Corporation' },
  ])
  await seedFx(days, 1.4)
  await seedCloses('SHOP.TO', 'stock', 'CAD', days, 160, -0.5)
  await seedCloses('MSFT', 'stock', 'USD', days, 400, 0.5)
  await seedLot({ account: 'tfsa', symbol: 'SHOP.TO', asset_type: 'stock', qty: 10, price: 160, currency: 'CAD', bought_at: days[0] })
  await seedLot({ account: 'tfsa', symbol: 'MSFT', asset_type: 'stock', qty: 5, price: 400, currency: 'USD', fx_rate_cad: 1.4, bought_at: days[0] })
  // the previous published run's stop was lower, so the stop order should be raised
  const earlier = await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: new Date(Date.now() - 86_400_000).toISOString() })
  await seedHoldingAction(earlier, { account: 'tfsa', symbol: 'MSFT', asset_type: 'stock', action: 'hold', reasons: ['Hold.'], trailing_stop: 390 })
  const runId = await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: new Date().toISOString() })
  // under the liquid line, with a 2% daily range: a 0.5% buffer and a 1% stop-limit gap
  for (const symbol of ['SHOP.TO', 'MSFT']) await seedFeatures(runId, symbol, 'stock', { atr_14_pct: 0.02, log_adv20: Math.log1p(5e6) })
  await seedHoldingAction(runId, {
    account: 'tfsa',
    symbol: 'SHOP.TO',
    asset_type: 'stock',
    action: 'sell',
    reasons: ['closed at 140.00, under its trailing stop 146.10'],
    trailing_stop: 146.1,
    ref_price: 140,
  })
  await seedHoldingAction(runId, {
    account: 'tfsa',
    symbol: 'MSFT',
    asset_type: 'stock',
    action: 'hold',
    review: true,
    reasons: ['no rule fired', 'earnings on Oct 30'],
    trailing_stop: 398.5,
    ref_price: 420,
  })
  await page.goto('/portfolio')

  // the order is priced off the latest close (a Refresh's live price when there is one), not the run's ref_price
  const lastShop = 160 - 0.5 * (days.length - 1)
  const sellAt = (Math.round(lastShop * 0.995 * 100) / 100).toFixed(2).replace('.', '\\.')
  const sell = page.locator('.action-card.sell .order-guide')
  await expect(sell).toContainText(new RegExp(`Limit sell 10 sh at C\\$${sellAt} · (Day order|set it to expire at the end of the next trading day)`))
  await expect(sell).not.toContainText('Stop-limit') // a Sell's order replaces its stop
  const review = page.locator('.action-card.review .order-guide')
  const stop = /^Stop-limit sell 5 sh: stop US\$398\.50, limit US\$394\.5[12], expiry 90 days · raise it from US\$390\.00$/
  await expect(review.locator('.og-step')).toHaveText(stop)

  await expect(holdings(page).filter({ hasText: 'MSFT' }).locator('.order-note')).toHaveText(stop)
  await expect(holdings(page).filter({ hasText: 'SHOP.TO' }).locator('.order-note')).toContainText('Stop-limit sell 10 sh: stop C$146.10')
  await expect(page.getByText("Order guidance is a rule of thumb for Wealthsimple's order types, not a price forecast.")).toHaveCount(1)
})

test('an Add also offers the buy as one bracket order on the new shares', async ({ page }) => {
  const days = weekdays(daysAgo(30))
  await seedSymbols([
    { symbol: 'SHOP.TO', market: 'TSX', name: 'Shopify Inc.' },
    { symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' },
  ])
  await seedFx(days, 1.4)
  await seedCloses('SHOP.TO', 'stock', 'CAD', days, 100, 0)
  await seedCloses('RY.TO', 'stock', 'CAD', days, 100, 0)
  // a C$100,000 portfolio holding C$1,000 of SHOP.TO: a medium-risk Add tops it up to 3%, C$2,000 more
  await seedLot({ account: 'tfsa', symbol: 'SHOP.TO', asset_type: 'stock', qty: 10, price: 100, currency: 'CAD', bought_at: days[0] })
  await seedLot({ account: 'tfsa', symbol: 'RY.TO', asset_type: 'stock', qty: 990, price: 100, currency: 'CAD', bought_at: days[0] })
  const runId = await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: new Date().toISOString() })
  await seedFeatures(runId, 'SHOP.TO', 'stock', { atr_14_pct: 0.02, log_adv20: Math.log1p(5e6) })
  await seedHoldingAction(runId, {
    account: 'tfsa',
    symbol: 'SHOP.TO',
    asset_type: 'stock',
    action: 'add',
    reasons: ['would be a Buy today: P(beat XIU.TO) 0.60 over 10 trading days, below its max size'],
    trailing_stop: 92,
    ref_price: 100,
    q10: -0.04,
    q50: 0.03,
    q90: 0.12,
    horizon_days: 10,
    exit_by: addDays(today(), 14),
    risk_level: 'medium',
  })
  await page.goto('/portfolio')
  const guide = page.locator('.action-card.add .order-guide')
  // C$2,000 at C$100.50 is 19 sh; the take-profit is C$100 × 1.12, the stop loss the trailing stop
  await expect(guide).toContainText(
    /Or as one bracket order: limit buy 19 sh at C\$100\.50 · (Day order|set it to expire at the end of the next trading day), take profit C\$112\.00 \(\+11%\), stop loss C\$92\.00 \(−8%\)/,
  )
  await expect(guide).toContainText('A bracket covers only the shares this buy adds; the shares you hold keep their own stop-limit.')
})

test("a holding's exit plan shows in the table, the cards and the hold list, and its alert link prefills the form", async ({ page }) => {
  const days = weekdays(daysAgo(30))
  await seedSymbols([
    { symbol: 'SHOP.TO', market: 'TSX', name: 'Shopify Inc.' },
    { symbol: 'MSFT', market: 'US', name: 'Microsoft Corporation' },
  ])
  await seedFx(days, 1.4)
  await seedCloses('SHOP.TO', 'stock', 'CAD', days, 160, -0.5)
  await seedCloses('MSFT', 'stock', 'USD', days, 400, 0.5)
  await seedLot({ account: 'tfsa', symbol: 'SHOP.TO', asset_type: 'stock', qty: 10, price: 180, currency: 'CAD', bought_at: days[0] })
  await seedLot({ account: 'tfsa', symbol: 'MSFT', asset_type: 'stock', qty: 5, price: 400, currency: 'USD', fx_rate_cad: 1.4, bought_at: days[0] })
  const runId = await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: new Date().toISOString() })
  const recheck = addDays(today(), 29)
  // a plain Hold without a stop: its plan passed the check and has a sell-at price
  await seedHoldingAction(runId, {
    account: 'tfsa',
    symbol: 'MSFT',
    asset_type: 'stock',
    action: 'hold',
    reasons: ['Hold.'],
    ref_price: 420,
    horizon_days: 21,
    exit_by: recheck,
    exit_plan: {
      status: 'pass',
      basis: 'forecast',
      horizon: 21,
      recheck_by: recheck,
      low: 400,
      mid: 425,
      high: 455,
      sell_at: 440.123456,
      p_touch: 0.33,
      p_stop_first: null,
      p_up: 0.55,
      breakeven: null,
      p_breakeven: null,
      drift: 0.009,
      cost_price: 400,
    },
  })
  // a Sell under water whose plan no benchmark has checked yet
  await seedHoldingAction(runId, {
    account: 'tfsa',
    symbol: 'SHOP.TO',
    asset_type: 'stock',
    action: 'sell',
    reasons: ['closed at 145.00, under its trailing stop 146.10'],
    trailing_stop: 146.1,
    ref_price: 145,
    exit_plan: {
      status: 'unvalidated',
      basis: 'volatility',
      horizon: 21,
      recheck_by: recheck,
      low: 130,
      mid: 145,
      high: 160,
      sell_at: 155,
      p_touch: 0.33,
      p_stop_first: 0.4,
      p_up: 0.5,
      breakeven: 180,
      p_breakeven: 0.05,
      drift: null,
      cost_price: 180,
    },
  })
  await page.goto('/portfolio')

  const by = shortDay(recheck)
  // the plan sits under the holding's name, one block per planned holding
  await expect(page.locator('#holdings .h-exit')).toHaveCount(2)
  const msft = holdings(page).filter({ hasText: 'MSFT' })
  await expect(msft.locator('.h-exit')).toContainText(`Range by ${by}: US$400.00 – 425.00 – 455.00 (+1%)`)
  await expect(msft.locator('.h-exit')).toContainText('Sell at US$440.12 · about 1 in 3 · +10% on cost')
  // without a stop the sell-at price is also an order to place
  await expect(msft.locator('.order-note')).toHaveText('Limit sell 5 sh at US$440.12, expiry 90 days · replace any earlier sell-at order')
  const shop = holdings(page).filter({ hasText: 'SHOP.TO' })
  await expect(shop.locator('.h-exit')).toContainText(`Range by ${by}: C$130.00 – 145.00 – 160.00 (0%)`)
  await expect(shop.locator('.h-exit')).toContainText('Not validated yet: the first benchmark run after this change checks these chances.')
  await expect(shop.locator('.h-exit')).toContainText('From volatility only — no view on direction')
  // a Sell keeps its range and break-even, but no sell-at price, stop-first chance or alert (R20a)
  await expect(shop.locator('.h-exit')).toContainText(`Unlikely to get back to your cost by ${by}: reached in 5% of cases.`)
  await expect(shop.locator('.h-exit')).not.toContainText('Sell at')
  await expect(shop.locator('.h-exit')).not.toContainText('Stop first')
  await expect(shop.getByRole('link', { name: /Alert me at/ })).toHaveCount(0)
  // once, under the table: the cells leave out the closes line and a forecast plan's basis
  await expect(page.getByText('Chances count closes at or above the price.')).toHaveCount(1)
  await expect(page.getByText("Chances count closes at or above the price. Plans are from the model's forecast unless marked “From volatility only”.", { exact: true })).toHaveCount(1)

  const card = page.locator('.action-card.sell')
  await expect(card).toContainText(`Range by ${by}: C$130.00 – 145.00 – 160.00 (0%)`)
  await expect(card.locator('.warn-cell')).toContainText(`Unlikely to get back to your cost by ${by}: reached in 5% of cases.`)
  await expect(card).toContainText('Not validated yet')
  await expect(card).not.toContainText('Sell at')
  // the holding has a plan, so its Sell says to cancel a resting limit sell first (R20c)
  await expect(card.locator('.order-guide')).toContainText('Cancel any resting limit sell on these shares first.')
  await page.getByRole('button', { name: /1 holding · MSFT/ }).click()
  await expect(page.locator('#hold-list')).toContainText(`hold ~21 trading days · range US$400.00–455.00 · sell at US$440.12 · re-check ${by}`)

  const alert = msft.getByRole('link', { name: 'Alert me at US$440.12' })
  await expect(alert).toHaveAttribute('href', '/ticker/MSFT?alertLevel=440.12&alertDir=above&alertNote=exit+plan+sell-at#alerts')
  await alert.click()
  await expect(page).toHaveURL(/\/ticker\/MSFT\?alertLevel=440\.12/)
  const plan = page.locator('.exit-plan')
  await expect(plan).toHaveCount(1)
  await expect(plan.getByText('Exit plan · USD', { exact: true })).toBeVisible() // in Your position
  await expect(plan).toContainText("From the model's forecast · assumes SPY drifts +0.9% over 21 trading days")
  await expect(plan).toContainText('Sell at US$440.12 · about 1 in 3 · +10% on cost')
  await expect(plan).toContainText('Chances count closes at or above the price.')
  // the link opens the Alerts sheet with the form filled in
  const sheet = page.getByRole('dialog', { name: 'Alerts' })
  await expect(sheet).toBeVisible()
  const form = sheet.locator('form')
  await expect(form.locator('select[name="direction"]')).toHaveValue('above')
  await expect(form.locator('input[name="level"]')).toHaveValue('440.12')
  await expect(form.locator('input[name="note"]')).toHaveValue('exit plan sell-at')
  // nothing is saved until the owner adds it
  await expect(sheet.getByText('No alerts on MSFT.')).toBeVisible()

  // the Sell's ticker page: its range and break-even, no sell-at price, stop-first chance or alert (R20a)
  await page.goto('/ticker/SHOP.TO')
  const sold = page.locator('.exit-plan')
  await expect(sold).toContainText(`Range by ${by}: C$130.00 – 145.00 – 160.00 (0%)`)
  await expect(sold).toContainText(`Unlikely to get back to your cost by ${by}: reached in 5% of cases.`)
  await expect(sold).not.toContainText('Sell at')
  await expect(sold).not.toContainText('Stop first')
  await expect(sold.getByRole('link', { name: /Alert me at/ })).toHaveCount(0)
})
