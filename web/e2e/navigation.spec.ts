import { expect, test } from '@playwright/test'
import { resetData, seedHealth, seedNews, seedPortfolio, seedRun, seedSources, seedSymbols, seedVerdict, sql } from './db'

test.beforeEach(resetData)

test('the sidebar reaches every page and marks the current one', async ({ page }) => {
  await page.goto('/')
  const sidebar = page.getByRole('complementary', { name: 'Main' })
  await expect(sidebar.getByRole('link', { name: 'Today' })).toHaveAttribute('aria-current', 'page')
  await sidebar.getByRole('link', { name: 'Portfolio' }).click()
  await expect(page.getByRole('heading', { name: 'My Portfolio', level: 1 })).toBeVisible()
  await expect(sidebar.getByRole('link', { name: 'Portfolio' })).toHaveAttribute('aria-current', 'page')
  await expect(sidebar.getByRole('link', { name: 'Today' })).not.toHaveAttribute('aria-current', 'page')
  await sidebar.getByRole('link', { name: 'Watchlist' }).click()
  await expect(page.getByRole('heading', { name: 'Watchlist' })).toBeVisible()
  await expect(sidebar.getByRole('link', { name: 'Watchlist' })).toHaveAttribute('aria-current', 'page')
  await sidebar.getByRole('link', { name: 'Sources' }).click()
  await expect(page.getByRole('heading', { name: 'Source health' })).toBeVisible()
  await sidebar.getByRole('link', { name: 'Settings' }).click()
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
})

test('on a desktop, "/" jumps to the search in the top bar', async ({ page }) => {
  await page.goto('/portfolio')
  await expect(page.getByRole('heading', { name: 'My Portfolio', level: 1 })).toBeVisible()
  await page.keyboard.press('/')
  const search = page.getByRole('banner').getByRole('combobox', { name: 'Find a symbol' })
  await expect(search).toBeFocused()
  await expect(search).toHaveValue('') // the key only moved the focus
})

