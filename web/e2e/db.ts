import postgres, { type JSONValue } from 'postgres'
import { addDays, todayInToronto } from '../lib/dates'
import { localStack } from './stack'

const DB_URL = localStack().DB_URL
// These helpers truncate tables: refuse anything but a database on this machine.
if (!/@(127\.0\.0\.1|localhost):/.test(DB_URL)) throw new Error(`Refusing to seed a database that isn't local: ${DB_URL}`)

/** Direct SQL on the local stack's database, as its superuser, for seeding and checking. */
export const sql = postgres(DB_URL, { onnotice: () => {} })

/** Everything the owner or a run writes, emptied between tests. Users and app_config stay. */
export async function resetData() {
  await sql`truncate lots, sells, watchlist, runs, daily_closes, fx_rates, symbols restart identity cascade`
  await sql`update settings set usd_fx_fee_pct = 1.5, crypto_fee_pct = 2.0, tfsa_round_trips_warn = 24,
            tfsa_short_hold_share_warn = 0.5, updated_at = now() where id = 1`
}

export const today = () => todayInToronto()
export const daysAgo = (n: number) => addDays(today(), -n)

/** Weekdays from `from` to yesterday. */
export function weekdays(from: string): string[] {
  const days: string[] = []
  for (let day = from; day < today(); day = addDays(day, 1)) {
    const weekday = new Date(`${day}T12:00:00Z`).getUTCDay()
    if (weekday !== 0 && weekday !== 6) days.push(day)
  }
  return days
}

export async function seedSymbols(rows: { symbol: string; market: 'US' | 'TSX'; name: string }[]) {
  for (const r of rows) {
    await sql`insert into symbols (symbol, asset_type, market, name, exchange)
              values (${r.symbol}, 'stock', ${r.market}, ${r.name}, ${r.market === 'TSX' ? 'TSX' : 'NYSE'})`
  }
}

/** A close for every day, rising by `step` a day from `start`. */
export async function seedCloses(
  symbol: string,
  assetType: 'stock' | 'crypto',
  currency: 'USD' | 'CAD',
  days: string[],
  start: number,
  step: number,
) {
  const rows = days.map((day, i) => ({ symbol, asset_type: assetType, day, close: start + step * i, currency }))
  if (rows.length) await sql`insert into daily_closes ${sql(rows)}`
}

export async function seedFx(days: string[], usdCad = 1.37) {
  const rows = days.map((day) => ({ day, usd_cad: usdCad }))
  if (rows.length) await sql`insert into fx_rates ${sql(rows)}`
}

export async function seedLot(lot: {
  account: string
  symbol: string
  asset_type: 'stock' | 'crypto'
  qty: number
  price: number
  currency: 'USD' | 'CAD'
  fx_rate_cad?: number | null
  bought_at: string
}) {
  await sql`insert into lots ${sql({ fx_rate_cad: null, ...lot })}`
}

export async function seedSell(sell: {
  account: string
  symbol: string
  asset_type: 'stock' | 'crypto'
  qty: number
  price: number
  currency: 'USD' | 'CAD'
  sold_at: string
}) {
  await sql`insert into sells ${sql({ fx_rate_cad: null, ...sell })}`
}

export async function seedRun(run: {
  kind: 'pre_open' | 'pre_close' | 'early_close'
  status: 'success' | 'degraded' | 'failed' | 'running'
  published: boolean
  finished: string
  summary?: JSONValue
}) {
  const finished = new Date(run.finished)
  await sql`insert into runs (kind, et_date, started_at, finished_at, status, published, sources_ok, sources_total, summary)
            values (${run.kind}, ${todayInToronto(finished)}, ${new Date(finished.getTime() - 15 * 60_000)}, ${finished},
                    ${run.status}, ${run.published}, 30, 33, ${sql.json(run.summary ?? {})})`
}
