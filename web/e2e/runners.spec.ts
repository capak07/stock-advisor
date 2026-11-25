import { expect, test, type Page } from '@playwright/test'
import { addDays, shortDay } from '../lib/dates'
import { BIAS_NOTE, NOTES, type RunnerWarning } from '../lib/runners'
import { LIVE_NOTE } from '../lib/runners-live'
import { daysAgo, lastWeekday, resetData, runnerReport, seedFx, seedRun, seedRunner, seedRunnerBacktest, seedRunnerRule } from './db'

const SALE: RunnerWarning = {
  kind: 'share_sale',
  form: 'F-1/A',
  filed: daysAgo(4),
  text: 'Filed a F-1/A on Nov 20: a share sale may be pending.',
}
const SPLIT: RunnerWarning = {
  kind: 'reverse_split',
  form: 'split',
  filed: daysAgo(30),
  text: 'Did a 1-for-25 reverse split on Oct 27: the share count was cut to lift the price.',
}

const cards = (page: Page) => page.getByTestId('runner-card')
const gateChip = (page: Page) => page.getByTestId('runners-gate')
const openCards = (page: Page) => page.getByTestId('open-runner-card')
const backtestCard = (page: Page) => page.getByRole('region', { name: 'Backtest' })
// a minute ago: this morning's check, unless the test runs in the first minute after midnight
const finished = () => new Date(Date.now() - 60_000).toISOString()
const SIDEBAR = ['Today', 'Portfolio', 'Day trade', 'Runners', 'Picks', 'History', 'Invest', 'Watchlist', 'Sources', 'Settings']

test.beforeEach(resetData)

test('a signal shows its plan and warning under the paper label', async ({ page }) => {
  await seedFx([daysAgo(1)], 1.4)
  await seedRunner({ warnings: [SALE], warningsChecked: true })
  await page.goto('/runners')
  await expect(page.getByRole('heading', { name: 'Runners', level: 1 })).toBeVisible()
  await expect(gateChip(page)).toHaveText('Paper: testing')
  await expect(page.getByText('No rule has been chosen by a backtest yet.')).toBeVisible()

  await expect(cards(page)).toHaveCount(1)
  const card = cards(page).first()
  await expect(card).toContainText('Paper: testing')
  await expect(card).toContainText('AKAN')
  await expect(card).toContainText('Akanda Corp.')
  await expect(card).toContainText(SALE.text)
  await expect(card.getByTestId('runner-answer')).toHaveText('Buy at the openAbout US$136.00 for 100 shares at the signal close')
  await expect(card).toContainText('Entry ≈ US$1.36')
  await expect(card).toContainText('Target US$2.04+50.0%Stop US$1.02−25.0%')
  await expect(card.getByText('≈ 105 shares (risking ≈ C$50 at the stop)')).toBeHidden() // under Details
  await expect(card).toContainText('≈ 105 shares')
  await expect(card).toContainText('Paper trade: 100 shares at the open (about US$136.00 at the signal close)')
  await expect(card.getByRole('link', { name: 'AKAN' })).toHaveAttribute('href', '/ticker/AKAN')
  for (const note of NOTES) await expect(page.getByText(note)).toBeVisible()
  // display only: nothing here places an order
  await expect(page.getByRole('button', { name: /buy|order|place/i })).toHaveCount(0)
})

