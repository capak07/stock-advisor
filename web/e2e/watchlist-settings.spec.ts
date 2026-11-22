import { expect, test } from '@playwright/test'
import {
  daysAgo,
  resetData,
  seedCloses,
  seedCoins,
  seedFeatures,
  seedFx,
  seedHoldingAction,
  seedModel,
  seedPick,
  seedPrediction,
  seedRun,
  seedSymbols,
  seedVerdict,
  sql,
} from './db'

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

  test('watchlist rows show each verdict and why, with the chance, horizon and likely range when the run forecast it', async ({ page }) => {
    await seedSymbols([
      { symbol: 'AAPL', market: 'US', name: 'Apple Inc.' },
      { symbol: 'TD.TO', market: 'TSX', name: 'Toronto-Dominion Bank' },
    ])
    await sql`insert into watchlist (symbol, asset_type) values ('AAPL', 'stock'), ('TD.TO', 'stock'), ('SOL', 'crypto')`
    const runId = await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
    await seedVerdict(runId, {
      symbol: 'AAPL',
      assetType: 'stock',
      verdict: 'buy',
      reasons: ['P(beat SPY) 0.64 over 10 trading days', 'expected 2.4% against 3.1% round-trip costs'],
      details: { style: 'swing', horizon: 10, exit_by: '2026-10-30', rank: 2, market_picks_enabled: true },
    })
    await seedVerdict(runId, {
      symbol: 'TD.TO',
      assetType: 'stock',
      verdict: 'avoid',
      reasons: ['P(beat XIU.TO) 0.38 over 5 trading days'],
      details: { market_picks_enabled: true },
    })
    // TD.TO's Avoid was judged at 5 days (its reason says so): its outlook is at 5, not 21; AAPL was not forecast this run
    for (const [horizon, p] of [[5, 0.38], [21, 0.52], [63, 0.41]] as const) {
      await seedPrediction(runId, 'TD.TO', horizon, { q10: -0.064, q50: -0.01, q90: 0.071, p })
    }
    // SOL the stock is not watched; SOL the coin was added after the run, so it waits for its verdict
    await seedPrediction(runId, 'SOL', 21, { q10: -0.1, q50: 0, q90: 0.1, p: 0.5 }, 'stock')
    await seedPrediction(runId, 'SOL', 10, { q10: -0.1, q50: 0, q90: 0.1, p: 0.5 }, 'crypto')
    await seedCloses('TD.TO', 'stock', 'CAD', [daysAgo(2), daysAgo(1)], 80, 0.4)
    await page.goto('/watchlist')
    await expect(page.getByText(/^verdicts from the \d\d:\d\d run$/)).toBeVisible()
    await expect(page.getByText('Verdicts appear once the model runs')).toHaveCount(0)

    const aapl = page.locator('.watch-row', { hasText: 'AAPL' })
    await expect(aapl.locator('.chip')).toHaveText('Buy')
    await expect(aapl.locator('.w-detail')).toHaveText(
      "Swing · hold ~10 trading days · exit by Oct 30 · 64% to beat SPY · also today's #2 US pick",
    )
    await expect(aapl.locator('.w-odds')).toHaveCount(0)
    const td = page.locator('.watch-row', { hasText: 'TD.TO' })
    await expect(td.locator('.chip')).toHaveText('Avoid')
    await expect(td.locator('.w-odds')).toHaveText('38% to beat XIU.TO over 5 days')
    await expect(td.locator('.range-lab')).toHaveText('−6.4%likely 5-day range+7.1%')
    await expect(td.getByRole('img', { name: /^Likely range relative to XIU\.TO/ })).toBeVisible()
    await expect(td.locator('.w-price')).toHaveText('C$80.40')
    await expect(td.locator('.w-move')).toHaveText('+0.5%')
    await expect(td.locator('.w-detail')).toHaveText('P(beat XIU.TO) 0.38 over 5 trading days')
    // added after the run: no verdict yet
    const sol = page.locator('.watch-row', { hasText: 'SOL' })
    await expect(sol.locator('.chip')).toHaveText('New')
    await expect(sol.locator('.w-detail')).toHaveText('Gets its first verdict at the next run')
    await expect(sol.locator('.w-odds')).toHaveCount(0)
  })

  test('a watched US stock in the bottom tenth of the run shows Low model rank beside its verdict', async ({ page }) => {
    await seedSymbols([
      { symbol: 'AAPL', market: 'US', name: 'Apple Inc.' },
      { symbol: 'MSFT', market: 'US', name: 'Microsoft Corporation' },
    ])
    await sql`insert into watchlist (symbol, asset_type) values ('AAPL', 'stock'), ('MSFT', 'stock')`
    const runId = await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
    for (const symbol of ['AAPL', 'MSFT']) {
      await seedVerdict(runId, {
        symbol,
        assetType: 'stock',
        verdict: 'hold',
        reasons: ["doesn't qualify as a buy", 'P(beat SPY) 0.47 is under 0.58 at every horizon'],
        details: { market_picks_enabled: false },
      })
    }
    await sql`insert into screen_ranks (run_id, symbol, market, pct, low, scored)
              values (${runId}, 'AAPL', 'US', 0.04, true, 3712), (${runId}, 'MSFT', 'US', 0.80, false, 3712)`
    await page.goto('/watchlist')
    const aapl = page.locator('.watch-row', { hasText: 'AAPL' })
    await expect(aapl.locator('.chip.hold')).toHaveText('Hold')
    const flag = aapl.locator('.chip.low-rank')
    await expect(flag).toHaveText('Low model rank')
    await expect(flag).toHaveAttribute('title', /Bottom 10% of the model’s ranking of 3,712 US stocks/)
    await expect(page.locator('.watch-row', { hasText: 'MSFT' }).locator('.chip.low-rank')).toHaveCount(0)
  })

  test("a watched symbol you hold shows My Portfolio's action, on the Watchlist and on Picks", async ({ page }) => {
    await seedSymbols([
      { symbol: 'XRPN', market: 'US', name: 'XRPN Corp.' },
      { symbol: 'VEEA', market: 'US', name: 'Veea Inc.' },
    ])
    await sql`insert into watchlist (symbol, asset_type) values ('XRPN', 'stock'), ('VEEA', 'stock')`
    const runId = await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
    const hold = ["doesn't qualify as a buy", 'P(beat SPY) 0.45 is under 0.58 at every horizon']
    for (const symbol of ['XRPN', 'VEEA']) {
      await seedVerdict(runId, { symbol, assetType: 'stock', verdict: 'hold', reasons: hold, details: { market_picks_enabled: false } })
    }
    // XRPN is held and closed under its trailing stop; VEEA isn't held
    await seedHoldingAction(runId, {
      account: 'tfsa',
      symbol: 'XRPN',
      asset_type: 'stock',
      action: 'sell',
      reasons: ['closed at 14.71, under its trailing stop 31.35'],
      trailing_stop: 31.35,
    })
    for (const symbol of ['XRPN', 'VEEA']) await seedPrediction(runId, symbol, 21, { q10: -0.08, q50: 0, q90: 0.07, p: 0.48 })

    await page.goto('/watchlist')
    const xrpn = page.locator('.watch-row', { hasText: 'XRPN' })
    await expect(xrpn.locator('.chip')).toHaveText('Sell')
    await expect(xrpn.locator('.w-detail')).toHaveText('You hold it · Closed at 14.71, under its trailing stop 31.35')
    await expect(xrpn.getByText('% to beat')).toHaveCount(0) // held: My Portfolio's action, no chance
    await expect(xrpn.locator('.range')).toHaveCount(0)
    const veea = page.locator('.watch-row', { hasText: 'VEEA' })
    await expect(veea.locator('.chip')).toHaveText('No clear edge') // a Hold with a forecast, in words
    await expect(veea.locator('.w-odds')).toHaveText('48% to beat SPY over 21 days')
    await expect(veea.locator('.w-detail')).toContainText("doesn't qualify as a buy")

    // Picks lists the run's verdicts under its picks (a run without picks links to the Watchlist instead)
    await seedModel('stock_us', { picks_enabled: true })
    await seedPrediction(runId, 'AAPL', 63, { q10: -0.02, q50: 0.04, q90: 0.1, p: 0.62 })
    await seedPick(runId, { symbol: 'AAPL', market: 'US', style: 'position', horizon: 63, rank: 1, exitBy: '2027-01-19', entry: 200, stop: 180, riskLevel: 'medium', maxPct: 3 })
    await page.goto('/picks')
    const verdicts = page.locator('.card', { has: page.getByRole('heading', { name: 'Watchlist verdicts' }) })
    await expect(verdicts.locator('.verdict', { hasText: 'XRPN' }).locator('.chip')).toHaveText('Sell')
    await expect(verdicts.locator('.verdict', { hasText: 'XRPN' })).toContainText('You hold it · Closed at 14.71, under its trailing stop 31.35')
    await expect(verdicts.locator('.verdict', { hasText: 'VEEA' }).locator('.chip')).toHaveText('Hold')
  })

  test('a watched Buy says how to place it, sized at C$1,000 with nothing held', async ({ page }) => {
    await seedSymbols([{ symbol: 'TD.TO', market: 'TSX', name: 'Toronto-Dominion Bank' }])
    await sql`insert into watchlist (symbol, asset_type) values ('TD.TO', 'stock')`
    const runId = await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
    await seedFeatures(runId, 'TD.TO', 'stock', { atr_14_pct: 0.02, log_adv20: Math.log1p(5e6) })
    await seedVerdict(runId, {
      symbol: 'TD.TO',
      assetType: 'stock',
      verdict: 'buy',
      reasons: ['P(beat XIU.TO) 0.62 over 10 trading days', 'expected 2.0% against 0.3% round-trip costs'],
      details: { style: 'swing', horizon_days: 10, exit_by: '2026-11-10', rank: 1, entry_ref_price: 80, stop: 74, max_position_pct: 3, market_picks_enabled: true },
    })
    await seedPrediction(runId, 'TD.TO', 10, { q10: -0.03, q50: 0.02, q90: 0.06, p: 0.62 })
    await seedPrediction(runId, 'TD.TO', 21, { q10: -0.05, q50: 0.03, q90: 0.2, p: 0.55 }) // another horizon, not the Buy's
    await page.goto('/watchlist')
    const row = page.locator('.watch-row', { hasText: 'TD.TO' })
    await expect(row.locator('.w-detail')).toHaveText("Swing · hold ~10 trading days · exit by Nov 10 · 62% to beat XIU.TO · also today's #1 TSX pick")
    // the outlook at the Buy's horizon, not the 21 days a Hold would get
    await expect(row.locator('.chip.buy')).toHaveText('Buy')
    await expect(row.locator('.w-odds')).toHaveText('62% to beat XIU.TO over 10 days')
    await expect(row.locator('.range-lab')).toHaveText('−3.0%likely 10-day range+6.0%')
    const guide = row.locator('.order-guide')
    await expect(guide.locator('summary')).toContainText('How to place it · for C$1,000')
    await guide.locator('summary').click()
    await expect(guide).toContainText('How to place it · for C$1,000')
    // C$1,000 at C$80.40 is 12 shares and C$35 left over, bought as a fraction
    await expect(guide).toContainText(/Limit buy 12 sh at C\$80\.40 · (Day order|set it to expire at the end of the next trading day)/)
    await expect(guide).toContainText('Market buy C$35')
    await expect(guide).toContainText('Then a stop-limit sell 12 sh: stop C$74.00, limit C$73.26, expiry 90 days')
    // take-profit at the 10-day range's top, C$80 × 1.06
    await expect(guide).toContainText(
      /Or as one bracket order: limit buy 12 sh at C\$80\.40 · (Day order|set it to expire at the end of the next trading day), take profit C\$84\.80 \(\+5%\), stop loss C\$74\.00 \(−8%\)/,
    )
    await expect(guide).toContainText('A bracket covers whole shares only; the fraction stays a separate market buy.')
    await expect(page.getByText("Order guidance is a rule of thumb for Wealthsimple's order types, not a price forecast.")).toBeVisible()
  })

  test("a held watched stock's verdict says it is held", async ({ page }) => {
    await seedSymbols([{ symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' }])
    await sql`insert into watchlist (symbol, asset_type) values ('RY.TO', 'stock')`
    const runId = await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
    await seedVerdict(runId, {
      symbol: 'RY.TO',
      assetType: 'stock',
      verdict: 'buy',
      reasons: ['P(beat XIU.TO) 0.61 over 63 trading days', 'expected 3.0% against 0.3% round-trip costs'],
      details: { style: 'position', horizon_days: 63, exit_by: '2027-01-19', held: true, market_picks_enabled: true },
    })
    await page.goto('/watchlist')
    const row = page.locator('.watch-row', { hasText: 'RY.TO' })
    await expect(row.locator('.chip')).toHaveText('Buy')
    await expect(row.locator('.w-detail')).toHaveText('Position · hold ~3 months · exit by Jan 19 · 61% to beat XIU.TO · you hold it')
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
