import { expect, test, type Page } from '@playwright/test'
import { daysAgo, resetData, seedFx, seedLot, seedSymbols, sql } from './db'

test.beforeEach(resetData)

const holdings = (page: Page) => page.locator('#holdings tbody tr')

async function openBuy(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Buy' }).click()
  return page.getByRole('dialog', { name: 'Add a buy' })
}

test('a buy is saved and shows up as a holding', async ({ page }) => {
  await seedSymbols([{ symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' }])
  const drawer = await openBuy(page)
  await drawer.getByLabel('Symbol').fill('ry.to')
  await expect(drawer.getByLabel('Price (CAD)')).toBeVisible()
  await expect(drawer.getByLabel('USD/CAD rate')).toHaveCount(0)
  await drawer.getByLabel('Quantity').fill('10')
  await drawer.getByLabel('Price (CAD)').fill('184.50')
  await drawer.getByRole('button', { name: 'Save buy' }).click()

  await expect(page.getByRole('status')).toHaveText('Buy saved: 10 RY.TO in TFSA')
  await expect(drawer).toBeHidden()
  await expect(holdings(page).filter({ hasText: 'RY.TO' })).toContainText('No close yet; at cost')
  const [lot] = await sql`select symbol, qty::float as qty, price::float as price, currency, fx_rate_cad from lots`
  expect(lot).toEqual({ symbol: 'RY.TO', qty: 10, price: 184.5, currency: 'CAD', fx_rate_cad: null })
})

test('a US buy uses the Bank of Canada rate unless another is entered', async ({ page }) => {
  await seedSymbols([{ symbol: 'AAPL', market: 'US', name: 'Apple Inc.' }])
  await seedFx([daysAgo(3)], 1.3712)
  const drawer = await openBuy(page)
  await drawer.getByLabel('Symbol').fill('AAPL')
  await expect(drawer.getByLabel('USD/CAD rate')).toHaveValue('1.3712')
  await drawer.getByLabel('Quantity').fill('2')
  await drawer.getByLabel('Price (USD)').fill('180')
  await drawer.getByLabel('USD/CAD rate').fill('1.3918')
  await drawer.getByRole('button', { name: 'Save buy' }).click()
  await expect(page.getByRole('status')).toHaveText('Buy saved: 2 AAPL in TFSA')
  const [lot] = await sql`select currency, fx_rate_cad::float as rate from lots`
  expect(lot).toEqual({ currency: 'USD', rate: 1.3918 })
})

test('mistakes are named and what was typed stays', async ({ page }) => {
  const drawer = await openBuy(page)
  await drawer.getByLabel('Symbol').fill('RY.TO')
  await drawer.getByLabel('Quantity').fill('0')
  await drawer.getByLabel('Price (CAD)').fill('184')
  await drawer.getByRole('button', { name: 'Save buy' }).click()
  await expect(drawer.getByText('Enter a quantity above 0.')).toBeVisible()
  await expect(drawer.getByLabel('Price (CAD)')).toHaveValue('184')
  await expect(drawer.getByLabel('Symbol')).toHaveValue('RY.TO')
  expect(await sql`select 1 from lots`).toHaveLength(0)
})

test('a stock missing from the lists needs a second look', async ({ page }) => {
  const drawer = await openBuy(page)
  await drawer.getByLabel('Symbol').fill('XEQT.TO')
  await drawer.getByLabel('Quantity').fill('20')
  await drawer.getByLabel('Price (CAD)').fill('35')
  await drawer.getByRole('button', { name: 'Save buy' }).click()
  await expect(drawer.getByText(/XEQT\.TO isn't in the US or TSX stock lists/)).toBeVisible()
  expect(await sql`select 1 from lots`).toHaveLength(0)

  await drawer.getByLabel('Save it anyway').check()
  await drawer.getByRole('button', { name: 'Save buy' }).click()
  await expect(page.getByRole('status')).toHaveText('Buy saved: 20 XEQT.TO in TFSA')
})

test('a sell shows its gain at average cost and reduces the holding', async ({ page }) => {
  await seedSymbols([{ symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' }])
  await seedLot({ account: 'tfsa', symbol: 'RY.TO', asset_type: 'stock', qty: 10, price: 170, currency: 'CAD', bought_at: daysAgo(30) })
  await page.goto('/')
  await page.getByRole('button', { name: 'Sell' }).click()
  const drawer = page.getByRole('dialog', { name: 'Add a sell' })
  await expect(drawer.getByLabel('Holding')).toHaveValue('tfsa:stock:RY.TO')
  await expect(drawer.getByLabel('Quantity')).toHaveValue('10')
  await drawer.getByLabel('Quantity').fill('4')
  await drawer.getByLabel('Price (CAD)').fill('180')
  // 4 × (180 − 170) = +C$40, sheltered in the TFSA.
  await expect(drawer.getByText('+C$40 realized')).toBeVisible()
  await expect(drawer.getByText(/In a TFSA, gains and losses aren't taxed/)).toBeVisible()

  await drawer.getByLabel('Quantity').fill('11')
  await drawer.getByRole('button', { name: 'Save sell' }).click()
  await expect(drawer.getByText('You hold 10 in your TFSA.')).toBeVisible()

  await drawer.getByLabel('Quantity').fill('4')
  await drawer.getByRole('button', { name: 'Save sell' }).click()
  await expect(page.getByRole('status')).toHaveText('Sell saved: 4 RY.TO from TFSA')
  await expect(holdings(page).filter({ hasText: 'RY.TO' })).toBeVisible()
  const [held] = await sql`select (select sum(qty) from lots) - (select sum(qty) from sells) as qty`
  expect(Number(held.qty)).toBe(6)
})
