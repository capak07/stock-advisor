import { expect, test, type Page } from '@playwright/test'
import { longDay } from '../lib/dates'
import { daysAgo, resetData, seedLot, seedSell, sql } from './db'

test.beforeEach(resetData)

const rows = (page: Page) => page.locator('#trades tbody tr')
const lot = (qty: number, day: string) =>
  seedLot({ account: 'tfsa', symbol: 'RY.TO', asset_type: 'stock', qty, price: 170, currency: 'CAD', bought_at: day })

test('a mistaken buy is deleted from the trade list', async ({ page }) => {
  await lot(10, daysAgo(30))
  await page.goto('/')
  await expect(rows(page)).toHaveCount(1)
  await expect(rows(page)).toContainText('RY.TO')
  await expect(rows(page)).toContainText('1,700')

  await page.getByRole('button', { name: `Delete the buy of 10 RY.TO on ${longDay(daysAgo(30))}` }).click()
  await expect(page.getByText("This can't be undone.")).toBeVisible()
  await page.getByRole('button', { name: 'Delete', exact: true }).click()

  await expect(page.getByRole('status')).toHaveText('Buy deleted: 10 RY.TO')
  await expect(page.getByText('No holdings yet. Add your first buy to start.')).toBeVisible()
  await expect(page.locator('#trades')).toHaveCount(0)
  expect(await sql`select 1 from lots`).toHaveLength(0)
})

test('deleting a buy that a later sell needs says so first, and Keep keeps it', async ({ page }) => {
  await lot(10, daysAgo(40))
  await lot(5, daysAgo(30))
  await seedSell({ account: 'tfsa', symbol: 'RY.TO', asset_type: 'stock', qty: 12, price: 180, currency: 'CAD', sold_at: daysAgo(10) })
  await page.goto('/')
  await expect(rows(page)).toHaveCount(3)
  await expect(rows(page).first()).toContainText('Sell')

  await page.getByRole('button', { name: `Delete the buy of 5 RY.TO on ${longDay(daysAgo(30))}` }).click()
  await expect(page.getByText('Later sells of RY.TO would then exceed what you held.')).toBeVisible()
  await page.getByRole('button', { name: 'Keep' }).click()
  await expect(page.getByText('Later sells of RY.TO would then exceed what you held.')).toHaveCount(0)
  expect(await sql`select 1 from lots`).toHaveLength(2)
})

test('the latest ten trades show until all are asked for', async ({ page }) => {
  for (let i = 1; i <= 12; i += 1) await lot(1, daysAgo(40 - i))
  await page.goto('/')
  await expect(rows(page)).toHaveCount(10)
  await expect(rows(page).first()).toContainText(longDay(daysAgo(28)))
  await page.getByRole('button', { name: 'Show all 12' }).click()
  await expect(rows(page)).toHaveCount(12)
})