test("Yahoo's prices show what the paper trades cost at the open and are worth at the close", async ({ page }) => {
  // e2e/yahoo-stub.mjs: each weekday through the last one opens at 1.40 (high 1.50, low 1.30) and closes at 1.45
  const weekdayBefore = (day: string) => {
    let d = addDays(day, -1)
    while ([0, 6].includes(new Date(`${d}T12:00:00Z`).getUTCDay())) d = addDays(d, -1)
    return d
  }
  const last = lastWeekday()
  const signal = weekdayBefore(last)
  await seedFx([daysAgo(1)], 1.4)
  // AKAN's signal (close 1.36, low 0.66) is bought at the last weekday's 1.40 open: stop 1.05, target 2.10
  await seedRunner({ signalDay: signal })
  // SNDL, stored open through the weekday before: the last weekday opens at 1.40, under its 1.44 stop
  await seedRunner({
    symbol: 'SNDL',
    signalDay: weekdayBefore(weekdayBefore(signal)),
    status: 'open',
    entryDay: weekdayBefore(signal),
    entry: 1.92,
    stop: 1.44,
    target: 2.88,
    lastDay: signal,
    lastClose: 2.4,
  })
  await page.goto('/runners')

  const card = cards(page).first()
  await expect(card).toContainText(`Bought US$1.40${shortDay(last)}Target US$2.10+50.0%Stop US$1.05−25.0%`)
  await expect(card).toContainText('100 shares: paid US$140.00 · worth US$145.00')
  await expect(card).toContainText('Paper trade: 100 shares, US$136.00 at the signal close, bought for US$140.00 at the open')
  await expect(card).toContainText(`Closed US$1.45 on ${shortDay(last)}: worth US$145.00`)
  await expect(card.getByTestId('runner-gain')).toHaveText('+US$5.00 +3.6%')
  await expect(card).toContainText('+0.14R')
  await expect(card.getByTestId('runner-gain')).toHaveClass(/gain/)
  await expect(card).toContainText(LIVE_NOTE)
  await expect(page.getByText('bought at the open', { exact: true })).toBeVisible()

  const open = openCards(page).first()
  await expect(open).toContainText(`Opened under the stop at US$1.40 on ${shortDay(last)}: got back US$140.00`)
  await expect(open.getByTestId('open-runner-gain')).toHaveText('−US$52.00 −27.1%')
  await expect(open).toContainText('100 shares: paid US$192.00 · got back US$140.00')
  await expect(open).toContainText('R at the exit')
  await expect(open.getByTestId('open-runner-r')).toHaveText('−1.08R')
  await expect(page.getByText('latest prices from Yahoo', { exact: true })).toBeVisible()
})

test('no ignition yesterday and no finished runners say so', async ({ page }) => {
  await page.goto('/runners')
  await expect(page.getByText('No ignition yesterday.')).toBeVisible()
  await expect(page.getByText('No finished runners yet.')).toBeVisible()
  await expect(page.getByText('No finished paper trades yet.')).toBeVisible()
  await expect(page.getByText('No open runners.')).toBeVisible()
  await expect(backtestCard(page)).toContainText('not run yet')
  await expect(page.getByText('No check has run yet.')).toBeVisible()
})

test('open runners show their R so far and closed ones fill the track record', async ({ page }) => {
  await seedRunner({
    symbol: 'AKAN',
    signalDay: daysAgo(4),
    status: 'open',
    entryDay: daysAgo(3),
    entry: 1.92,
    stop: 1.44,
    target: 2.88,
    lastDay: daysAgo(1),
    lastClose: 2.4,
  })
  await seedRunner({ symbol: 'MULN', signalDay: daysAgo(6), status: 'target', entry: 2, exitPrice: 3, exitDay: daysAgo(1), grossR: 1.6, netR: 1.5 })
  await seedRunner({ symbol: 'SNDL', signalDay: daysAgo(6), status: 'stop', entry: 1.5, exitPrice: 1.2, exitDay: daysAgo(1), grossR: -0.4, netR: -0.5 })
  await page.goto('/runners')

  await expect(openCards(page)).toHaveCount(1)
  const card = openCards(page).first()
  await expect(card).toContainText('Bought 100 shares at US$1.92')
  await expect(card).toContainText('= US$192.00')
  await expect(card).toContainText(`${shortDay(daysAgo(1))} close US$2.40`)
  await expect(card).toContainText('100 shares: paid US$192.00 · worth US$240.00')
  await expect(card).toContainText('Target US$2.88+50.0%Stop US$1.44−25.0%')
  await expect(card.getByTestId('open-runner-gain')).toHaveText('+US$48.00 +25.0%')
  await expect(card.getByTestId('open-runner-gain')).toHaveClass(/gain/)
  await expect(card.getByTestId('open-runner-r')).toHaveText('+1.00R')
  await expect(card.getByTestId('open-runner-r')).toHaveClass(/gain/)

  const last20 = page.getByTestId('runners-record-20')
  await expect(last20.getByRole('cell')).toHaveText(['Last 20 sessions', '+0.50R', '2', '1 / 1 / 0', '0', '+0.50R', '+1.00R'])
  await expect(page.getByText('No finished runners yet.')).toHaveCount(0)
  await expect(page.getByTestId('runners-paper-total')).toHaveText(
    '2 finished trades: put in US$350.00, got back US$420.00, +US$70.00 (+20.0%). After the estimated spread: +US$63.00.',
  )
})

