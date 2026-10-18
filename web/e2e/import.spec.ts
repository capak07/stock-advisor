import { expect, test, type Page } from '@playwright/test'
import { daysAgo, resetData, seedFx, seedLot, seedSymbols, sql } from './db'

test.beforeEach(async () => {
  await resetData()
  await seedSymbols([
    { symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' },
    { symbol: 'AAPL', market: 'US', name: 'Apple Inc.' },
  ])
  await seedFx([daysAgo(40)], 1.37)
})

/** A Wealthsimple-style activity export: RY in CAD is the TSX listing. */
const csv = (...rows: string[]) =>
  ['Date,Activity Type,Symbol,Quantity,Price,Currency,Account', ...rows].join('\r\n')

async function upload(page: Page, text: string) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Import file' }).click()
  const drawer = page.getByRole('dialog', { name: 'Import a file' })
  await drawer.getByLabel('Activity file (CSV)').setInputFiles({
    name: 'activities.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(text),
  })
  return drawer
}

test('a broker file is imported after its columns are matched and its rows reviewed', async ({ page }) => {
  const drawer = await upload(
    page,
    csv(
      `${daysAgo(30)},Buy,RY,10,C$184.50,CAD,TFSA`,
      `${daysAgo(29)},Buy,AAPL,5,230.00,USD,TFSA`,
      `${daysAgo(20)},Sell,RY,4,190,CAD,TFSA`,
      `${daysAgo(10)},Dividend,RY,,,CAD,TFSA`,
    ),
  )
  await expect(drawer.getByText('activities.csv')).toBeVisible()
  await expect(drawer.getByLabel('What "Activity Type" means')).toHaveValue('side')
  await expect(drawer.getByLabel('What "Price" means')).toHaveValue('price')
  await drawer.getByRole('button', { name: 'Review 4 rows' }).click()

  await expect(drawer.getByText(/ready to import/)).toHaveText('3 ready to import · 1 not a trade')
  await expect(drawer.locator('#import-rows')).toContainText('RY.TO')
  await drawer.getByRole('button', { name: 'Import 3 trades' }).click()

  await expect(page.getByRole('status')).toHaveText('Imported 3 trades')
  await expect(page.locator('#holdings tbody tr')).toHaveCount(2)
  const [counts] = await sql`select (select count(*) from lots)::int as buys, (select count(*) from sells)::int as sells,
    (select fx_rate_cad::float from lots where symbol = 'AAPL') as rate`
  expect(counts).toEqual({ buys: 2, sells: 1, rate: 1.37 }) // the Bank of Canada's rate for the AAPL buy
})

test('importing the same file again adds nothing', async ({ page }) => {
  await seedLot({ account: 'tfsa', symbol: 'RY.TO', asset_type: 'stock', qty: 10, price: 184.5, currency: 'CAD', bought_at: daysAgo(30) })
  const drawer = await upload(page, csv(`${daysAgo(30)},Buy,RY,10,184.50,CAD,TFSA`))
  await drawer.getByRole('button', { name: 'Review 1 rows' }).click()
  await expect(drawer.locator('#import-rows')).toContainText('Already recorded.')
  await expect(drawer.getByRole('button', { name: 'Import 0 trades' })).toBeDisabled()
})

test('a sell of more than is held refuses the whole file', async ({ page }) => {
  const drawer = await upload(
    page,
    csv(`${daysAgo(30)},Buy,RY,10,184.50,CAD,TFSA`, `${daysAgo(20)},Sell,RY,12,190,CAD,TFSA`),
  )
  await drawer.getByRole('button', { name: 'Review 2 rows' }).click()
  await drawer.getByRole('button', { name: 'Import 2 trades' }).click()
  await expect(drawer.getByRole('alert')).toContainText('Nothing was imported.')
  await expect(drawer.getByRole('alert')).toContainText('sold 12 but held 10')
  expect(await sql`select 1 from lots`).toHaveLength(0)
})

test('a stock missing from the lists is left out unless the owner includes it', async ({ page }) => {
  const drawer = await upload(
    page,
    csv(`${daysAgo(30)},Buy,RY,10,184.50,CAD,TFSA`, `${daysAgo(30)},Buy,XEQT,20,35,CAD,TFSA`),
  )
  await drawer.getByRole('button', { name: 'Review 2 rows' }).click()
  await expect(drawer.getByText(/1 not in the stock lists/)).toBeVisible()
  await expect(drawer.getByRole('button', { name: 'Import 1 trade' })).toBeEnabled()
  await drawer.getByLabel(/Import the 1 not in the lists too/).check()
  await drawer.getByRole('button', { name: 'Import 2 trades' }).click()
  await expect(page.getByRole('status')).toHaveText('Imported 2 trades')
  expect(await sql`select symbol from lots order by symbol`).toEqual([{ symbol: 'RY.TO' }, { symbol: 'XEQT.TO' }])
})
