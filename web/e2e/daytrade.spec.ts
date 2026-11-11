import { expect, test, type Page } from '@playwright/test'
import { nyTime } from '../lib/daytrade'
import { daysAgo, nyAt, resetData, seedDaytradeDay, seedDaytradeSignal, seedFx, sql, today } from './db'

const MIN = 60_000
const ago = (minutes: number) => new Date(Date.now() - minutes * MIN)
const skillSection = (page: Page) => page.getByRole('region', { name: "The skill's top 3" })
const costSection = (page: Page) => page.getByRole('region', { name: 'Top 3 after your costs' })
/** The after-costs top 3's cards. */
const cards = (page: Page) => costSection(page).getByTestId('daytrade-card')
const skillCards = (page: Page) => skillSection(page).getByTestId('daytrade-card')
const SKILL_SUB = 'Strongest volume-confirmed breakouts at the first scan, among the most traded stocks. Before your costs.'

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

test("the skill's top 3 come first, with their strength and round-trip cost, then the top 3 after costs", async ({ page }) => {
  await seedFx([daysAgo(1)], 1.4)
  await seedDaytradeDay({ status: 'scanning', lastUpdate: ago(1) })
  // the skill's three, seeded out of rank order: none of them is eligible after costs
  await seedDaytradeSignal({ symbol: 'AFRM', name: 'Affirm', triggerAt: ago(40), entry: 60.3, orHigh: 60, stop: 59.5, costR: 2.26, skillRank: 3, eligible: false, netHistoryR: -0.4 })
  await seedDaytradeSignal({
    symbol: 'FIS',
    name: 'Fidelity National Information Services',
    triggerAt: ago(45),
    entry: 68.12,
    orHigh: 67.5,
    stop: 67,
    costR: 1.36,
    skillRank: 1,
    eligible: false,
    netHistoryR: -0.1,
    status: 'target',
    exitAt: ago(10),
    exitPrice: 70.36,
    grossR: 2,
    netR: 0.64,
  })
  await seedDaytradeSignal({ symbol: 'ERAS', name: 'Erasca', triggerAt: ago(44), entry: 3.05, orHigh: 3, stop: 2.95, costR: 0.95, skillRank: 2, eligible: false, netHistoryR: -0.2 })
  await seedDaytradeSignal({ symbol: 'OGC.TO', market: 'TSX', name: 'OceanaGold', triggerAt: ago(35), entry: 5.5, stop: 5.4, costPct: 0.1, rank: 1, netHistoryR: 0.4 })

  await page.goto('/daytrade')
  // the page's order: status line, the skill's top 3, the top 3 after costs, other signals, track record
  const status = await page.getByTestId('daytrade-status').boundingBox()
  const skillTop = await skillSection(page).boundingBox()
  expect(status!.y).toBeLessThan(skillTop!.y)
  const headings = await page.getByRole('heading', { level: 2 }).allInnerTexts()
  expect(headings.map((h) => h.trim())).toEqual(["The skill's top 3", 'Top 3 after your costs', 'Other signals today', 'Track record'])
  await expect(skillSection(page).getByText(SKILL_SUB, { exact: true })).toBeVisible()

  await expect(skillCards(page)).toHaveCount(3)
  await expect(skillCards(page).nth(0)).toContainText('#1 FIS')
  await expect(skillCards(page).nth(1)).toContainText('#2 ERAS')
  await expect(skillCards(page).nth(2)).toContainText('#3 AFRM')

  const fis = skillCards(page).nth(0)
  await expect(fis).toContainText('Fidelity National Information Services')
  await expect(fis).toContainText(/Entry signal \d{1,2}:\d{2} [AP]M at US\$68\.12/)
  await expect(fis.getByText('+0.92% above the range high', { exact: true })).toBeVisible()
  await expect(fis.getByText('Your round-trip cost (currency conversion both ways plus the spread) is 1.36R: the trade must gain more than that to pay.', { exact: true })).toBeVisible()
  await expect(fis).toContainText(/Target hit at \d{1,2}:\d{2} [AP]M \(US\$70\.36\) · \+2\.00R before costs, \+0\.64R after/)
  await expect(fis).toContainText('Cost 3.10% round trip = 1.36R')
  await expect(fis.getByText('Target hit', { exact: true })).toBeVisible() // the outcome chip
  await expect(skillCards(page).nth(1).getByText('+1.67% above the range high', { exact: true })).toBeVisible()
  await expect(skillCards(page).nth(2)).toContainText('Your round-trip cost (currency conversion both ways plus the spread) is 2.26R: the trade must gain more than that to pay.')

  // the after-costs top 3 is as it was: no strength or conversion line
  await expect(cards(page)).toHaveCount(1)
  const ogc = cards(page).first()
  await expect(ogc).toContainText('#1 OGC.TO')
  await expect(ogc).toContainText('StopC$5.40')
  await expect(ogc).not.toContainText('above the range high')
  await expect(ogc).not.toContainText('Your round-trip cost')

  // every signal is still listed; the skill's ones are marked
  const table = page.getByRole('table', { name: 'Other signals today' })
  await expect(table.getByRole('row')).toHaveCount(5)
  await expect(table.getByRole('row', { name: /FIS/ })).toContainText('skill #1')
  await expect(table.getByRole('row', { name: /AFRM/ })).toContainText('skill #3')
  await expect(table.getByRole('row', { name: /OGC\.TO/ })).not.toContainText('skill #')
  await expect(page.getByRole('button', { name: /buy|order|place/i })).toHaveCount(0)
})

