import { expect, test } from '@playwright/test'
import { MARKET_CLOSED } from '../lib/daytrade'
import {
  nyAt,
  resetData,
  seedDaytradeDay,
  seedDaytradeSignal,
  seedHoldingAction,
  seedNews,
  seedPortfolio,
  seedPrediction,
  seedRun,
  today,
} from './db'

const ATTENTION = /^Needs your attention/
const DAYTRADE = 'Day trade · top 3 after costs'

test.beforeEach(async () => {
  await resetData()
})

test('an empty portfolio shows C$0.00 without a chart and nothing to attend to (Review Focus 1)', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Today', level: 1 })).toBeVisible()
  const summary = page.getByRole('link', { name: 'Portfolio summary' })
  await expect(summary.getByTestId('today-value')).toHaveText('C$0.00')
  await expect(summary.getByText(/No holdings yet/)).toBeVisible()
  await expect(summary.locator('svg')).toHaveCount(0)
  await expect(page.getByRole('region', { name: ATTENTION }).getByText('Nothing needs your attention.')).toBeVisible()
})

test('a Sell holding shows under Needs your attention with its Sell chip; the Holds are counted', async ({ page }) => {
  await seedPortfolio() // RY.TO and AAPL in the TFSA, ETH in the crypto account
  const runId = await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
  await seedHoldingAction(runId, { account: 'tfsa', symbol: 'RY.TO', asset_type: 'stock', action: 'sell', reasons: ['closed below its stop'] })
  await seedHoldingAction(runId, { account: 'tfsa', symbol: 'AAPL', asset_type: 'stock', action: 'hold', reasons: ['on track'] })
  await seedHoldingAction(runId, { account: 'crypto', symbol: 'ETH', asset_type: 'crypto', action: 'hold', reasons: ['on track'] })

  await page.goto('/')
  const card = page.getByRole('region', { name: ATTENTION })
  const row = card.getByTestId('attention-row')
  await expect(row).toHaveCount(1)
  await expect(row.getByText('Sell', { exact: true })).toBeVisible()
  await expect(row.getByText('RY.TO', { exact: true })).toBeVisible()
  await expect(row.getByText('Closed below its stop')).toBeVisible()
  await expect(row).toHaveAttribute('href', '/ticker/RY.TO')
  await expect(card.getByRole('link', { name: /2 more on Hold/ })).toHaveAttribute('href', '/portfolio')
  // the summary shows only the money made or lost on the last session, with no chart or SPY gap
  const summary = page.getByRole('link', { name: 'Portfolio summary' })
  await expect(summary).toHaveAttribute('href', '/portfolio')
  await expect(summary.getByTestId('today-value')).toHaveText(/^[+−]C\$[\d,]+\.\d\d$/)
  await expect(summary.locator('svg')).toHaveCount(0)
  await expect(summary.getByText(/All time|SPY|cash/i)).toHaveCount(0)
})

test('with no run, the Picks card says No run yet (Review Focus 2)', async ({ page }) => {
  await page.goto('/')
  const picks = page.getByRole('region', { name: 'Picks' })
  await expect(picks.getByText('No run yet', { exact: true })).toBeVisible()
  await expect(picks.getByText(/best chance/)).toHaveCount(0)
})

test('a run with no picks shows the best chance per market against the 58% bar', async ({ page }) => {
  const runId = await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
  await seedPrediction(runId, 'AAPL', 21, { q10: -0.05, q50: 0.01, q90: 0.06, p: 0.527 })
  await seedPrediction(runId, 'AAPL', 63, { q10: -0.05, q50: 0.01, q90: 0.06, p: 0.49 })
  await seedPrediction(runId, 'RY.TO', 21, { q10: -0.05, q50: 0.01, q90: 0.06, p: 0.551 })

  await page.goto('/')
  const picks = page.getByRole('region', { name: 'Picks' })
  await expect(picks.getByText('None today')).toBeVisible()
  await expect(picks.getByText('US 52.7% vs SPY · TSX 55.1% vs XIU.TO')).toBeVisible()
  await expect(picks.getByText(/a pick needs 58%\. Nothing has enough evidence to buy\./)).toBeVisible()
  await expect(picks.getByRole('link', { name: 'Why none?' })).toHaveAttribute('href', '/picks')
  await expect(picks.getByRole('link', { name: 'Watchlist verdicts' })).toHaveAttribute('href', '/watchlist')
})

