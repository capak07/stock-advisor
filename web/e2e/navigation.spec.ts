import { expect, test } from '@playwright/test'
import { resetData } from './db'

test.beforeEach(resetData)

test('the sidebar reaches every page and marks the current one', async ({ page }) => {
  await page.goto('/')
  const sidebar = page.getByRole('complementary', { name: 'Main' })
  await expect(sidebar.getByRole('link', { name: 'Portfolio' })).toHaveAttribute('aria-current', 'page')
  await sidebar.getByRole('link', { name: 'Watchlist' }).click()
  await expect(page.getByRole('heading', { name: 'Watchlist' })).toBeVisible()
  await expect(sidebar.getByRole('link', { name: 'Watchlist' })).toHaveAttribute('aria-current', 'page')
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
    for (const [path, heading] of [['/', 'My Portfolio'], ['/watchlist', 'Watchlist'], ['/settings', 'Settings']]) {
      await page.goto(path)
      await expect(page.getByRole('heading', { name: heading, level: 1 })).toBeVisible()
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow, path).toBeLessThanOrEqual(0)
    }
  })
})
