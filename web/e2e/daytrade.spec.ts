import { expect, test, type Locator, type Page } from '@playwright/test'
import { nyTime } from '../lib/daytrade'
import { daysAgo, nyAt, resetData, seedDaytradeDay, seedDaytradeSignal, seedFx, sql, today } from './db'

const MIN = 60_000
const ago = (minutes: number) => new Date(Date.now() - minutes * MIN)
const skillSection = (page: Page) => page.getByRole('region', { name: "The skill's top 3" })
const costSection = (page: Page) => page.getByRole('region', { name: 'Top 3 after your costs' })
/** The after-costs top 3's cards. */
const cards = (page: Page) => costSection(page).getByTestId('daytrade-card')
const skillCards = (page: Page) => skillSection(page).getByTestId('daytrade-card')
/** The All signals table: opens its collapsed block first. */
async function allSignals(page: Page) {
  await page.locator('summary', { hasText: 'All signals' }).click()
  return page.getByRole('table', { name: 'All signals' })
}
/** A card's place in its top 3 and its symbol. */
async function expectPlace(card: Locator, place: number, symbol: string) {
  await expect(card.locator('.rank')).toHaveText(String(place))
  await expect(card.locator('.sym')).toHaveText(symbol)
}
const SKILL_SUB = 'The strongest volume-confirmed US breakouts at 10:00 AM ET, by how far the price is above the range high. Before your costs.'

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
  await expect(first).toContainText('Stop US$66.05')
  await expect(first).toContainText('Target US$70.85')
  await expect(first).toContainText('Opening range US$64.45–US$67.55 · flat by 12:55 PM')
  await expect(first).toContainText('Cost1.31R')
  await expect(first).toContainText('History, net+0.29R')
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
  await expect(second).toContainText('Stop C$149.50')
  await expect(second).toContainText('≈ 100 shares (risking ≈ C$50 at the stop)')
  await expect(second).toContainText('flat by 3:55 PM')
  await expect(cards(page).nth(2)).toContainText('Even one share risks more than your C$50 limit.')

  // every signal, in a collapsed table
  await expect(page.getByRole('table', { name: 'All signals' })).toBeHidden()
  const table = await allSignals(page)
  await expect(table.getByRole('row')).toHaveCount(5) // header + 4
  await expect(table.getByRole('row', { name: /AMD/ })).toContainText('History is −0.20R after costs')
  await expect(table.getByRole('row', { name: /TGTX/ })).toContainText('Top 3 (#1)')

  for (const note of NOTES) await expect(page.getByText(note)).toBeVisible()
  // nothing here places an order or links to a broker
  await expect(page.getByRole('button', { name: /buy|order|place/i })).toHaveCount(0)
})

test("the top 3 after costs come first, then the skill's top 3 in compact cards with their strength, result and cost", async ({ page }) => {
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
  // the page's order (spec §7.3): status line, the top 3 after costs, the skill's top 3, all signals, track record and notes
  const status = await page.getByTestId('daytrade-status').boundingBox()
  const costTop = await costSection(page).boundingBox()
  const skillTop = await skillSection(page).boundingBox()
  expect(status!.y).toBeLessThan(costTop!.y)
  expect(costTop!.y).toBeLessThan(skillTop!.y)
  const headings = await page.getByRole('heading', { level: 2 }).allInnerTexts()
  expect(headings.map((h) => h.replace(/\s+/g, ' ').trim())).toEqual([
    'Top 3 after your costs',
    "The skill's top 3",
    'All signals 4',
    'Track record',
    'Notes: costs, rules, limits',
  ])
  await expect(skillSection(page).getByText(SKILL_SUB, { exact: true })).toBeVisible()

  await expect(skillCards(page)).toHaveCount(3)
  await expectPlace(skillCards(page).nth(0), 1, 'FIS')
  await expectPlace(skillCards(page).nth(1), 2, 'ERAS')
  await expectPlace(skillCards(page).nth(2), 3, 'AFRM')

  const fis = skillCards(page).nth(0)
  await expect(fis).toContainText('Fidelity National Information Services')
  // compact: entry → target / stop, the strength, the result after costs, the verdict and the cost; no tiles
  await expect(fis).toContainText('Entry US$68.12 → US$70.36 / US$67.00')
  await expect(fis.getByText('+0.92% above the range high', { exact: true })).toBeVisible()
  await expect(fis.getByText('+0.64R after costs', { exact: true })).toBeVisible()
  await expect(fis).toContainText('10,000 replays: target first 34%')
  await expect(fis).toContainText('Cost 3.10% round trip = 1.36R')
  await expect(fis.getByText('Target hit', { exact: true })).toBeVisible() // the outcome chip
  await expect(fis.locator('.stat')).toHaveCount(0)
  await expect(fis).not.toContainText('shares')
  await expect(skillCards(page).nth(1).getByText('+1.67% above the range high', { exact: true })).toBeVisible()
  await expect(skillCards(page).nth(1).getByText('Open', { exact: true })).toBeVisible()
  await expect(skillCards(page).nth(2)).toContainText('Cost 3.10% round trip = 2.26R')

  // the after-costs top 3 is a full card, without the strength line
  await expect(cards(page)).toHaveCount(1)
  const ogc = cards(page).first()
  await expectPlace(ogc, 1, 'OGC.TO')
  await expect(ogc).toContainText('Stop C$5.40')
  await expect(ogc).not.toContainText('above the range high')

  // every signal is still listed; the skill's ones are marked
  const table = await allSignals(page)
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
  await expectPlace(skillCards(page).first(), 1, 'TGTX')
  await expect(cards(page)).toHaveCount(1)
  await expectPlace(cards(page).first(), 1, 'TGTX')
})

