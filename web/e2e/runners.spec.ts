import { expect, test, type Page } from '@playwright/test'
import { BIAS_NOTE, NOTES, type RunnerWarning } from '../lib/runners'
import { daysAgo, resetData, runnerReport, seedFx, seedRun, seedRunner, seedRunnerBacktest, seedRunnerRule } from './db'

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
const openTable = (page: Page) => page.getByRole('table', { name: 'Open runners' })
const backtestCard = (page: Page) => page.getByRole('region', { name: 'Backtest' })
const finished = () => new Date(Date.now() - 3_600_000).toISOString()

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
  await expect(card).toContainText('AKAN')
  await expect(card).toContainText('Akanda Corp.')
  await expect(card).toContainText(SALE.text)
  await expect(card).toContainText('stop US$1.02, target US$2.04 (2R)')
  await expect(card).toContainText('≈ 105 shares')
  await expect(card.getByRole('link', { name: 'AKAN' })).toHaveAttribute('href', '/ticker/AKAN')
  for (const note of NOTES) await expect(page.getByText(note)).toBeVisible()
  // display only: nothing here places an order
  await expect(page.getByRole('button', { name: /buy|order|place/i })).toHaveCount(0)
})

test('no ignition yesterday and no finished runners say so', async ({ page }) => {
  await page.goto('/runners')
  await expect(page.getByText('No ignition yesterday.')).toBeVisible()
  await expect(page.getByText('No finished runners yet.')).toBeVisible()
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
  await seedRunner({ symbol: 'MULN', signalDay: daysAgo(6), status: 'target', exitDay: daysAgo(1), grossR: 1.6, netR: 1.5 })
  await seedRunner({ symbol: 'SNDL', signalDay: daysAgo(6), status: 'stop', exitDay: daysAgo(1), grossR: -0.4, netR: -0.5 })
  await page.goto('/runners')

  const open = openTable(page)
  await expect(open.getByRole('row')).toHaveCount(2) // header + 1
  const row = open.getByRole('row', { name: /AKAN/ })
  await expect(row).toContainText('US$1.92')
  await expect(row).toContainText('US$1.44')
  await expect(row).toContainText('US$2.88')
  await expect(row.getByText('+1.00R')).toHaveClass(/gain/)

  const last20 = page.getByTestId('runners-record-20')
  await expect(last20.getByRole('cell')).toHaveText(['Last 20 sessions', '2', '1 / 1 / 0', '0', '+0.50R', '+0.50R', '+1.00R'])
  await expect(page.getByText('No finished runners yet.')).toHaveCount(0)
})

test('the label changes once the backtest and 40 live trades are positive', async ({ page }) => {
  await seedRunnerRule(1)
  await seedRunnerBacktest({ ruleVersion: 1, frozen: { older: runnerReport(), newer: runnerReport({ signals: 120, avg_net_r: 0.2 }) } })
  const symbols = Array.from({ length: 40 }, (_, i) => `T${String(i).padStart(2, '0')}`)
  for (const symbol of symbols) {
    await seedRunner({ symbol, ruleVersion: 1, signalDay: daysAgo(90), status: 'target', exitDay: daysAgo(85), grossR: 2.1, netR: 2 })
  }
  await page.goto('/runners')
  await expect(gateChip(page)).toHaveText('Tested: positive after costs so far')
  await expect(page.getByTestId('runners-gate-reasons')).toHaveCount(0)
})

test('a failed morning check is shown', async ({ page }) => {
  await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: finished(), summary: { runners_error: 'RuntimeError: boom' } })
  await page.goto('/runners')
  await expect(page.getByText("This morning's check failed: RuntimeError: boom")).toBeVisible()
  await expect(page.getByText('No check has run yet.')).toHaveCount(0)
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

test('the backtest card carries the bias note and the unseen-third line', async ({ page }) => {
  await seedRunnerRule(1)
  await seedRunnerBacktest({ variantsTried: 15 })
  await page.goto('/runners')
  const card = backtestCard(page)
  await expect(card).toContainText(BIAS_NOTE)
  await expect(card).toContainText('Chosen on data before Mar 1, 2024; the newest third was unseen. 15 variations tried.')
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
    await seedRunnerRule(1)
    await seedRunnerBacktest()
    await page.goto('/runners')
    await expect(cards(page)).toHaveCount(1)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
    // the backtest's two columns fit without scrolling sideways in their card
    const backtest = page.locator('.rn-backtest')
    expect(await backtest.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(0)
  })
})

test('Runners is in the sidebar after Day trade and never on Picks or Invest', async ({ page }) => {
  await seedRunner()
  await page.goto('/runners')
  const sidebar = page.getByRole('complementary', { name: 'Main' })
  await expect(sidebar.getByRole('link')).toContainText(['Today', 'Portfolio', 'Day trade', 'Runners', 'Picks', 'History', 'Invest', 'Watchlist', 'Sources', 'Settings'])
  await expect(sidebar.getByRole('link', { name: 'Runners' })).toHaveAttribute('aria-current', 'page')
  await expect(cards(page)).toContainText('AKAN')
  for (const path of ['/picks', '/invest']) {
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.locator('main')).not.toContainText('AKAN')
  }
})
