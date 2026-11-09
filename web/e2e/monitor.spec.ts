import { expect, test } from '@playwright/test'
import { daysAgo, resetData, seedEarnings, seedFiling, seedInsider, seedNews, seedPortfolio, seedQuarter, seedRun } from './db'

const FEED = "What's new on your stocks"

test.beforeEach(async () => {
  await resetData()
  await seedPortfolio() // AAPL (US) and RY.TO (TSX) held
})

test('My Portfolio lists a headline, an important 8-K, an insider buy and an upcoming report', async ({ page }) => {
  await seedNews([
    { symbol: 'AAPL', asset_type: 'stock', hoursAgo: 3, outlet: 'Reuters', url: 'https://example.com/aapl', title: 'Apple unveils a new chip', sentiment: 0.4 },
  ])
  await seedFiling({ accession: '0000320193-26-000001', symbol: 'AAPL', hoursAgo: 2, items: ['5.02', '9.01'] })
  await seedInsider({ accession: '0000320193-26-000002', symbol: 'AAPL', hoursAgo: 4, owner: 'Jane Doe', role: 'CFO', code: 'P', shares: 1000, price: 12.34, planned: true })
  await seedEarnings({ symbol: 'AAPL', daysFromNow: 5, epsEstimate: 1.23 })

  await page.goto('/')
  const card = page.getByRole('region', { name: FEED })
  await expect(card.getByRole('link', { name: 'Apple unveils a new chip' })).toBeVisible()
  await expect(card.getByText('8-K: director or officer change')).toBeVisible()
  await expect(card.getByText('Important', { exact: true })).toBeVisible()
  await expect(card.getByText('Jane Doe (CFO) bought 1,000 shares at $12.34')).toBeVisible()
  await expect(card.getByText('(10b5-1 plan)')).toBeVisible()
  await expect(card.getByText('Earnings report due')).toBeVisible()
  await expect(card.getByText(/EPS estimate \$1\.23/)).toBeVisible()
  await expect(card.getByTestId('monitor-item')).toHaveCount(4)
})

test('the feed shows filings and insider trades stored since the previous run, even when filed earlier', async ({ page }) => {
  // the previous published run started 30h15m ago; the latest one finished an hour ago
  await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: new Date(Date.now() - 30 * 3_600_000).toISOString() })
  await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
  // filed 3 days ago, first stored by the latest run (a daily source, or a failed fetch caught up)
  await seedFiling({ accession: '0000320193-26-000011', symbol: 'AAPL', hoursAgo: 72, addedHoursAgo: 2, items: ['5.02'] })
  await seedInsider({ accession: '0000320193-26-000012', symbol: 'AAPL', hoursAgo: 40, addedHoursAgo: 2, owner: 'Late Filer', role: 'CEO', code: 'P', shares: 10, price: 5 })
  // filed 3 days ago and already stored before the previous run: shown then, not new now
  await seedFiling({ accession: '0000320193-26-000013', symbol: 'AAPL', hoursAgo: 72, addedHoursAgo: 40, items: ['2.02'] })
  await seedInsider({ accession: '0000320193-26-000014', symbol: 'AAPL', hoursAgo: 72, addedHoursAgo: 40, owner: 'Old News', role: 'CFO', code: 'S', shares: 10, price: 5 })
  // stored by the latest run but filed 20 days ago: a first backfill, not news
  await seedFiling({ accession: '0000320193-26-000015', symbol: 'AAPL', hoursAgo: 20 * 24, addedHoursAgo: 2, items: ['8.01'] })

  await page.goto('/')
  const card = page.getByRole('region', { name: FEED })
  await expect(card.getByText('8-K: director or officer change')).toBeVisible()
  await expect(card.getByText('Late Filer (CEO) bought 10 shares at $5.00')).toBeVisible()
  await expect(card.getByTestId('monitor-item')).toHaveCount(2)
  await expect(card.getByText(/earnings results/)).toHaveCount(0)
  await expect(card.getByText(/Old News/)).toHaveCount(0)
})

test('an empty feed says so', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('region', { name: FEED }).getByText('Nothing new since the last run.')).toBeVisible()
})