test('a signal in both lists is shown in both', async ({ page }) => {
  await seedDaytradeDay({ status: 'scanning', lastUpdate: ago(1) })
  await seedDaytradeSignal({ symbol: 'TGTX', triggerAt: ago(2), entry: 67.65, stop: 66.05, rank: 1, skillRank: 1 })
  await page.goto('/daytrade')
  await expect(skillCards(page)).toHaveCount(1)
  await expect(skillCards(page).first()).toContainText('#1 TGTX')
  await expect(cards(page)).toHaveCount(1)
  await expect(cards(page).first()).toContainText('#1 TGTX')
})

test("a day with the skill's signals but none eligible shows the skill's list and the no-trade line", async ({ page }) => {
  await seedDaytradeDay({ status: 'done', lastUpdate: ago(30) })
  await seedDaytradeSignal({ symbol: 'FIS', triggerAt: ago(200), entry: 68.12, orHigh: 67.5, stop: 67, skillRank: 1, eligible: false, netHistoryR: -0.1 })
  await seedDaytradeSignal({ symbol: 'ERAS', triggerAt: ago(195), entry: 3.05, orHigh: 3, stop: 2.95, skillRank: 2, eligible: false, netHistoryR: -0.2 })

  await page.goto('/daytrade')
  await expect(skillCards(page)).toHaveCount(2)
  await expect(skillCards(page).nth(0)).toContainText('#1 FIS')
  await expect(skillCards(page).nth(1)).toContainText('#2 ERAS')
  await expect(skillSection(page).getByText('No signals yet today.')).toHaveCount(0)
  await expect(cards(page)).toHaveCount(0)
  await expect(costSection(page).getByText('No signal today has a positive record after costs (2 signals checked).')).toBeVisible()
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
  await expect(skillSection(page).getByText('No signals yet today.')).toBeVisible()
  await expect(costSection(page).getByText('No signals yet today.')).toBeVisible()
  await expect(page.getByText(/signals checked/)).toHaveCount(0)
})

