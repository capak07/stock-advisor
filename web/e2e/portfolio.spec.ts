import { expect, test, type Page } from '@playwright/test'
import { daysAgo, resetData, seedCloses, seedFx, seedLot, seedSell, seedSymbols, weekdays } from './db'

test.beforeEach(resetData)

const holdings = (page: Page) => page.locator('#holdings tbody tr')

test('an empty portfolio invites the first buy', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'My Portfolio' })).toBeVisible()
  await expect(page.getByText('No holdings yet. Add your first buy to start.')).toBeVisible()
  await expect(page.getByText('No actions yet')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sell' })).toHaveCount(0)
})

/** RY.TO and AAPL in the TFSA, ETH in the crypto account (part sold at a loss 5 days ago). */
async function seedPortfolio() {
  const days = weekdays(daysAgo(60))
  const allDays = Array.from({ length: 61 }, (_, i) => daysAgo(60 - i)).filter((d) => d < daysAgo(0))
  await seedSymbols([
    { symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' },
    { symbol: 'AAPL', market: 'US', name: 'Apple Inc.' },
  ])
  await seedFx(days, 1.4)
  await seedCloses('XIU.TO', 'stock', 'CAD', days, 40, 0.05)
  await seedCloses('SPY', 'stock', 'USD', days, 500, 0.5)
  await seedCloses('RY.TO', 'stock', 'CAD', days, 170, 0.25)
  await seedCloses('AAPL', 'stock', 'USD', days, 200, 0.5)
  await seedCloses('ETH', 'crypto', 'USD', allDays, 3000, -5)
  await seedLot({ account: 'tfsa', symbol: 'RY.TO', asset_type: 'stock', qty: 10, price: 170, currency: 'CAD', bought_at: days[0] })
  await seedLot({ account: 'tfsa', symbol: 'AAPL', asset_type: 'stock', qty: 5, price: 200, currency: 'USD', fx_rate_cad: 1.4, bought_at: days[0] })
  await seedLot({ account: 'crypto', symbol: 'ETH', asset_type: 'crypto', qty: 2, price: 4200, currency: 'CAD', bought_at: days[0] })
  await seedSell({ account: 'crypto', symbol: 'ETH', asset_type: 'crypto', qty: 1, price: 3900, currency: 'CAD', sold_at: daysAgo(5) })
}

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
