import { expect, test } from '@playwright/test'
import {
  daysAgo,
  resetData,
  seedFeatures,
  seedHealth,
  seedNews,
  seedOutcome,
  seedPick,
  seedPortfolio,
  seedPrediction,
  seedRun,
  seedSources,
  sql,
  weekdays,
} from './db'

test.beforeEach(async () => {
  await resetData()
  await seedPortfolio()
})

test("a held stock's page shows its price, the position, the last two days of news and its sources", async ({ page }) => {
  const runId = await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
  await seedSources()
  await seedHealth(runId, new Date().toISOString(), [
    { source: 'yfinance_bars', status: 'ok' },
    { source: 'google_news', status: 'stale' },
    { source: 'sec_form4', status: 'ok' },
  ])
  await seedFeatures(runId, 'RY.TO', 'stock', {
    news_stories_48h: 2,
    news_outlets_48h: 2,
    news_sentiment_mean: 0.31,
    news_sentiment_trend: -0.05,
  })
  await seedNews([
    { symbol: 'RY.TO', asset_type: 'stock', hoursAgo: 3, outlet: 'BNN Bloomberg', url: 'https://www.bnnbloomberg.ca/ry', title: 'RBC raises its dividend', sentiment: 0.62 },
    { symbol: 'RY.TO', asset_type: 'stock', hoursAgo: 30, outlet: 'Globe', url: 'javascript:alert(1)', title: 'RBC names a new CFO', sentiment: -0.01 },
    { symbol: 'RY.TO', asset_type: 'stock', hoursAgo: 72, outlet: 'Globe', url: 'https://example.com/old', title: 'An older RBC story', sentiment: 0.1 },
    { symbol: 'TD.TO', asset_type: 'stock', hoursAgo: 2, outlet: 'Globe', url: 'https://example.com/td', title: 'TD story', sentiment: 0.1 },
  ])

  await page.goto('/')
  await page.locator('#holdings').getByRole('link', { name: 'RY.TO' }).click()
  await expect(page).toHaveURL(/\/ticker\/RY\.TO$/)
  await expect(page.getByRole('heading', { name: 'RY.TO', level: 1 })).toBeVisible()
  await expect(page.getByText('Royal Bank of Canada · TSX', { exact: true })).toBeVisible() // the exchange only when it differs
  const days = weekdays(daysAgo(60))
  await expect(page.locator('#last-price')).toHaveText(`C$${(170 + 0.25 * (days.length - 1)).toFixed(2)}`)
  await expect(page.getByText('You hold 10 · TFSA')).toBeVisible()
  await expect(page.getByRole('img', { name: 'RY.TO closes over 6M' })).toBeVisible()
  await page.getByRole('tab', { name: '1M' }).click()
  await expect(page.getByRole('img', { name: 'RY.TO closes over 1M' })).toBeVisible()

  const news = page.getByRole('region', { name: 'News' })
  await expect(news.locator('.kpi')).toHaveText(['Stories2', 'Outlets2', 'Sentiment+0.31', 'Trend−0.05'])
  await expect(news.locator('.news-item')).toHaveCount(2) // not the 3-day-old story, nor TD's
  await expect(news.getByRole('link', { name: 'RBC raises its dividend' })).toHaveAttribute('href', 'https://www.bnnbloomberg.ca/ry')
  await expect(news.getByText('RBC names a new CFO')).toBeVisible()
  await expect(news.getByRole('link', { name: 'RBC names a new CFO' })).toHaveCount(0) // a script link is shown as text

  const sources = page.getByRole('region', { name: 'Sources' })
  await expect(sources.getByText(/^1 of the 2 sources that cover TSX stocks answered/)).toBeVisible()
  await expect(sources.locator('#ticker-sources > span')).toHaveText(['google_newsstale', 'yfinance_bars'])
  await expect(sources.getByText('Not available for TSX stocks: sec_8k, sec_form4.')).toBeVisible()
})

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString()

/** A published run that forecast RY.TO at 21 and 63 days, explained at 63. */
async function seedForecast() {
  const runId = await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: hoursAgo(1) })
  await seedPrediction(runId, 'RY.TO', 21, { q10: -0.031, q50: 0.006, q90: 0.041, p: 0.55 })
  await seedPrediction(runId, 'RY.TO', 63, { q10: -0.075, q50: 0.021, q90: 0.108, p: 0.61 })
  await seedFeatures(runId, 'RY.TO', 'stock', {
    ex_bench_63: 0.041,
    fcf_yield: 0.062,
    ret_21: -0.012,
    advice: {
      horizon: 63,
      top_factors: [
        { feature: 'ex_bench_63', contribution: 0.012 },
        { feature: 'fcf_yield', contribution: 0.008 },
        { feature: 'ret_21', contribution: -0.004 },
      ],
      catalysts: [{ type: 'earnings', date: '2026-12-03' }],
      round_trip_cost: 0.003,
    },
  })
  return runId
}