test('finished days without a signal in either list show dash rows with 0 trades', async ({ page }) => {
  for (const n of [1, 2, 3]) await seedDaytradeDay({ day: daysAgo(n), status: 'done', lastUpdate: ago(n * 1440) })
  await seedDaytradeSignal({ day: daysAgo(1), symbol: 'AMD', triggerAt: ago(1440), entry: 50, stop: 49, eligible: false, status: 'flat', netR: -0.3 })
  await page.goto('/daytrade')
  const last20 = page.getByRole('region', { name: 'Track record' }).getByTestId('track-20')
  await expect(last20).toContainText('Last 20 trading days · 3 finished so far')
  const cells = (name: RegExp) => last20.getByRole('row', { name }).getByRole('cell')
  await expect(cells(/The skill's top 3/)).toHaveText(["The skill's top 3", '0', '—', '—', '—', '—'])
  await expect(cells(/Top 3 after your costs/)).toHaveText(['Top 3 after your costs', '0', '—', '—', '—', '—'])
})

test('a closed day says the market is closed', async ({ page }) => {
  await seedDaytradeDay({ status: 'closed' })
  await page.goto('/daytrade')
  await expect(page.getByTestId('daytrade-status')).toHaveText('Market closed today.')
  await expect(skillSection(page).getByText('No signals yet today.')).toHaveCount(0)
  await expect(costSection(page).getByText('No signals yet today.')).toHaveCount(0)
})

test('before the first scan neither list says there are no signals yet', async ({ page }) => {
  await seedDaytradeDay({ status: 'waiting', lastUpdate: null })
  await page.goto('/daytrade')
  await expect(skillSection(page)).toBeVisible()
  await expect(skillSection(page).getByText('No signals yet today.')).toHaveCount(0)
  await expect(costSection(page).getByText('No signals yet today.')).toHaveCount(0)
})

test('the track record counts each list of finished days, before and after costs', async ({ page }) => {
  for (const n of [1, 2, 3]) await seedDaytradeDay({ day: daysAgo(n), status: 'done', lastUpdate: ago(n * 1440) })
  await seedDaytradeDay({ day: daysAgo(4), status: 'failed', lastUpdate: ago(4 * 1440) }) // not finished: left out
  const past = (n: number, symbol: string, status: 'open' | 'target' | 'stop' | 'flat', netR: number, rank: number | null = 1, skillRank: number | null = null) =>
    seedDaytradeSignal({ day: daysAgo(n), symbol, triggerAt: ago(n * 1440), entry: 20, stop: 19, rank, skillRank, status, netR })
  // the after-costs top 3 (gross R is net R + 0.1)
  await past(1, 'AAA', 'target', 2.0, 1, 1) // in both lists
  await past(1, 'BBB', 'stop', -1.0, 2)
  await past(2, 'CCC', 'flat', 0.2)
  await past(2, 'GGG', 'target', 1.0, null)
  await sql`update daytrade_signals set best_rank = 2 where symbol = 'GGG'` // shown #2, displaced later that day
  await past(2, 'DDD', 'stop', -1.1, null) // in neither list
  await past(3, 'EEE', 'stop', -1.0)
  await past(3, 'HHH', 'open', 0) // never finalized: counts nowhere
  await sql`update daytrade_signals set net_r = null where symbol = 'HHH'`
  await past(4, 'FFF', 'target', 1.9)
  // the skill's top 3: AAA (#1 on day 1), and two more
  await past(1, 'FIS', 'stop', -1.36, null, 2)
  await past(2, 'ERAS', 'target', 0.64, null, 1)
  await past(4, 'AFRM', 'target', 0.64, null, 1) // not a finished day: left out

  await page.goto('/daytrade')
  const record = page.getByRole('region', { name: 'Track record' })
  await expect(record.getByText("Paper: what each list's trades would have done.")).toBeVisible()
  await expect(record.getByText(/rule's top-3 trades/)).toHaveCount(0)
  const last20 = record.getByTestId('track-20')
  await expect(last20).toContainText('Last 20 trading days · 3 finished so far')
  const headers = await last20.getByRole('columnheader').allTextContents()
  expect(headers.map((h) => h.trim())).toEqual(['List', 'Trades', 'Target / stop / flat', 'Average R before costs', 'Average R after costs', 'Sum after costs'])
  const cells = (name: RegExp) => last20.getByRole('row', { name }).getByRole('cell')
  // skill: 2.0, −1.36, 0.64 after costs (sum 1.28, average 0.43); 2.1, −1.26, 0.74 before (average 0.53)
  await expect(cells(/The skill's top 3/)).toHaveText(["The skill's top 3", '3', '2 / 1 / 0', '+0.53R', '+0.43R', '+1.28R'])
  // after costs: 2.0, −1.0, 0.2, 1.0, −1.0 → average +0.24R, sum +1.20R; +0.34R before costs
  await expect(cells(/Top 3 after your costs/)).toHaveText(['Top 3 after your costs', '5', '2 / 2 / 1', '+0.34R', '+0.24R', '+1.20R'])
  await expect(record.getByTestId('track-60').getByRole('row', { name: /Top 3 after your costs/ }).getByRole('cell').nth(1)).toHaveText('5')
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
