import { expect, test } from '@playwright/test'
import { resetData, seedAlert, seedPortfolio, seedSymbols } from './db'

const FEED = "What's new on your stocks"
const COPY = 'Alerts are checked on each run (about 3 a day), not live, and appear only here and on My Portfolio.'

test.beforeEach(async () => {
  await resetData()
  await seedPortfolio() // AAPL (US), RY.TO (TSX) held, ETH coin
  await seedSymbols([{ symbol: 'TSLA', market: 'US', name: 'Tesla, Inc.' }]) // not held or watched
})

test('add an alert on a US stock page, see it listed in USD, then delete it', async ({ page }) => {
  await page.goto('/ticker/AAPL')
  const card = page.getByRole('region', { name: 'Alerts' })
  await expect(card.getByText(COPY)).toBeVisible()
  await expect(card.getByText('Level (USD)')).toBeVisible()
  await card.getByLabel('Level (USD)').fill('250.5')
  await card.getByLabel('Note (optional)').fill('trim here')
  await card.getByRole('button', { name: 'Add alert' }).click()
  const row = card.getByTestId('alert-row')
  await expect(row).toHaveCount(1)
  await expect(row).toContainText('Above $250.50')
  await expect(row).toContainText('trim here')
  await expect(row).toContainText('USD')

  await row.getByRole('button', { name: /Delete/ }).click()
  await expect(card.getByTestId('alert-row')).toHaveCount(0)
})

test('a bad level shows an error and adds nothing', async ({ page }) => {
  await page.goto('/ticker/AAPL')
  const card = page.getByRole('region', { name: 'Alerts' })
  await card.getByLabel('Level (USD)').fill('0')
  await card.getByRole('button', { name: 'Add alert' }).click()
  await expect(card.getByText('Enter a price greater than zero.')).toBeVisible()
  await expect(card.getByTestId('alert-row')).toHaveCount(0)
})

test('a TSX stock alert is in CAD; a coin alert says it uses the USD price', async ({ page }) => {
  await page.goto('/ticker/RY.TO')
  await expect(page.getByRole('region', { name: 'Alerts' }).getByText('Level (CAD)')).toBeVisible()

  await page.goto('/ticker/ETH?asset=crypto')
  const card = page.getByRole('region', { name: 'Alerts' })
  await expect(card.getByText('Level (USD)')).toBeVisible()
  await expect(card.getByText('Coin alerts use the USD price.')).toBeVisible()
  await card.getByLabel('Level (USD)').fill('2500')
  await card.getByRole('button', { name: 'Add alert' }).click()
  await expect(card.getByTestId('alert-row')).toContainText('Above $2,500.00')
})

test('an alert on a coin does not show on a stock with the same symbol', async ({ page }) => {
  await seedAlert({ symbol: 'ETH', assetType: 'crypto', direction: 'below', level: 2000 })
  await page.goto('/ticker/ETH?asset=crypto')
  await expect(page.getByRole('region', { name: 'Alerts' }).getByTestId('alert-row')).toHaveCount(1)
  // the stock page with the same symbol does not list the coin's alert
  await page.goto('/ticker/ETH?asset=stock')
  await expect(page.getByRole('region', { name: 'Alerts' }).getByTestId('alert-row')).toHaveCount(0)
})

test('a sub-cent coin hit keeps its digits on My Portfolio', async ({ page }) => {
  await seedAlert({ symbol: 'ETH', assetType: 'crypto', direction: 'below', level: 0.00000123, hit: { hoursAgo: 1, price: 0.00000119 } })
  await page.goto('/')
  const item = page.getByRole('region', { name: FEED }).getByTestId('monitor-item')
  await expect(item).toContainText('crossed below $0.00000123 by the last run')
  await expect(item).toContainText('$0.00000119')
})

test('an unknown symbol is refused', async ({ page }) => {
  await page.goto('/ticker/AAPL')
  const card = page.getByRole('region', { name: 'Alerts' })
  await card.getByLabel('Level (USD)').fill('10')
  await card.locator('input[name="symbol"]').evaluate((el) => ((el as HTMLInputElement).value = 'ZZZZ'))
  await card.getByRole('button', { name: 'Add alert' }).click()
  await expect(card.getByText('ZZZZ is not a stock or coin this app knows.')).toBeVisible()
  await page.goto('/ticker/AAPL')
  await expect(page.getByRole('region', { name: 'Alerts' }).getByTestId('alert-row')).toHaveCount(0)
})

test('a hit alert on an unheld stock shows on My Portfolio, past the since window, until dismissed', async ({ page }) => {
  await seedAlert({ symbol: 'TSLA', direction: 'above', level: 400, hit: { hoursAgo: 24 * 20, price: 402.1 } })
  await seedAlert({ symbol: 'TSLA', direction: 'below', level: 100, hit: { hoursAgo: 5, price: 99 }, dismissed: true })

  await page.goto('/')
  const feed = page.getByRole('region', { name: FEED })
  const item = feed.getByTestId('monitor-item').filter({ hasText: 'crossed above $400.00 by the last run' })
  await expect(item).toHaveCount(1)
  await expect(item).toContainText('TSLA')
  await expect(item).toContainText('$402.10')
  await expect(feed.getByTestId('monitor-item')).toHaveCount(1)

  await item.getByRole('button', { name: 'Dismiss' }).click()
  await expect(feed.getByTestId('monitor-item')).toHaveCount(0)
  await page.reload()
  await expect(feed.getByText('Nothing new since the last run.')).toBeVisible()
})

test('a hit alert on the ticker page can be dismissed and then disappears', async ({ page }) => {
  await seedAlert({ symbol: 'TSLA', direction: 'above', level: 400, hit: { hoursAgo: 2, price: 402.1 } })
  await page.goto('/ticker/TSLA')
  const card = page.getByRole('region', { name: 'Alerts' })
  await expect(card.getByTestId('alert-row')).toContainText(/Crossed above \$400\.00 USD by the last run, at \$402\.10 on /)
  await card.getByRole('button', { name: 'Dismiss' }).click()
  await expect(card.getByTestId('alert-row')).toHaveCount(0)

  await page.goto('/')
  await expect(page.getByRole('region', { name: FEED }).getByText('Nothing new since the last run.')).toBeVisible()
})

test('the 21st active alert on an asset is refused', async ({ page }) => {
  for (let i = 1; i <= 20; i++) await seedAlert({ symbol: 'AAPL', direction: 'above', level: 300 + i })
  await page.goto('/ticker/AAPL')
  const card = page.getByRole('region', { name: 'Alerts' })
  await card.getByLabel('Level (USD)').fill('999')
  await card.getByRole('button', { name: 'Add alert' }).click()
  await expect(page.getByText(/already has 20 active alerts/)).toBeVisible()
  await expect(card.getByTestId('alert-row')).toHaveCount(20)
})