test('a forecast stock shows its cone, odds, factors and catalysts', async ({ page }) => {
  await seedForecast()
  await page.goto('/ticker/RY.TO')
  await expect(page.getByRole('heading', { name: 'Price and forecast' })).toBeVisible()
  const horizons = page.getByRole('tablist', { name: 'Forecast horizon in trading days' })
  await expect(horizons.getByRole('tab')).toHaveText(['21d', '63d'])
  await expect(horizons.getByRole('tab', { name: '63d' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.forecast-cone')).toHaveCount(1)
  await expect(page.locator('g[aria-label="Forecast: +63 trading days · if XIU.TO is flat"]')).toHaveCount(1)
  const kpis = page.locator('#forecast-kpis')
  await expect(kpis).toContainText('Beats XIU.TO61%over 63 trading days')
  await expect(kpis).toContainText('Median+2.1%relative to XIU.TO')
  await expect(kpis).toContainText('Likely range−7.5% to +10.8%')

  const factors = page.getByRole('region', { name: 'Top factors' })
  await expect(factors.locator('.factor')).toHaveText([
    'Return vs XIU.TO over 63 days +4.1%',
    'Free-cash-flow yield 6.2%',
    'Return over 21 days −1.2%',
  ])
  await expect(factors.locator('.factor').last().getByRole('img')).toHaveAttribute('aria-label', 'lowers the forecast')
  await expect(factors).toContainText('Est. cost 0.3% round trip · spread')
  await expect(page.getByRole('region', { name: 'Catalysts' })).toContainText('Earnings Dec 3, inside the hold')
  await expect(page.getByText(/appear here once the model runs/)).toHaveCount(0)
  // the cone and odds follow the horizon tab
  await horizons.getByRole('tab', { name: '21d' }).click()
  await expect(kpis).toContainText('Beats XIU.TO55%over 21 trading days')
  await expect(page.locator('g[aria-label="Forecast: +21 trading days · if XIU.TO is flat"]')).toHaveCount(1)
})

test('horizon tabs list only the usable horizons', async ({ page }) => {
  const runId = await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: hoursAgo(1) })
  await seedPrediction(runId, 'AAPL', 5, { q10: -0.02, q50: 0.004, q90: 0.029, p: 0.52 })
  await seedPrediction(runId, 'AAPL', 126, { q10: -0.11, q50: 0.038, q90: 0.16, p: 0.63 })
  await page.goto('/ticker/AAPL')
  const horizons = page.getByRole('tablist', { name: 'Forecast horizon in trading days' })
  await expect(horizons.getByRole('tab')).toHaveText(['5d', '126d'])
  // no advice: the first usable horizon is selected, and there are no factors to explain
  await expect(horizons.getByRole('tab', { name: '5d' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('#forecast-kpis')).toContainText('Beats SPY52%')
  await expect(page.getByRole('region', { name: 'Top factors' })).toHaveCount(0)
})

test('a ticker without forecasts keeps the empty forecast card', async ({ page }) => {
  await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: hoursAgo(1) })
  await page.goto('/ticker/RY.TO')
  await expect(page.getByText('The forecast cone, its top factors, catalysts and past picks for RY.TO appear here once the model runs.')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Price', exact: true })).toBeVisible()
  await expect(page.getByRole('tablist', { name: 'Forecast horizon in trading days' })).toHaveCount(0)
  await expect(page.locator('.forecast-cone')).toHaveCount(0)
  // an unpublished run's forecast is never shown
  const draft = await seedRun({ kind: 'pre_close', status: 'running', published: false, finished: hoursAgo(0.5) })
  await seedPrediction(draft, 'RY.TO', 21, { q10: -0.03, q50: 0.01, q90: 0.04, p: 0.6 })
  await page.reload()
  await expect(page.locator('.forecast-cone')).toHaveCount(0)
})

const ryPick = (horizon: number, status: 'open' | 'exited_early' | 'graded' = 'open') => ({
  symbol: 'RY.TO',
  market: 'TSX' as const,
  style: 'swing' as const,
  horizon,
  rank: 1,
  exitBy: '2026-10-20',
  entry: 180,
  stop: 170,
  riskLevel: 'low' as const,
  maxPct: 5,
  status,
})

test("past picks list the stock's earlier picks", async ({ page }) => {
  const earlier = await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: hoursAgo(72) })
  await seedPrediction(earlier, 'RY.TO', 10, { q10: -0.02, q50: 0.015, q90: 0.05, p: 0.61 })
  await seedPick(earlier, ryPick(10))
  await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: hoursAgo(1) })
  await page.goto('/ticker/RY.TO')
  await expect(page.getByText('No forecast this run. Its earlier picks are below.')).toBeVisible()
  const rows = page.locator('#past-picks tbody tr')
  await expect(rows).toHaveCount(1)
  await expect(rows.locator('td')).toHaveText([/^[A-Z][a-z]{2} \d{1,2}$/, 'Swing', '10d', '61%', 'Oct 20', 'open'])
})