test('the label changes once the backtest and 40 live trades are positive', async ({ page }) => {
  await seedRunnerRule(1)
  await seedRunnerBacktest({ ruleVersion: 1, frozen: { older: runnerReport(), newer: runnerReport({ signals: 120, avg_net_r: 0.2 }) } })
  const symbols = Array.from({ length: 40 }, (_, i) => `T${String(i).padStart(2, '0')}`)
  for (const symbol of symbols) {
    await seedRunner({ symbol, ruleVersion: 1, signalDay: daysAgo(90), status: 'target', exitDay: daysAgo(85), grossR: 2.1, netR: 2 })
  }
  await seedRunner({ symbol: 'NEXT', ruleVersion: 1 })
  await page.goto('/runners')
  await expect(gateChip(page)).toHaveText('Tested: positive after costs so far')
  await expect(page.getByTestId('runners-gate-reasons')).toHaveCount(0)
  await expect(cards(page)).toHaveCount(1)
  await expect(cards(page)).not.toContainText('Paper: testing')
})

test('a failed morning check is shown', async ({ page }) => {
  await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: finished(), summary: { runners_error: 'RuntimeError: boom' } })
  await page.goto('/runners')
  await expect(page.getByText("This morning's check failed: RuntimeError: boom")).toBeVisible()
  await expect(page.getByText('No check has run yet.')).toHaveCount(0)
  await expect(page.getByText('No signals: the check failed.')).toBeVisible()
  await expect(page.getByText('No ignition yesterday.')).toHaveCount(0)
})

test("yesterday's check that has not run this morning shows the last signals as such", async ({ page }) => {
  const yesterday = new Date(Date.now() - 86_400_000)
  await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: yesterday.toISOString(), summary: { runners: { signals: 1 } } })
  await seedRunner({ signalDay: daysAgo(2) })
  const day = yesterday.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'America/Toronto' })
  await page.goto('/runners')
  await expect(page.getByText(`This morning's check has not run yet. Last check: ${day}.`)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Last signals' })).toBeVisible()
  await expect(page.getByRole('heading', { name: "Today's signals" })).toHaveCount(0)
  await expect(page.getByText('enter at the open', { exact: true })).toHaveCount(0)
  await expect(cards(page)).toHaveCount(1)
})

test('a morning check that ran shows neither the failed nor the no-check line', async ({ page }) => {
  // a later run without a runners part must not hide it
  await seedRun({
    kind: 'pre_open',
    status: 'success',
    published: true,
    finished: finished(),
    summary: { runners: { signals: 0, split_suspect: 0, entered: 0, closed: 0, open: 0, unchecked: 0 } },
  })
  await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: new Date().toISOString(), summary: {} })
  await page.goto('/runners')
  await expect(page.getByRole('heading', { name: 'Runners', level: 1 })).toBeVisible()
  await expect(page.getByText('No ignition yesterday.')).toBeVisible()
  await expect(page.getByText('No check has run yet.')).toHaveCount(0)
  await expect(page.getByText(/check failed/)).toHaveCount(0)
})

test('the backtest card carries the bias note, the unseen-third line, its run date and the worst trades', async ({ page }) => {
  await seedRunnerRule(1)
  const worst = [{ symbol: 'MULN', signal_day: '2025-02-03', net_r: -2.4 }]
  const frozen = { older: runnerReport(), newer: runnerReport({ signals: 120, avg_net_r: 0.2, worst }) }
  await seedRunnerBacktest({
    variantsTried: 15,
    ranAt: '2026-11-21T14:00:00Z',
    dataFrom: '2018-11-01',
    dataTo: '2026-11-20',
    frozen,
    pick: { name: 'starting values', note: null, ...frozen },
  })
  await page.goto('/runners')
  const card = backtestCard(page)
  await expect(card).toContainText(BIAS_NOTE)
  await expect(card).toContainText('Ran Nov 21, 2026 on prices from Nov 1, 2018 to Nov 20, 2026.')
  await expect(card).toContainText(
    'Split at Mar 1, 2024: the rule was chosen on older data; the newest third was unseen. 15 variations tried.',
  )
  await card.getByText('Worst 10 trades').click()
  const newer = card.getByRole('table', { name: 'Worst trades, Newest 1/3, unseen' })
  await expect(newer.getByRole('row', { name: /MULN/ }).getByRole('cell')).toHaveText(['MULN', 'Feb 3, 2025', '−2.40R'])
  await expect(card).not.toContainText('not run yet')
  // the search picks the frozen rule: no "would pick" line
  await expect(card).not.toContainText('would pick')
})