test.describe('on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('Today, Portfolio, Day trade and Picks are tabs at the bottom, and the other pages are under More', async ({ page }) => {
    await page.goto('/')
    const tabs = page.getByRole('navigation', { name: 'Main' }).last()
    await expect(tabs.getByRole('link', { name: 'Today' })).toHaveAttribute('aria-current', 'page')
    await expect(tabs.getByRole('link')).toHaveText(['Today', 'Portfolio', 'Day trade', 'Picks'])
    await expect(tabs.getByRole('button')).toHaveText(['More']) // the search is the top bar's
    await tabs.getByRole('link', { name: 'Portfolio' }).click()
    await expect(page.getByRole('heading', { name: 'My Portfolio', level: 1 })).toBeVisible()
    await expect(tabs.getByRole('link', { name: 'Portfolio' })).toHaveAttribute('aria-current', 'page')
    await tabs.getByRole('button', { name: 'More' }).click()
    await expect(page.getByRole('dialog', { name: 'More' }).getByRole('link')).toHaveText(['Runners', 'History', 'Invest', 'Watchlist', 'Sources', 'Settings'])
    await page.getByRole('dialog', { name: 'More' }).getByRole('link', { name: 'Watchlist' }).click()
    await expect(page.getByRole('heading', { name: 'Watchlist' })).toBeVisible()
    await expect(tabs.getByRole('button', { name: 'More' })).toHaveAttribute('aria-current', 'page')
    await tabs.getByRole('button', { name: 'More' }).click()
    await page.getByRole('dialog', { name: 'More' }).getByRole('link', { name: 'Settings' }).click()
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
    await expect(tabs.getByRole('button', { name: 'More' })).toHaveAttribute('aria-current', 'page')
  })

  test('the symbol search sits at the top of every page, not under More', async ({ page }) => {
    await seedSymbols([{ symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' }])
    await page.goto('/picks')
    const search = page.getByRole('banner').getByRole('combobox', { name: 'Find a symbol' })
    await expect(search).toBeVisible()
    const box = await search.boundingBox()
    expect(box?.y ?? 999).toBeLessThan(140)
    await page.getByRole('navigation', { name: 'Main' }).last().getByRole('button', { name: 'More' }).click()
    await expect(page.getByRole('dialog', { name: 'More' }).getByRole('combobox', { name: 'Find a symbol' })).toHaveCount(0)
    await page.keyboard.press('Escape')
    await search.fill('royal')
    await page.getByRole('option', { name: /RY\.TO/ }).click()
    await expect(page).toHaveURL(/\/ticker\/RY\.TO/)
  })

  test('the Picks tab opens Picks', async ({ page }) => {
    await page.goto('/')
    const tabs = page.getByRole('navigation', { name: 'Main' }).last()
    await tabs.getByRole('link', { name: 'Picks' }).click()
    await expect(page.getByRole('heading', { name: "Today's Picks", level: 1 })).toBeVisible()
    await expect(tabs.getByRole('link', { name: 'Picks' })).toHaveAttribute('aria-current', 'page')
  })

  test('the More sheet lists the stocks opened lately, newest first', async ({ page }) => {
    await seedSymbols([
      { symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' },
      { symbol: 'AAPL', market: 'US', name: 'Apple Inc.' },
    ])
    const tabs = page.getByRole('navigation', { name: 'Main' }).last()
    const sheet = page.getByRole('dialog', { name: 'More' })
    await page.goto('/')
    await tabs.getByRole('button', { name: 'More' }).click()
    await expect(sheet.getByText('Recent', { exact: true })).toHaveCount(0) // nothing opened yet: no list at all
    await page.keyboard.press('Escape')

    await page.goto('/ticker/AAPL')
    await expect(page.getByRole('heading', { name: 'AAPL', level: 1 })).toBeVisible()
    await page.goto('/ticker/RY.TO')
    await expect(page.getByRole('heading', { name: 'RY.TO', level: 1 })).toBeVisible()
    await tabs.getByRole('button', { name: 'More' }).click()
    await expect(sheet.getByText('Recent', { exact: true })).toBeVisible()
    await expect(sheet.getByRole('listitem').getByRole('link')).toHaveText(['RY.TO', 'AAPL'])
    await sheet.getByRole('link', { name: 'AAPL' }).click()
    await expect(page).toHaveURL(/\/ticker\/AAPL$/)
    await expect(sheet).toBeHidden()
  })

  test('a corrupt or blocked recent list leaves the More sheet without it, without errors (Review Focus 4)', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    await seedSymbols([{ symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' }])
    // A hand-edited value, then storage that refuses every read and write (a blocked WebView).
    await page.addInitScript(() => {
      localStorage.setItem('advisor.recent-symbols', '[1, "<script>", {"a": 2}')
    })
    const tabs = page.getByRole('navigation', { name: 'Main' }).last()
    const sheet = page.getByRole('dialog', { name: 'More' })
    await page.goto('/')
    await tabs.getByRole('button', { name: 'More' }).click()
    await expect(sheet.getByRole('link', { name: 'Runners' })).toBeFocused()
    await expect(sheet.getByText('Recent', { exact: true })).toHaveCount(0)
    await page.keyboard.press('Escape')

    await page.addInitScript(() => {
      Object.defineProperty(window, 'localStorage', {
        get() {
          throw new DOMException('The operation is insecure.', 'SecurityError')
        },
      })
    })
    await page.goto('/ticker/RY.TO')
    await expect(page.getByRole('heading', { name: 'RY.TO', level: 1 })).toBeVisible()
    await tabs.getByRole('button', { name: 'More' }).click()
    await expect(sheet.getByRole('link', { name: 'Runners' })).toBeFocused()
    await expect(sheet.getByText('Recent', { exact: true })).toHaveCount(0)
    expect(errors).toEqual([])
  })

  test('More opens on its first page link, not on the theme switch', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('navigation', { name: 'Main' }).last().getByRole('button', { name: 'More' }).click()
    await expect(page.getByRole('dialog', { name: 'More' }).getByRole('link', { name: 'Runners' })).toBeFocused()
  })

  test('the tab bar, scrolled away, leaves the tab order', async ({ page }) => {
    await page.goto('/')
    // By CSS, not by role: an inert bar is out of the accessibility tree.
    const tabs = page.locator('nav.bottom-tabs')
    await expect(tabs).not.toHaveAttribute('inert')
    await page.evaluate(() => {
      // the Android app's bottom inset (a gesture bar): the hidden bar must still clear the screen
      document.documentElement.style.setProperty('--safe-area-inset-bottom', '34px')
      document.body.style.minHeight = '4000px'
      window.scrollTo(0, 800)
    })
    await expect(tabs).toHaveClass(/hidden/)
    await expect(tabs).toHaveAttribute('inert')
    await expect.poll(() => tabs.evaluate((el) => el.getBoundingClientRect().top - window.innerHeight)).toBeGreaterThanOrEqual(0)
    const today = tabs.locator('a', { hasText: 'Today' })
    await today.evaluate((link: HTMLElement) => link.focus())
    await expect(today).not.toBeFocused()
    await page.evaluate(() => window.scrollTo(0, 0)) // back up: the bar returns and takes the focus again
    await expect(tabs).not.toHaveClass(/hidden/)
    await expect(tabs).not.toHaveAttribute('inert')
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
      ['/', 'Today'],
      ['/portfolio', 'My Portfolio'],
      ['/history', 'History'],
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
      if (path === '/portfolio') {
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

test.describe('on a desktop', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test('no page is wider than the screen, with the runs menu closed or open', async ({ page }) => {
    await seedPortfolio()
    await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
    for (const path of ['/', '/portfolio']) {
      await page.goto(path)
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth), path).toBeLessThanOrEqual(1440)
    }
    // the runs menu opens under its pill, inside the screen
    await page.getByRole('button', { name: /Pre-open/ }).click()
    const menu = page.getByRole('menu')
    await expect(menu).toHaveClass(/open/)
    const box = (await menu.boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(1440)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1440)
  })
})
