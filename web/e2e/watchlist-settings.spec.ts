import { expect, test } from '@playwright/test'
import { daysAgo, resetData, seedCloses, seedFx, seedSymbols, sql } from './db'

test.beforeEach(resetData)

test.describe('watchlist', () => {
  test('adds a TSX stock without its suffix, refuses a duplicate, and removes it', async ({ page }) => {
    await seedSymbols([{ symbol: 'SHOP.TO', market: 'TSX', name: 'Shopify Inc.' }])
    await seedCloses('SHOP.TO', 'stock', 'CAD', [daysAgo(1)], 141.25, 0)
    await page.goto('/watchlist')
    await expect(page.getByRole('heading', { name: 'Watching 0' })).toBeVisible()

    await page.getByLabel('Symbol', { exact: true }).fill('shop')
    await page.getByLabel('Type').selectOption('TSX stock')
    await page.getByRole('button', { name: 'Add' }).click()
    await expect(page.getByRole('status')).toHaveText('SHOP.TO added to the watchlist')
    await expect(page.getByRole('heading', { name: 'Watching 1' })).toBeVisible()
    await expect(page.locator('.watch-row')).toContainText('Shopify Inc.')
    await expect(page.locator('.watch-row')).toContainText('C$141.25')
    await expect(page.getByLabel('Symbol', { exact: true })).toHaveValue('')

    await page.getByLabel('Symbol', { exact: true }).fill('SHOP.TO')
    await page.getByRole('button', { name: 'Add' }).click()
    await expect(page.getByText('SHOP.TO is already on the watchlist.')).toBeVisible()

    await page.getByRole('button', { name: 'Remove SHOP.TO' }).click()
    await expect(page.getByRole('status')).toHaveText('SHOP.TO removed from the watchlist')
    await expect(page.getByRole('heading', { name: 'Watching 0' })).toBeVisible()
    expect(await sql`select 1 from watchlist`).toHaveLength(0)
  })

  test('shows a coin in CAD and an unlisted stock with a note', async ({ page }) => {
    await seedFx([daysAgo(1)], 1.4)
    await seedCloses('SOL', 'crypto', 'USD', [daysAgo(1)], 200, 0)
    await page.goto('/watchlist')
    await page.getByLabel('Symbol', { exact: true }).fill('sol')
    await page.getByLabel('Type').selectOption('Crypto')
    await page.getByRole('button', { name: 'Add' }).click()
    await expect(page.locator('.watch-row').filter({ hasText: 'SOL' })).toContainText('C$280.00')

    await page.getByLabel('Symbol', { exact: true }).fill('VFV')
    await page.getByLabel('Type').selectOption('TSX stock')
    await page.getByRole('button', { name: 'Add' }).click()
    await expect(page.getByRole('status')).toHaveText("VFV.TO added. It isn't in the stock lists; the next run will try Yahoo.")
    await expect(page.locator('.watch-row').filter({ hasText: 'VFV.TO' })).toContainText('next run')
  })
})

test.describe('settings', () => {
  test('saves costs and guidelines, and names a value out of range', async ({ page }) => {
    await page.goto('/settings')
    const fee = page.getByLabel(/USD conversion fee/)
    await expect(fee).toHaveValue('1.5')
    await fee.fill('12')
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('Enter a fee from 0 to 10%.')).toBeVisible()

    await fee.fill('1.25')
    await page.getByLabel(/Short holds/).fill('40')
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByRole('status')).toHaveText('Settings saved: they apply from the next run')
    const [row] = await sql`select usd_fx_fee_pct::float as fee, tfsa_short_hold_share_warn::float as share from settings`
    expect(row).toEqual({ fee: 1.25, share: 0.4 })

    await page.reload()
    await expect(page.getByLabel(/USD conversion fee/)).toHaveValue('1.25')
    await expect(page.getByLabel(/Short holds/)).toHaveValue('40')
  })

  test('the theme choice sticks on this device', async ({ page }) => {
    await page.goto('/settings')
    await page.getByRole('tab', { name: 'Dark' }).click()
    await expect(page.locator('html')).toHaveClass(/\bdark\b/)
    await page.reload()
    await expect(page.getByRole('tab', { name: 'Dark' })).toHaveAttribute('aria-selected', 'true')
    await page.getByRole('tab', { name: 'Light' }).click()
    await expect(page.locator('html')).not.toHaveClass(/\bdark\b/)
  })
})