test('a closed day (a holiday) reads No session today and markets closed (Review Focus 3)', async ({ page }) => {
  await seedDaytradeDay({ status: 'closed' })
  await page.goto('/')
  await expect(page.getByRole('region', { name: DAYTRADE }).getByText('No session today.')).toBeVisible()
  await expect(page.getByTestId('today-line')).toContainText('markets closed')
})

test('with no day-trade row the header says markets closed and the card says what the Day trade page says', async ({ page }) => {
  // the weekday-before-the-job wording is covered with a fixed clock in DaytradeTop.test.tsx
  await page.goto('/daytrade')
  const line = (await page.getByTestId('daytrade-status').textContent())!.trim()
  await page.goto('/')
  await expect(page.getByTestId('today-line')).toContainText('markets closed')
  const card = page.getByRole('region', { name: DAYTRADE })
  await expect(card.getByText(line === MARKET_CLOSED ? 'No session today.' : line)).toBeVisible()
})

test("the Day trade card shows the Day trade page's top 3 after costs, the first with its levels", async ({ page }) => {
  const day = today()
  await seedDaytradeDay({ status: 'done', lastUpdate: nyAt(day, '15:55') })
  await seedDaytradeSignal({ symbol: 'TSLA', name: 'Tesla', triggerAt: nyAt(day, '10:15'), entry: 364.18, stop: 358.32, rank: 1, status: 'target', netHistoryR: 0.12 })
  await seedDaytradeSignal({ symbol: 'AMD', triggerAt: nyAt(day, '10:40'), entry: 120, stop: 119, rank: 2, status: 'stop' })
  await seedDaytradeSignal({ symbol: 'SOFI', triggerAt: nyAt(day, '11:00'), entry: 20, stop: 19.8, rank: null, eligible: false })

  await page.goto('/')
  const card = page.getByRole('region', { name: DAYTRADE })
  const trades = card.getByTestId('today-trade')
  await expect(trades).toHaveCount(2)
  await expect(trades.nth(0)).toContainText('TSLA')
  // the currency in the label, the figure whole
  await expect(trades.nth(0).getByText('Entry US$', { exact: true })).toBeVisible()
  await expect(trades.nth(0).getByText('364.18', { exact: true })).toBeVisible()
  await expect(trades.nth(0).getByText('Target hit')).toBeVisible()
  await expect(trades.nth(0)).toContainText('10,000 replays: target first 34%')
  await expect(trades.nth(0)).toContainText('history +0.12R after costs')
  await expect(trades.nth(1)).toContainText('AMD')
  await expect(trades.nth(1).getByText('Stopped out')).toBeVisible()
  await expect(trades.nth(1).getByText('Entry')).toHaveCount(0)
  await expect(card.getByText('SOFI')).toHaveCount(0)
  await expect(card.getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/daytrade')
})

test('the news shows the latest 3 and Show all expands it in place', async ({ page }) => {
  await seedPortfolio()
  await seedNews(
    [1, 2, 3, 4, 5].map((h) => ({
      symbol: h <= 3 ? 'AAPL' : 'RY.TO', // the feed keeps 3 headlines a symbol
      asset_type: 'stock' as const,
      hoursAgo: h,
      outlet: 'Reuters',
      url: `https://example.com/aapl-${h}`,
      title: `Apple story ${h}`,
      sentiment: 0.1,
    })),
  )
  await page.goto('/')
  const feed = page.getByRole('region', { name: "What's new on your stocks" })
  await expect(feed.getByTestId('monitor-item')).toHaveCount(3)
  await expect(feed.getByText('Apple story 4')).toHaveCount(0)
  await feed.getByRole('button', { name: /Show all 5/ }).click()
  await expect(feed.getByTestId('monitor-item')).toHaveCount(5)
  await expect(feed.getByText('Apple story 5')).toBeVisible()
  await expect(page).toHaveURL(/\/$/)
})

test('at 390 px the page has no horizontal scroll', async ({ page }) => {
  await seedPortfolio()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Today', level: 1 })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
})
