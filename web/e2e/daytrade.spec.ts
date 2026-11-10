import { expect, test, type Page } from '@playwright/test'
import { nyTime } from '../lib/daytrade'
import { daysAgo, nyAt, resetData, seedDaytradeDay, seedDaytradeSignal, seedFx, sql, today } from './db'

const MIN = 60_000
const ago = (minutes: number) => new Date(Date.now() - minutes * MIN)
const cards = (page: Page) => page.getByTestId('daytrade-card')

/** The status line without a row for today, at New York's time now. */
function noRowLine() {
  const { weekday, minutes } = nyTime(new Date().toISOString())
  if (weekday === 'Sat' || weekday === 'Sun') return 'Market closed today.'
  return minutes < 9 * 60 + 50 ? 'Before 9:50 AM: the opening range is still forming.' : 'No scan has run yet today.'
}

const NOTES = [
  'Not financial advice. Nothing is ordered: you place trades yourself.',
  'Frequent day trading in a TFSA can be treated as a business, which makes the gains taxable (not tax advice).',
  "Yahoo's free 5-minute bars can lag a few minutes.",
]

test.beforeEach(resetData)

test('the top 3 show the plan, odds, history, cost, shares and headlines; the rest are listed', async ({ page }) => {
  await seedFx([daysAgo(1)], 1.4)
  await seedDaytradeDay({ status: 'scanning', lastUpdate: ago(1) })
  await seedDaytradeSignal({
    symbol: 'TGTX',
    name: 'TG Therapeutics',
    triggerAt: ago(2),
    entry: 67.65,
    stop: 66.05,
    rank: 1,
    netHistoryR: 0.29,
    flatBy: nyAt(today(), '12:55'), // as the pipeline stores it on a 1:00 PM close
    headlines: [
      { title: 'TG Therapeutics beats estimates', url: 'https://finance.yahoo.com/tgtx-1', published_at: ago(90).toISOString(), outlet: 'Reuters' },
      { title: 'TGTX second headline', url: 'https://finance.yahoo.com/tgtx-2', published_at: ago(120).toISOString(), outlet: 'Yahoo Finance' },
    ],
  })
  await seedDaytradeSignal({ symbol: 'RY', market: 'TSX', name: 'Royal Bank', triggerAt: ago(3), entry: 150, stop: 149.5, costPct: 0.1, rank: 2, netHistoryR: 0.2 })
  await seedDaytradeSignal({ symbol: 'NVDA', triggerAt: ago(4), entry: 100, stop: 40, rank: 3, netHistoryR: 0.1 })
  await seedDaytradeSignal({ symbol: 'AMD', triggerAt: ago(5), entry: 50, stop: 49, eligible: false, netHistoryR: -0.2, netReplayR: 0.1 })

  await page.goto('/daytrade')
  await expect(page.getByRole('heading', { name: 'Day trade', level: 1 })).toBeVisible()
  await expect(page.getByTestId('daytrade-status')).toHaveText(/^Scanning · last update \d{1,2}:\d{2} [AP]M ET( · next ~\d{1,2}:\d{2})?$/)
  await expect(cards(page)).toHaveCount(3)

  const first = cards(page).nth(0)
  await expect(first).toContainText('TGTX')
  await expect(first).toContainText('TG Therapeutics')
  await expect(first).toContainText(/Entry signal \d{1,2}:\d{2} [AP]M at US\$67\.65/)
  await expect(first.getByText('Fresh', { exact: true })).toBeVisible()
  await expect(first).toContainText('StopUS$66.05')
  await expect(first).toContainText('TargetUS$70.85')
  await expect(first).toContainText('Flat by12:55 PM')
  await expect(first).toContainText('10,000 replays: target first 34% · stop first 52% · neither 14% · green at close 48%')
  await expect(first).toContainText("This rule on TGTX's last 55 sessions: fired 37 times, 5 target, 20 stop; average +1.60R before costs")
  await expect(first).toContainText('Cost 3.10% round trip = 1.31R')
  // C$50 at 1.40 = US$35.71; US$1.60 a share at risk → 22 shares, C$49.28 at the stop
  await expect(first).toContainText('≈ 22 shares (risking ≈ C$49 at the stop)')
  await expect(first.getByRole('link', { name: 'TG Therapeutics beats estimates' })).toHaveAttribute('href', 'https://finance.yahoo.com/tgtx-1')
  await expect(first).toContainText('Open: no price since the signal yet')

  const second = cards(page).nth(1)
  await expect(second).toContainText('RY')
  await expect(second).toContainText('TSX')
  await expect(second).toContainText('StopC$149.50')
  await expect(second).toContainText('≈ 100 shares (risking ≈ C$50 at the stop)')
  await expect(second).toContainText('Flat by3:55 PM')
  await expect(cards(page).nth(2)).toContainText('Even one share risks more than your C$50 limit.')

  const table = page.getByRole('table', { name: 'Other signals today' })
  await expect(table.getByRole('row')).toHaveCount(5) // header + 4
  await expect(table.getByRole('row', { name: /AMD/ })).toContainText('History is −0.20R after costs')
  await expect(table.getByRole('row', { name: /TGTX/ })).toContainText('Top 3 (#1)')

  for (const note of NOTES) await expect(page.getByText(note)).toBeVisible()
  // nothing here places an order or links to a broker
  await expect(page.getByRole('button', { name: /buy|order|place/i })).toHaveCount(0)
})

