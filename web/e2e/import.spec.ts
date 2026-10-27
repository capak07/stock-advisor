import { expect, test, type Page } from '@playwright/test'
import { daysAgo, resetData, seedFx, seedLot, seedSymbols, sql } from './db'

test.beforeEach(async () => {
  await resetData()
  await seedSymbols([
    { symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' },
    { symbol: 'AAPL', market: 'US', name: 'Apple Inc.' },
    { symbol: 'VEEA', market: 'US', name: 'Veea Inc.' },
  ])
  await seedFx([daysAgo(40)], 1.37)
})

/** A Wealthsimple-style activity export: RY in CAD is the TSX listing. */
const csv = (...rows: string[]) =>
  ['Date,Activity Type,Symbol,Quantity,Price,Currency,Account', ...rows].join('\r\n')

async function upload(page: Page, text: string, name = 'activities.csv') {
  await page.goto('/')
  await page.getByRole('button', { name: 'Import file' }).click()
  const drawer = page.getByRole('dialog', { name: 'Import a file' })
  await drawer.getByLabel('Activity file or holdings report (CSV)').setInputFiles({
    name,
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

test("a trade recorded after the file was reviewed isn't imported twice", async ({ page }) => {
  const drawer = await upload(page, csv(`${daysAgo(30)},Buy,RY,10,184.50,CAD,TFSA`, `${daysAgo(25)},Buy,RY,5,186,CAD,TFSA`))
  await drawer.getByRole('button', { name: 'Review 2 rows' }).click()
  await expect(drawer.getByText(/ready to import/)).toHaveText('2 ready to import')
  // Another tab records one of them meanwhile.
  await seedLot({ account: 'tfsa', symbol: 'RY.TO', asset_type: 'stock', qty: 10, price: 184.5, currency: 'CAD', bought_at: daysAgo(30) })
  await drawer.getByRole('button', { name: 'Import 2 trades' }).click()
  await expect(page.getByRole('status')).toHaveText('Imported 1 trade (1 already recorded, skipped)')
  const [{ n }] = await sql`select count(*)::int as n from lots`
  expect(n).toBe(2)
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

/** Make the database refuse inserts into sells and/or deletes from lots while `run` runs. */
async function refusing(which: { sells?: boolean; lotDeletes?: boolean }, run: () => Promise<void>) {
  try {
    if (which.sells) {
      await sql.unsafe(`create function refuse_sells_fn() returns trigger language plpgsql as $$ begin raise exception 'sells refused'; end $$`)
      await sql.unsafe(`create trigger refuse_sells before insert on sells for each row execute function refuse_sells_fn()`)
    }
    if (which.lotDeletes) {
      await sql.unsafe(`create function refuse_lot_deletes_fn() returns trigger language plpgsql as $$ begin raise exception 'deletes refused'; end $$`)
      await sql.unsafe(`create trigger refuse_lot_deletes before delete on lots for each row execute function refuse_lot_deletes_fn()`)
    }
    await run()
  } finally {
    await sql.unsafe(`drop trigger if exists refuse_sells on sells`)
    await sql.unsafe(`drop function if exists refuse_sells_fn()`)
    await sql.unsafe(`drop trigger if exists refuse_lot_deletes on lots`)
    await sql.unsafe(`drop function if exists refuse_lot_deletes_fn()`)
  }
}

const buyAndSell = csv(`${daysAgo(30)},Buy,RY,10,184.50,CAD,TFSA`, `${daysAgo(20)},Sell,RY,4,190,CAD,TFSA`)

test('when the database refuses the sells, none of the file\'s buys stay', async ({ page }) => {
  await refusing({ sells: true }, async () => {
    const drawer = await upload(page, buyAndSell)
    await drawer.getByRole('button', { name: 'Review 2 rows' }).click()
    await drawer.getByRole('button', { name: 'Import 2 trades' }).click()
    await expect(drawer.getByRole('alert')).toContainText('Nothing was imported: sells refused')
    const [{ n }] = await sql`select count(*)::int as n from lots`
    expect(n).toBe(0)
  })
})

test('when the buys can\'t be taken back, the drawer says so', async ({ page }) => {
  await refusing({ sells: true, lotDeletes: true }, async () => {
    const drawer = await upload(page, buyAndSell)
    await drawer.getByRole('button', { name: 'Review 2 rows' }).click()
    await drawer.getByRole('button', { name: 'Import 2 trades' }).click()
    await expect(drawer.getByRole('alert')).toContainText('Only the buys went in: the sells failed')
    await expect(drawer.getByRole('alert')).toContainText("couldn't be taken back")
    const [{ n }] = await sql`select count(*)::int as n from lots`
    expect(n).toBe(1)
  })
})

/** Wealthsimple's holdings report, dated today (month/day/year); the account numbers are made up. */
function holdingsReport(...rows: string[]) {
  const [y, m, d] = daysAgo(0).split('-')
  const header =
    'Account Name,Account Type,Account Classification,Account Number,Symbol,Exchange,MIC,Name,Security Type,Quantity,Position Direction,Market Price,Market Price Currency,Book Value (CAD),Book Value Currency (CAD),Book Value (Market),Book Value Currency (Market),Market Value,Market Value Currency,Market Unrealized Returns,Market Unrealized Returns Currency,,,,Date'
  return [header, ...rows.map((r) => `${r},,,,${m}/${d}/${y}`)].join('\r\n')
}
const BONK = 'Crypto,Crypto,Trade,AAAA00000CAD,BONK,,,Bonk,CRYPTOCURRENCY,95934743,LONG,4.28956E-06,CAD,500,CAD,500,CAD,411.35,CAD,-88.65,CAD'
const VEEA = 'TFSA,TFSA,Trade,BBBB00000CAD,VEEA,NASDAQ,XNAS,Veea Inc.,EQUITY,118,LONG,6,USD,986.36,CAD,678.4977517,USD,708,USD,29.50,USD'
const RY = 'TFSA,TFSA,Trade,BBBB00000CAD,RY,TSX,XTSE,Royal Bank of Canada,EQUITY,10,LONG,190,CAD,1845,CAD,1845,CAD,1900,CAD,55,CAD'

test('a holdings report seeds every position at its book value, without matching columns', async ({ page }) => {
  const drawer = await upload(page, holdingsReport(BONK, VEEA, RY), 'holdings-report.csv')
  await expect(drawer.getByText('2 · Review')).toBeVisible()
  await expect(drawer.getByText(/ready to import/)).toHaveText('3 ready to import')
  await expect(drawer.locator('#import-rows')).toContainText('RY.TO')
  await drawer.getByRole('button', { name: 'Import 3 trades' }).click()

  await expect(page.getByRole('status')).toHaveText('Imported 3 trades')
  await expect(page.locator('#holdings tbody tr')).toHaveCount(3)
  const lots = await sql`select symbol, bought_at::text as day, (qty * price * coalesce(fx_rate_cad, 1))::float as cad
    from lots order by symbol`
  expect(lots.map((l) => [l.symbol, l.day, Math.round(l.cad * 100) / 100])).toEqual([
    ['BONK', daysAgo(0), 500],
    ['RY.TO', daysAgo(0), 1845],
    ['VEEA', daysAgo(0), 986.36],
  ])
})

test("a later holdings report adds what changed, and the same report again adds nothing", async ({ page }) => {
  await seedLot({ account: 'tfsa', symbol: 'VEEA', asset_type: 'stock', qty: 100, price: 5.5, currency: 'USD', fx_rate_cad: 1.45, bought_at: daysAgo(30) })
  await seedLot({ account: 'tfsa', symbol: 'RY.TO', asset_type: 'stock', qty: 15, price: 180, currency: 'CAD', bought_at: daysAgo(30) })
  let drawer = await upload(page, holdingsReport(VEEA, RY), 'holdings-report.csv')
  await expect(drawer.locator('#import-rows')).toContainText('Up from 100.')
  await expect(drawer.locator('#import-rows')).toContainText('Down from 15.')
  await drawer.getByRole('button', { name: 'Import 2 trades' }).click()
  await expect(page.getByRole('status')).toHaveText('Imported 2 trades')

  const [veea] = await sql`select sum(qty * price * fx_rate_cad)::float as cad, sum(qty)::float as qty from lots where symbol = 'VEEA'`
  expect([veea.qty, Math.round(veea.cad * 100) / 100]).toEqual([118, 986.36])
  const [sell] = await sql`select qty::float, price::float, sold_at::text as day from sells`
  expect(sell).toEqual({ qty: 5, price: 190, day: daysAgo(0) })

  drawer = await upload(page, holdingsReport(VEEA, RY), 'holdings-report.csv')
  await expect(drawer.getByText(/ready to import/)).toHaveText('0 ready to import · 2 already recorded or repeated')
})
