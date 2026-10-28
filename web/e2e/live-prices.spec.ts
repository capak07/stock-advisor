import { expect, test, type Page } from '@playwright/test'
import { daysAgo, resetData, seedCloses, seedFx, seedLot, seedSymbols, weekdays } from './db'

test.beforeEach(async () => {
  await resetData()
  const days = weekdays(daysAgo(20))
  await seedSymbols([{ symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' }])
  await seedLot({ account: 'tfsa', symbol: 'RY.TO', asset_type: 'stock', qty: 10, price: 100, currency: 'CAD', bought_at: days[0] })
  await seedCloses('RY.TO', 'stock', 'CAD', days, 100, 0) // the last run's price: C$100
  await seedFx(days, 1.4)
})

const ry = (page: Page) => page.locator('#holdings tbody tr').filter({ hasText: 'RY.TO' })

/** What a Refresh leaves behind (app/(app)/quotes.ts), set directly so the test never calls Yahoo. */
async function refreshedTo(page: Page, price: number) {
  const now = new Date().toISOString()
  const value = JSON.stringify({ fetchedAt: now, quotes: { 'stock:RY.TO': { price, currency: 'CAD', at: now } } })
  await page.context().addCookies([{ name: 'live_quotes', value: encodeURIComponent(value), url: 'http://127.0.0.1:3100' }])
}

test("without a refresh, holdings are valued at the last run's prices", async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Refresh prices' })).toBeVisible()
  await expect(page.locator('#live-prices')).toHaveCount(0)
  await expect(ry(page)).toContainText('1,000')
})

test("after a refresh, holdings are valued at the live price and the top bar says when", async ({ page }) => {
  await refreshedTo(page, 150)
  await page.goto('/')
  await expect(page.locator('#live-prices')).toContainText(/^Live prices \d{1,2}:\d{2}/)
  await expect(ry(page)).toContainText('1,500')
})

test('a malformed live-prices cookie is ignored', async ({ page }) => {
  await page.context().addCookies([{ name: 'live_quotes', value: 'garbage', url: 'http://127.0.0.1:3100' }])
  await page.goto('/')
  await expect(page.locator('#live-prices')).toHaveCount(0)
  await expect(ry(page)).toContainText('1,000')
})