test('a day with no eligible signal says no trade and still lists the signals', async ({ page }) => {
  await seedDaytradeDay({ status: 'done', lastUpdate: ago(30) })
  await seedDaytradeSignal({ symbol: 'AMD', triggerAt: ago(200), entry: 50, stop: 49, eligible: false, netHistoryR: -0.2 })
  await seedDaytradeSignal({
    symbol: 'SOFI',
    triggerAt: ago(150),
    entry: 10,
    stop: 9.9,
    eligible: false,
    netHistoryR: null,
    history: { skipped: 'only 4 full past session(s); need at least 20' },
  })

  await page.goto('/daytrade')
  await expect(page.getByTestId('daytrade-status')).toHaveText(/^Done for today · last update/)
  await expect(page.getByText('No signal today has a positive record after costs (2 signals checked).')).toBeVisible()
  await expect(cards(page)).toHaveCount(0)
  const table = page.getByRole('table', { name: 'Other signals today' })
  await expect(table.getByRole('row', { name: /AMD/ })).toContainText('History is −0.20R after costs')
  await expect(table.getByRole('row', { name: /SOFI/ })).toContainText('Not enough history: only 4 full past session(s); need at least 20')
})

test('a signal more than 10 minutes old is late and shows the latest price with its time', async ({ page }) => {
  await seedDaytradeDay({ status: 'scanning', lastUpdate: ago(1) })
  await seedDaytradeSignal({ symbol: 'TGTX', triggerAt: ago(30), entry: 67.65, stop: 66.05, rank: 1, lastPrice: 68.4, lastAt: ago(1) })

  await page.goto('/daytrade')
  const card = cards(page).first()
  await expect(card.getByText('Late: the price has moved since the signal; entering now is a different trade.')).toBeVisible()
  await expect(card).toContainText(/Last price US\$68\.40 at \d{1,2}:\d{2} [AP]M/)
  await expect(card.getByText('Fresh', { exact: true })).toHaveCount(0)
  await expect(card.getByText("Shares are sized from the signal's entry and stop.")).toBeVisible()
})