test('a graded past pick shows its result', async ({ page }) => {
  const earlier = await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: hoursAgo(96) })
  const graded = await seedPick(earlier, ryPick(10, 'graded'))
  await seedOutcome(graded, { exitPrice: 185, exitReason: 'horizon', ret: 0.028, benchRet: 0.011, beat: true })
  const exited = await seedPick(earlier, { ...ryPick(5, 'exited_early'), rank: 2 })
  await seedOutcome(exited, { exitPrice: 174, exitReason: 'exit_early', ret: -0.032, benchRet: 0.004, beat: false })
  await seedForecast()
  await page.goto('/ticker/RY.TO')
  const past = page.getByRole('region', { name: 'Past picks' })
  await expect(past).toContainText('1 graded · 1 beat XIU.TO')
  const rows = past.locator('#past-picks tbody tr')
  await expect(rows).toHaveCount(2)
  await expect(rows.nth(0).locator('td').last()).toHaveText('exited early · −3.2%')
  await expect(rows.nth(1).locator('td').last()).toHaveText('+2.8% vs XIU.TO +1.7% ✓')
  await expect(rows.nth(1).locator('td').nth(3)).toHaveText('—') // no prediction row from that run
})

test("a coin's page is in CAD, and the coin can be watched and unwatched from it", async ({ page }) => {
  await page.goto('/')
  const sidebar = page.getByRole('complementary', { name: 'Main' })
  await sidebar.getByRole('combobox', { name: 'Find a symbol' }).fill('ether')
  await expect(sidebar.getByRole('option')).toHaveText(['ETHEthereumCrypto', 'ETHEROpen as a symbol'])
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/ticker\/ETH\?asset=crypto$/)
  await expect(page.getByText('Crypto · priced in CAD')).toBeVisible()
  const [{ close }] = await sql`select close::float from daily_closes where symbol = 'ETH' order by day desc limit 1`
  await expect(page.locator('#last-price')).toHaveText(`C$${(close * 1.4).toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`)
  await expect(page.getByText('You hold 1 · Crypto')).toBeVisible()

  await page.getByRole('button', { name: 'Watch', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('ETH added to the watchlist')
  await expect(page.getByRole('button', { name: 'Watching' })).toHaveAttribute('aria-pressed', 'true')
  expect(await sql`select symbol, asset_type from watchlist`).toEqual([{ symbol: 'ETH', asset_type: 'crypto' }])
  await page.getByRole('button', { name: 'Watching' }).click()
  await expect(page.getByRole('status')).toHaveText('ETH removed from the watchlist')
  await expect(page.getByRole('button', { name: 'Watch', exact: true })).toHaveAttribute('aria-pressed', 'false')
})

test('any symbol has a page, with no data until a run collects it', async ({ page }) => {
  await page.goto('/')
  const search = page.getByRole('complementary', { name: 'Main' }).getByRole('combobox', { name: 'Find a symbol' })
  await search.fill('not a symbol!')
  await page.keyboard.press('Enter')
  await expect(page.getByText('Try a name or a symbol like NVDA, SHOP.TO or BTC.')).toBeVisible()
  await expect(page.locator('.combo-note')).toHaveText('No stock or coin matches.')
  await search.fill('shop.to')
  await expect(page.getByRole('complementary', { name: 'Main' }).getByRole('option')).toHaveText(['SHOP.TOOpen as a symbol'])
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/ticker\/SHOP\.TO$/)
  await expect(page.getByRole('heading', { name: 'SHOP.TO', level: 1 })).toBeVisible()
  await expect(page.getByText('Not in the stock lists · TSX')).toBeVisible()
  await expect(page.getByText(/^No prices yet/)).toBeVisible()
  await expect(page.getByText('No headlines in the last 48 hours.')).toBeVisible()
  await expect(page.getByText('No sources are listed yet; the next run lists them.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Watch', exact: true })).toHaveCount(0) // only listed stocks and coins

  await page.goto('/ticker/AAPL')
  await expect(page.getByText('Apple Inc. · US · NYSE', { exact: true })).toBeVisible()

  await page.goto('/ticker/not-valid')
  await expect(page.getByText('This page could not be found.')).toBeVisible()
})

test('the Find box lists stocks by name, best match first, and picking one opens its page', async ({ page }) => {
  await page.goto('/')
  const sidebar = page.getByRole('complementary', { name: 'Main' })
  await sidebar.getByRole('combobox', { name: 'Find a symbol' }).fill('royal')
  const options = sidebar.getByRole('option')
  await expect(options).toHaveText(['RY.TORoyal Bank of CanadaTSX', 'ROYALOpen as a symbol'])
  await options.first().click()
  await expect(page).toHaveURL(/\/ticker\/RY\.TO$/)
  await expect(page.getByRole('heading', { name: 'RY.TO', level: 1 })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Watch', exact: true })).toBeVisible()
})