test("a day with the skill's signals but none eligible shows the skill's list and the no-trade line", async ({ page }) => {
  await seedDaytradeDay({ status: 'done', lastUpdate: ago(30) })
  await seedDaytradeSignal({ symbol: 'FIS', triggerAt: ago(200), entry: 68.12, orHigh: 67.5, stop: 67, skillRank: 1, eligible: false, netHistoryR: -0.1 })
  await seedDaytradeSignal({ symbol: 'ERAS', triggerAt: ago(195), entry: 3.05, orHigh: 3, stop: 2.95, skillRank: 2, eligible: false, netHistoryR: -0.2 })

  await page.goto('/daytrade')
  await expect(skillCards(page)).toHaveCount(2)
  await expectPlace(skillCards(page).nth(0), 1, 'FIS')
  await expectPlace(skillCards(page).nth(1), 2, 'ERAS')
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
  // signals but none in the skill's list (as when a cycle failed to rank them)
  await expect(skillSection(page).getByText("The skill's ranking is set at 10:00 AM ET.")).toBeVisible()
  await expect(skillSection(page).getByText('No signals yet today.')).toHaveCount(0)
  const table = await allSignals(page)
  await expect(table.getByRole('row', { name: /AMD/ })).toContainText('History is −0.20R after costs')
  await expect(table.getByRole('row', { name: /SOFI/ })).toContainText('Not enough history: only 4 full past session(s); need at least 20')
})

test('each level is one unbroken figure, never wrapped or cut, at 1100 px, 1280 px and on a 390 px phone', async ({ page }) => {
  await seedFx([daysAgo(1)], 1.4)
  await seedDaytradeDay({ status: 'scanning', lastUpdate: ago(1) })
  // a four-digit US price: target US$3,567.88
  await seedDaytradeSignal({ symbol: 'AZO', name: 'AutoZone', triggerAt: ago(2), entry: 3456.78, stop: 3401.23, rank: 1 })
  await seedDaytradeSignal({ symbol: 'FIS', name: 'Fidelity National Information Services', triggerAt: ago(3), entry: 68.12, stop: 67, rank: 2 })
  await seedDaytradeSignal({ symbol: 'RY', market: 'TSX', name: 'Royal Bank', triggerAt: ago(4), entry: 150, stop: 149.5, costPct: 0.1, rank: 3 })

  const today = (p: Page) => p.getByRole('region', { name: 'Day trade · top 3 after costs' })
  for (const width of [1100, 1280, 390]) {
    await page.setViewportSize({ width, height: 900 })
    for (const [path, levels, count] of [
      ['/daytrade', (p: Page) => costSection(p).locator('.dt-levels b'), 9],
      ['/', (p: Page) => today(p).locator('.levels b'), 3], // Today shows the first one's levels
    ] as const) {
      await page.goto(path)
      await expect(levels(page)).toHaveCount(count)
      const figures = await levels(page).evaluateAll((els) =>
        els.map((el) => ({
          text: el.textContent,
          height: el.getBoundingClientRect().height,
          lineHeight: parseFloat(getComputedStyle(el).lineHeight),
          scrollWidth: el.scrollWidth,
          clientWidth: el.clientWidth,
        })),
      )
      const where = `${path} at ${width}px`
      expect(figures.map((f) => f.text), where).toContain('3,456.78')
      for (const f of figures) {
        expect(f.height, `${f.text} on one line, ${where}`).toBeLessThan(f.lineHeight * 1.5)
        expect(f.scrollWidth, `${f.text} not cut, ${where}`).toBeLessThanOrEqual(f.clientWidth)
      }
    }
  }
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
  await expect(cells(/Not picked/).nth(1)).toHaveText('1') // AMD, in neither list
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
  // not picked: DDD only (HHH never finished, FFF's day is not finished)
  await expect(cells(/Not picked/)).toHaveText(['Not picked', '1', '0 / 1 / 0', '−1.00R', '−1.10R', '−1.10R'])
  await expect(record.getByText(/Not picked: every other breakout/)).toBeVisible()
  await expect(record.getByTestId('track-60').getByRole('row', { name: /Top 3 after your costs/ }).getByRole('cell').nth(1)).toHaveText('5')
})