test('a failed day shows the reason and the last good update', async ({ page }) => {
  await seedDaytradeDay({ status: 'failed', lastUpdate: ago(20), error: 'Yahoo gave no data this cycle (12 of 12 symbols failed)' })

  await page.goto('/daytrade')
  await expect(page.getByTestId('daytrade-status')).toHaveText(
    /^Today's scan failed: Yahoo gave no data this cycle \(12 of 12 symbols failed\) · last update \d{1,2}:\d{2} [AP]M ET$/,
  )
})

test('without a row for today the line fits the time of day, and the track record is still shown', async ({ page }) => {
  // the line just before or just after the page loads, so a boundary (9:50, midnight) can't flake it
  const before = noRowLine()
  await page.goto('/daytrade')
  const after = noRowLine()
  const shown = (await page.getByTestId('daytrade-status').textContent()) ?? ''
  expect([before, after]).toContain(shown)
  await expect(page.getByRole('heading', { name: 'Track record' })).toBeVisible()
  await expect(page.getByText('No finished day-trade signals yet.')).toBeVisible()
})

test('a scanning day with no signal yet says so', async ({ page }) => {
  await seedDaytradeDay({ status: 'scanning', lastUpdate: ago(1) })
  await page.goto('/daytrade')
  await expect(page.getByText('No signals yet today.')).toBeVisible()
  await expect(page.getByText(/signals checked/)).toHaveCount(0)
})

test('finished days without a top-3 signal are counted', async ({ page }) => {
  for (const n of [1, 2, 3]) await seedDaytradeDay({ day: daysAgo(n), status: 'done', lastUpdate: ago(n * 1440) })
  await seedDaytradeSignal({ day: daysAgo(1), symbol: 'AMD', triggerAt: ago(1440), entry: 50, stop: 49, eligible: false, status: 'flat', netR: -0.3 })
  await page.goto('/daytrade')
  await expect(page.getByRole('region', { name: 'Track record' }).getByText('3 trading days, no top-3 signals.')).toBeVisible()
})

test('a closed day says the market is closed', async ({ page }) => {
  await seedDaytradeDay({ status: 'closed' })
  await page.goto('/daytrade')
  await expect(page.getByTestId('daytrade-status')).toHaveText('Market closed today.')
})

test('the track record counts the top-3 outcomes of finished days, after costs', async ({ page }) => {
  for (const n of [1, 2, 3]) await seedDaytradeDay({ day: daysAgo(n), status: 'done', lastUpdate: ago(n * 1440) })
  await seedDaytradeDay({ day: daysAgo(4), status: 'failed', lastUpdate: ago(4 * 1440) }) // not finished: left out
  const past = (n: number, symbol: string, status: 'open' | 'target' | 'stop' | 'flat', netR: number, rank: number | null = 1) =>
    seedDaytradeSignal({ day: daysAgo(n), symbol, triggerAt: ago(n * 1440), entry: 20, stop: 19, rank, status, netR })
  await past(1, 'AAA', 'target', 2.0)
  await past(1, 'BBB', 'stop', -1.0, 2)
  await past(2, 'CCC', 'flat', 0.2)
  await past(2, 'GGG', 'target', 1.0, null)
  await sql`update daytrade_signals set best_rank = 2 where symbol = 'GGG'` // shown #2, displaced later that day
  await past(2, 'DDD', 'stop', -1.1, null) // never top 3
  await past(3, 'EEE', 'stop', -1.0)
  await past(3, 'HHH', 'open', 0) // never finalized: counts nowhere
  await sql`update daytrade_signals set net_r = null where symbol = 'HHH'`
  await past(4, 'FFF', 'target', 1.9)

  await page.goto('/daytrade')
  const record = page.getByRole('region', { name: 'Track record' })
  await expect(record.getByText("Paper: what the rule's top-3 trades would have done, after costs.")).toBeVisible()
  const last20 = record.getByTestId('track-20')
  await expect(last20).toContainText('Last 20 trading days')
  await expect(last20).toContainText('5 signals')
  await expect(last20).toContainText('2 target · 2 stop · 1 flat')
  await expect(last20).toContainText('Average +0.24R') // (2.0 − 1.0 + 0.2 + 1.0 − 1.0) / 5
  await expect(last20).toContainText('Sum +1.20R')
  await expect(record.getByTestId('track-60')).toContainText('5 signals')
})