test('the backtest card says what the search would pick now when it differs from the frozen rule', async ({ page }) => {
  await seedRunnerRule(1)
  const frozen = { older: runnerReport(), newer: runnerReport({ signals: 120, avg_net_r: 0.2 }) }
  await seedRunnerBacktest({
    frozen,
    pick: { name: 'volume 8x', note: null, older: runnerReport({ avg_net_r: 0.3 }), newer: runnerReport({ signals: 90, avg_net_r: 0.25 }) },
  })
  await page.goto('/runners')
  await expect(backtestCard(page)).toContainText('The search would pick "volume 8x" now: +0.25R on the newest third over 90 signals.')
})

test('a new max loss in Settings resizes the card', async ({ page }) => {
  await seedFx([daysAgo(1)], 1.4)
  await seedRunner()
  await page.goto('/runners')
  await expect(cards(page)).toContainText('≈ 105 shares')
  const sidebar = page.getByRole('complementary', { name: 'Main' })
  await sidebar.getByRole('link', { name: 'Settings' }).click()
  await page.getByLabel(/Runners max loss per trade \(C\$\)/).fill('100')
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByRole('status')).toHaveText('Settings saved: they apply from the next run')
  await sidebar.getByRole('link', { name: 'Runners' }).click()
  await expect(cards(page)).toContainText('≈ 210 shares') // floor(100 / 1.4 / 0.34)
})

test.describe('on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('at 390 px the page has no horizontal scroll', async ({ page }) => {
    await seedFx([daysAgo(1)], 1.4)
    await seedRunner({ warnings: [SALE, SPLIT], warningsChecked: true })
    await seedRunner({ symbol: 'MULN', signalDay: daysAgo(6), status: 'open', entryDay: daysAgo(5), entry: 1.92, stop: 1.44, target: 2.88, lastClose: 2.4, lastDay: daysAgo(1) })
    await seedRunner({
      symbol: 'SNDL',
      ruleVersion: 1,
      signalDay: daysAgo(6),
      status: 'target',
      entry: 1.5,
      exitPrice: 2.5,
      exitDay: daysAgo(1),
      grossR: 2.1,
      netR: 2,
    })
    await seedRunnerRule(1)
    await seedRunnerBacktest()
    await page.goto('/runners')
    await expect(cards(page)).toHaveCount(1)
    await expect(page.getByTestId('runners-paper-total')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
    // the open card's money and R wrap inside it: on screen once the card is
    const open = openCards(page).first()
    await open.scrollIntoViewIfNeeded()
    await expect(open.getByTestId('open-runner-gain')).toBeInViewport({ ratio: 1 })
    await expect(open.getByTestId('open-runner-r')).toHaveText('+1.00R')
    await expect(open.getByTestId('open-runner-r')).toBeInViewport({ ratio: 1 })
    // "Average R" shows without scrolling inside its card: bring the row's first cell into view (that
    // scrolls the page, not the table), then the value beside it must be on screen too
    const record = page.getByTestId('runners-record-20').getByRole('cell')
    await record.first().scrollIntoViewIfNeeded()
    await expect(record.nth(1)).toHaveText('+2.00R')
    await expect(record.nth(1)).toBeInViewport({ ratio: 1 })
    // the backtest's two columns fit without scrolling sideways in their card
    const backtest = page.locator('.rn-backtest')
    expect(await backtest.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(0)
  })
})

test('Runners is in the sidebar after Day trade and never on Picks or Invest', async ({ page }) => {
  await seedRunner()
  await page.goto('/runners')
  const sidebar = page.getByRole('complementary', { name: 'Main' })
  await expect(sidebar.getByRole('link')).toHaveText([/ADVISOR/, ...SIDEBAR]) // the brand, then every page in order
  await expect(sidebar.getByRole('link', { name: 'Runners' })).toHaveAttribute('aria-current', 'page')
  await expect(cards(page)).toContainText('AKAN')
  for (const path of ['/picks', '/invest']) {
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.locator('main')).not.toContainText('AKAN')
  }
})