test('the page refreshes itself while the day is scanning', async ({ page }) => {
  await page.clock.install()
  await seedDaytradeDay({ status: 'scanning', lastUpdate: ago(1) })
  await page.goto('/daytrade')
  await expect(page.getByTestId('daytrade-status')).toHaveText(/^Scanning/)
  await expect(page.getByTestId('daytrade-live')).toHaveText('Live · updates every minute')
  await sql`update daytrade_days set status = 'failed', error = 'the scan failed: test' where day = ${today()}`
  await page.clock.runFor(61_000)
  await expect(page.getByTestId('daytrade-status')).toHaveText(/^Today's scan failed: the scan failed: test/)
})

test('a status chip flips when its status changes on a refresh, not on the first render', async ({ page }) => {
  await page.clock.install()
  await seedDaytradeDay({ status: 'scanning', lastUpdate: ago(1) })
  await seedDaytradeSignal({ symbol: 'TGTX', triggerAt: ago(2), entry: 67.65, stop: 66.05, rank: 1 })
  await page.goto('/daytrade')
  const chip = cards(page).first().locator('.dt-head > .chip')
  await expect(chip).toHaveText('Fresh')
  await expect(chip).not.toHaveClass(/flip/)
  await sql`update daytrade_signals set status = 'target', exit_at = now(), exit_price = 70.85, gross_r = 2, net_r = 0.69 where symbol = 'TGTX'`
  await page.clock.runFor(61_000)
  await expect(chip).toHaveText('Target hit')
  await expect(chip).toHaveClass('chip target flip')
})

test('a done day shows no live pill', async ({ page }) => {
  await seedDaytradeDay({ status: 'done', lastUpdate: ago(30) })
  await page.goto('/daytrade')
  await expect(page.getByTestId('daytrade-status')).toHaveText(/^Done for today/)
  await expect(page.getByTestId('daytrade-live')).toHaveCount(0)
})

test('the sidebar reaches Day trade right after Portfolio', async ({ page }) => {
  await page.goto('/')
  const links = page.getByRole('complementary', { name: 'Main' }).getByRole('link')
  const names = await links.allInnerTexts()
  expect(names.indexOf('Day trade')).toBe(names.indexOf('Portfolio') + 1)
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
    await seedDaytradeSignal({ symbol: 'PLTR', triggerAt: ago(20), entry: 148.3, stop: 146.55, skillRank: 1, eligible: false })
    // a finished day, so the track record shows its tables
    await seedDaytradeDay({ day: daysAgo(1), status: 'done', lastUpdate: ago(1440) })
    await seedDaytradeSignal({ day: daysAgo(1), symbol: 'AAA', triggerAt: ago(1440), entry: 20, stop: 19, rank: 1, status: 'target', netR: 1.9 })
    // Day trade is a phone tab, after Today and Portfolio (spec §6)
    await page.goto('/')
    const tabs = page.getByRole('navigation', { name: 'Main' }).last()
    await tabs.getByRole('link', { name: 'Day trade' }).click()
    await expect(page.getByRole('heading', { name: 'Day trade', level: 1 })).toBeVisible()
    await expect(page.getByTestId('track-20')).toBeVisible()
    const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(await overflow()).toBeLessThanOrEqual(0)
    await allSignals(page) // the opened table scrolls inside its card
    expect(await overflow()).toBeLessThanOrEqual(0)
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