test('the page refreshes itself while the day is scanning', async ({ page }) => {
  await page.clock.install()
  await seedDaytradeDay({ status: 'scanning', lastUpdate: ago(1) })
  await page.goto('/daytrade')
  await expect(page.getByTestId('daytrade-status')).toHaveText(/^Scanning/)
  await sql`update daytrade_days set status = 'failed', error = 'the scan failed: test' where day = ${today()}`
  await page.clock.runFor(61_000)
  await expect(page.getByTestId('daytrade-status')).toHaveText(/^Today's scan failed: the scan failed: test/)
})

test('the sidebar reaches Day trade right after Invest', async ({ page }) => {
  await page.goto('/')
  const links = page.getByRole('complementary', { name: 'Main' }).getByRole('link')
  const names = await links.allInnerTexts()
  expect(names.indexOf('Day trade')).toBe(names.indexOf('Invest') + 1)
  await page.getByRole('complementary', { name: 'Main' }).getByRole('link', { name: 'Day trade' }).click()
  await expect(page.getByRole('heading', { name: 'Day trade', level: 1 })).toBeVisible()
})

test.describe('on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('the page is no wider than the screen', async ({ page }) => {
    await seedDaytradeDay({ status: 'scanning', lastUpdate: ago(1) })
    await seedDaytradeSignal({
      symbol: 'TGTX',
      name: 'TG Therapeutics Global Diversified Holdings and Trust Incorporated',
      triggerAt: ago(30),
      entry: 67.65,
      stop: 66.05,
      rank: 1,
      headlines: [{ title: `TGTX ${'quarterly-results-'.repeat(8)}beat`, url: 'https://finance.yahoo.com/x', published_at: ago(60).toISOString(), outlet: 'Reuters' }],
    })
    await seedDaytradeSignal({ symbol: 'AMD', triggerAt: ago(5), entry: 50, stop: 49, eligible: false, netHistoryR: -0.2 })
    // Day trade sits under More on a phone; the primary tabs stay as they were
    await page.goto('/')
    const tabs = page.getByRole('navigation', { name: 'Main' }).last()
    await expect(tabs.getByRole('link', { name: 'Day trade' })).toHaveCount(0)
    await tabs.getByRole('button', { name: 'More' }).click()
    await page.getByRole('dialog', { name: 'More' }).getByRole('link', { name: 'Day trade' }).click()
    await expect(page.getByRole('heading', { name: 'Day trade', level: 1 })).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow).toBeLessThanOrEqual(0)
  })
})

test.describe('settings', () => {
  test('save the day-trade max loss and spread, and name a value out of range', async ({ page }) => {
    await page.goto('/settings')
    const maxLoss = page.getByLabel(/Day-trade max loss per trade \(C\$\)/)
    const spread = page.getByLabel(/Day-trade spread, round trip \(%\)/)
    await expect(maxLoss).toHaveValue('50')
    await expect(spread).toHaveValue('0.1')
    await maxLoss.fill('0')
    await spread.fill('6')
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('Enter a max loss above C$0, up to C$100,000.')).toBeVisible()
    await expect(page.getByText('Enter a spread from 0 to 5%.')).toBeVisible()

    await maxLoss.fill('75')
    await spread.fill('0.25')
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByRole('status')).toHaveText('Settings saved: they apply from the next run')
    const [row] = await sql`select daytrade_max_loss_cad::float as loss, daytrade_spread_pct::float as spread from settings`
    expect(row).toEqual({ loss: 75, spread: 0.25 })
    await page.reload()
    await expect(page.getByLabel(/Day-trade max loss per trade/)).toHaveValue('75')
  })
})
