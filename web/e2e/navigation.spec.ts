import { expect, test } from '@playwright/test'
import { resetData, seedHealth, seedNews, seedPortfolio, seedRun, seedSources, seedVerdict, sql } from './db'

test.beforeEach(resetData)

test('the sidebar reaches every page and marks the current one', async ({ page }) => {
  await page.goto('/')
  const sidebar = page.getByRole('complementary', { name: 'Main' })
  await expect(sidebar.getByRole('link', { name: 'Portfolio' })).toHaveAttribute('aria-current', 'page')
  await sidebar.getByRole('link', { name: 'Watchlist' }).click()
  await expect(page.getByRole('heading', { name: 'Watchlist' })).toBeVisible()
  await expect(sidebar.getByRole('link', { name: 'Watchlist' })).toHaveAttribute('aria-current', 'page')
  await sidebar.getByRole('link', { name: 'Sources' }).click()
  await expect(page.getByRole('heading', { name: 'Source health' })).toBeVisible()
  await sidebar.getByRole('link', { name: 'Settings' }).click()
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
})

test.describe('on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('pages are tabs at the bottom, and Settings is under More', async ({ page }) => {
    await page.goto('/')
    const tabs = page.getByRole('navigation', { name: 'Main' }).last()
    await expect(tabs.getByRole('link', { name: 'Portfolio' })).toHaveAttribute('aria-current', 'page')
    await tabs.getByRole('link', { name: 'Watchlist' }).click()
    await expect(page.getByRole('heading', { name: 'Watchlist' })).toBeVisible()
    await tabs.getByRole('button', { name: 'More' }).click()
    await page.getByRole('dialog', { name: 'More' }).getByRole('link', { name: 'Settings' }).click()
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
    await expect(tabs.getByRole('button', { name: 'More' })).toHaveAttribute('aria-current', 'page')
  })

  test('no page is wider than the screen', async ({ page }) => {
    // Pages with content: holdings with long names, notes, the chart, warnings, watchlist rows.
    await seedPortfolio()
    await sql`update symbols set name = 'Royal Bank of Canada Global Diversified Holdings and Trust Incorporated' where symbol = 'RY.TO'`
    await sql`update symbols set name = 'Apple Inc. Consumer Electronics and Services Worldwide Corporation' where symbol = 'AAPL'`
    await sql`insert into watchlist (symbol, asset_type) values ('SHOP.TO', 'stock'), ('SOL', 'crypto')`
    const runId = await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
    await seedVerdict(runId, {
      symbol: 'SHOP.TO',
      assetType: 'stock',
      verdict: 'hold',
      reasons: ["doesn't qualify as a buy", 'P(beat XIU.TO) 0.54 is under 0.58 at every horizon'],
      details: { market_picks_enabled: false },
    })
    await seedSources()
    await seedHealth(runId, new Date().toISOString(), [
      { source: 'sec_form4', status: 'partial', error: `PartialFetch: ${'DocumentBudgetExhausted; '.repeat(12)}` },
    ])
    await seedNews([
      { symbol: 'RY.TO', asset_type: 'stock', hoursAgo: 2, outlet: 'finance.yahoo.com', url: 'https://finance.yahoo.com/x', title: `RBC ${'quarterly-results-'.repeat(8)}beat`, sentiment: 0.4 },
    ])
    const pages = [
      ['/', 'My Portfolio'],
      ['/picks', "Today's Picks"],
      ['/watchlist', 'Watchlist'],
      ['/ticker/RY.TO', 'RY.TO'],
      ['/sources', 'Source health'],
      ['/settings', 'Settings'],
    ]
    for (const [path, heading] of pages) {
      await page.goto(path)
      await expect(page.getByRole('heading', { name: heading, level: 1 })).toBeVisible()
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow, path).toBeLessThanOrEqual(0)
      if (path === '/') {
        // The holdings table sits in a scroller, so the page itself never widens: check that the
        // phone layout stacks the rows, so the table fits without scrolling sideways.
        await expect(page.locator('#holdings tbody tr')).toHaveCount(3)
        const scrolls = await page.evaluate(() => {
          const box = document.querySelector('.table-scroll')!
          return box.scrollWidth - box.clientWidth
        })
        expect(scrolls, 'holdings table scrolls sideways').toBeLessThanOrEqual(0)
      }
    }
  })
})