test('a US stock page shows the Earnings table with year-ago values, Filings and Insider trades', async ({ page }) => {
  // ten quarters, 91 days apart, newest ending yesterday: each of the newest six has a year-ago partner
  for (let k = 0; k < 10; k++) {
    await seedQuarter({
      symbol: 'AAPL',
      periodEnd: daysAgo(1 + 91 * k),
      fiscalPeriod: `Q${(k % 4) + 1}`,
      revenue: 100e9 - k * 1e9,
      grossProfit: 45e9,
      operatingIncome: 30e9,
      netIncome: 25e9,
      epsDiluted: 1.5 - k * 0.01,
      form: k === 0 ? '10-K' : '10-Q',
      filed: daysAgo(k * 91),
      derived: k === 0,
    })
  }
  await seedEarnings({ symbol: 'AAPL', daysFromNow: 5, epsEstimate: 1.23 })
  await seedEarnings({ symbol: 'AAPL', daysFromNow: -60, epsEstimate: 1.1, epsActual: 1.2, surprisePct: 9.1 })
  await seedFiling({ accession: '0000320193-26-000003', symbol: 'AAPL', hoursAgo: 48, items: ['2.02', '9.01'] })
  await seedInsider({ accession: '0000320193-26-000004', symbol: 'AAPL', hoursAgo: 30, owner: 'John Roe', role: 'Director', code: 'S', shares: 500, price: 200 })

  await page.goto('/ticker/AAPL')
  const earnings = page.getByRole('region', { name: 'Earnings' })
  await expect(earnings.getByTestId('quarter-row')).toHaveCount(6)
  await expect(earnings.getByRole('columnheader', { name: /Revenue/ })).toContainText('year ago')
  await expect(earnings.getByTestId('year-ago').first()).toBeVisible()
  await expect(earnings.getByTestId('ttm-row')).toBeVisible()
  await expect(earnings.getByTestId('next-earnings')).toContainText('EPS estimate $1.23')
  await expect(earnings.getByTestId('past-earnings-row')).toHaveCount(1)
  await expect(earnings.getByText(/Latest filing: 10-K filed/)).toBeVisible()
  await expect(earnings.getByText('derived', { exact: false }).first()).toBeVisible()

  const filings = page.getByRole('region', { name: 'Filings (8-K)' })
  await expect(filings.getByText('earnings results')).toBeVisible()
  await expect(filings.getByText('Important', { exact: true })).toBeVisible()
  const insiders = page.getByRole('region', { name: 'Insider trades' })
  await expect(insiders.getByText('John Roe')).toBeVisible()
  await expect(insiders.getByText(/sold/)).toBeVisible()
})

test('a US stock without filings or insider trades shows the empty states', async ({ page }) => {
  await page.goto('/ticker/AAPL')
  await expect(
    page.getByText('No 8-K stored for the last 90 days. Filings are collected for stocks you hold, watch or that a run shortlists.'),
  ).toBeVisible()
  await expect(
    page.getByText('No insider buys or sells stored for the last 90 days. They are collected for stocks you hold, watch or that a run shortlists.'),
  ).toBeVisible()
})

test('a TSX stock page has an earnings date but no Filings or Insider cards', async ({ page }) => {
  await seedEarnings({ symbol: 'RY.TO', daysFromNow: 9, epsEstimate: 2.5 })
  await page.goto('/ticker/RY.TO')
  await expect(page.getByRole('region', { name: 'Earnings' }).getByTestId('next-earnings')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Filings (8-K)' })).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Insider trades' })).toHaveCount(0)
})

test("a coin's entry links to its crypto page, a stock's to the stock page", async ({ page }) => {
  await seedNews([
    { symbol: 'ETH', asset_type: 'crypto', hoursAgo: 2, outlet: 'CoinDesk', url: 'https://example.com/eth', title: 'Ether rallies', sentiment: 0.5 },
    { symbol: 'AAPL', asset_type: 'stock', hoursAgo: 3, outlet: 'Reuters', url: 'https://example.com/aapl', title: 'Apple story', sentiment: 0.1 },
  ])
  await page.goto('/')
  const items = page.getByRole('region', { name: FEED }).getByTestId('monitor-item')
  await expect(items.filter({ hasText: 'Ether rallies' }).getByRole('link', { name: 'ETH', exact: true })).toHaveAttribute('href', '/ticker/ETH?asset=crypto')
  await expect(items.filter({ hasText: 'Apple story' }).getByRole('link', { name: 'AAPL', exact: true })).toHaveAttribute('href', '/ticker/AAPL')
})

test('an 8-K/A shows its own form and a negative EPS estimate keeps its sign', async ({ page }) => {
  await seedFiling({ accession: '0000320193-26-000009', symbol: 'AAPL', hoursAgo: 2, items: ['2.02'], form: '8-K/A' })
  await seedEarnings({ symbol: 'AAPL', daysFromNow: 3, epsEstimate: -0.12 })
  await page.goto('/')
  const card = page.getByRole('region', { name: FEED })
  await expect(card.getByText('8-K/A: earnings results')).toBeVisible()
  await expect(card.getByText(/EPS estimate -\$0\.12/)).toBeVisible()
})
