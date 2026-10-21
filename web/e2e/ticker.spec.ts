import { expect, test } from '@playwright/test'
import { daysAgo, resetData, seedFeatures, seedHealth, seedNews, seedPortfolio, seedRun, seedSources, sql, weekdays } from './db'

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

test("a coin's page is in CAD, and the coin can be watched and unwatched from it", async ({ page }) => {
  await page.goto('/')
  const sidebar = page.getByRole('complementary', { name: 'Main' })
  await sidebar.getByRole('combobox', { name: 'Find a symbol' }).fill('ether')
  await expect(sidebar.getByRole('option')).toHaveText(['ETHEthereumCrypto'])
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
  await search.fill('shop.to')
  await expect(page.getByText('No match in the lists. Press Enter to open it as a symbol.')).toBeVisible()
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
  await expect(options).toHaveText(['RY.TORoyal Bank of CanadaTSX'])
  await options.first().click()
  await expect(page).toHaveURL(/\/ticker\/RY\.TO$/)
  await expect(page.getByRole('heading', { name: 'RY.TO', level: 1 })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Watch', exact: true })).toBeVisible()
})
