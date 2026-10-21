import { expect, test } from '@playwright/test'
import { daysAgo, resetData, seedCloses, seedCoins, seedFx, seedSymbols, sql } from './db'

test.beforeEach(resetData)

test.describe('watchlist', () => {
  test('adds a stock picked by name, marks it as watched in the list, and removes it', async ({ page }) => {
    await seedSymbols([
      { symbol: 'SHOP', market: 'US', name: 'Shopify Inc. Class A Subordinate Voting Shares' },
      { symbol: 'SHOP.TO', market: 'TSX', name: 'Shopify Inc.' },
    ])
    await seedCloses('SHOP.TO', 'stock', 'CAD', [daysAgo(1)], 141.25, 0)
    await page.goto('/watchlist')
    await expect(page.getByRole('heading', { name: 'Watching 0' })).toBeVisible()

    const box = page.getByRole('combobox', { name: 'Symbol', exact: true })
    const options = page.getByRole('listbox', { name: 'Symbol', exact: true }).getByRole('option')
    await box.fill('shopi')
    await expect(options).toHaveText(['SHOP.TOShopify Inc.TSX', 'SHOPShopify Inc.US']) // TSX first, share class dropped
    await expect(options.first().locator('b')).toHaveText('Shopi')
    await options.first().click()
    await expect(page.getByRole('status')).toHaveText('SHOP.TO added to the watchlist')
    await expect(page.getByRole('heading', { name: 'Watching 1' })).toBeVisible()
    await expect(page.locator('.watch-row')).toContainText('Shopify Inc.')
    await expect(page.locator('.watch-row')).toContainText('C$141.25')
    await expect(box).toHaveValue('')

    await box.fill('shop')
    await expect(options.first()).toHaveText('SHOP.TOShopify Inc.On your watchlist')
    await expect(options.first()).toHaveAttribute('aria-disabled', 'true')
    await expect(options.nth(1)).toHaveAttribute('aria-selected', 'true') // the first row that can be picked
    await page.keyboard.press('Enter')
    await expect(page.getByRole('status')).toHaveText('SHOP added to the watchlist')
    await expect(page.getByRole('heading', { name: 'Watching 2' })).toBeVisible()

    await page.getByRole('button', { name: 'Remove SHOP.TO' }).click()
    await expect(page.getByRole('status')).toHaveText('SHOP.TO removed from the watchlist')
    await expect(page.getByRole('heading', { name: 'Watching 1' })).toBeVisible()
    expect(await sql`select symbol from watchlist`).toEqual([{ symbol: 'SHOP' }])
  })

  test('adds a coin by name, shown in CAD, and takes nothing that is not in the lists', async ({ page }) => {
    await seedCoins([
      { symbol: 'SOL', name: 'Solana', marketCap: 8e10 },
      { symbol: 'JUP', name: 'Jupiter', marketCap: 1e9 },
      { symbol: 'LINK', name: 'Chainlink', marketCap: 9e9 },
    ])
    await seedSymbols([{ symbol: 'LINK', market: 'US', name: 'Interlink Electronics, Inc. - Common Stock' }])
    await seedFx([daysAgo(1)], 1.4)
    await seedCloses('SOL', 'crypto', 'USD', [daysAgo(1)], 200, 0)
    await page.goto('/watchlist')
    const box = page.getByRole('combobox', { name: 'Symbol', exact: true })
    await box.fill('sol')
    await expect(page.getByRole('option')).toHaveText(['SOLSolanaCrypto'])
    await page.keyboard.press('Enter')
    await expect(page.locator('.watch-row').filter({ hasText: 'SOL' })).toContainText('C$280.00')

    await box.fill('link') // both a stock and a coin: Enter asks rather than guesses
    await page.keyboard.press('Enter')
    await expect(page.locator('.combo-note')).toHaveText('LINK is both a stock and a coin. Pick one with the arrows or a click.')
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('Enter')
    await expect(page.getByRole('status')).toHaveText('LINK added to the watchlist')

    await box.fill('Vanguard S&P 500')
    await expect(page.locator('.combo-note')).toHaveText('No listed stock or coin matches.')
    await page.keyboard.press('Enter')
    await expect(page.getByText('Pick a stock or coin from the list.')).toBeVisible()
    await box.fill('Vanguard S&P 50')
    await expect(page.getByText('Pick a stock or coin from the list.')).toBeHidden() // editing clears it
    expect(await sql`select symbol, asset_type from watchlist order by symbol`).toEqual([
      { symbol: 'LINK', asset_type: 'crypto' },
      { symbol: 'SOL', asset_type: 'crypto' },
    ])
  })
})

test.describe('with the device clock an hour ahead of the server', () => {
  test.beforeEach(async ({ page }) => {
    await page.clock.setFixedTime(new Date(Date.now() + 3_600_000))
  })

  test('a fee out of range shows its error', async ({ page }) => {
    await page.goto('/settings')
    await page.getByLabel(/USD conversion fee/).fill('12')
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('Enter a fee from 0 to 10%.')).toBeVisible()
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
