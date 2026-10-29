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
  // runs cascades to source_health, features_live, predictions, picks and verdicts; models to model_files
  await sql`truncate lots, sells, watchlist, runs, daily_closes, fx_rates, symbols, news_items, sources, models
            restart identity cascade`
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

/** Coins in the stored coin list, as the pipeline's daily CoinGecko refresh writes them. */
export async function seedCoins(rows: { symbol: string; name: string; marketCap: number }[]) {
  for (const r of rows) {
    await sql`insert into symbols (symbol, asset_type, name, exchange, market_cap)
              values (${r.symbol}, 'crypto', ${r.name}, 'CoinGecko', ${r.marketCap})`
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
  const [row] = await sql`insert into runs (kind, et_date, started_at, finished_at, status, published, sources_ok, sources_total, summary)
            values (${run.kind}, ${todayInToronto(finished)}, ${new Date(finished.getTime() - 15 * 60_000)}, ${finished},
                    ${run.status}, ${run.published}, 30, 33, ${sql.json(run.summary ?? {})}) returning id`
  return row.id as number
}

/** A run's action for one holding, as the pipeline's portfolio stage writes it. */
export async function seedHoldingAction(
  runId: number,
  row: {
    account: string
    symbol: string
    asset_type: 'stock' | 'crypto'
    action: 'sell' | 'trim' | 'add' | 'hold'
    review?: boolean
    reasons: string[]
    warnings?: string[]
    trailing_stop?: number | null
    q10?: number | null
    q50?: number | null
    q90?: number | null
    horizon_days?: number | null
    exit_by?: string | null
    risk_level?: 'low' | 'medium' | 'high' | 'very_high' | null
    ref_price?: number | null
  },
) {
  const { reasons, warnings = [], ...rest } = row
  await sql`insert into holding_actions ${sql({
    run_id: runId,
    review: false,
    ref_price: null,
    trailing_stop: null,
    q10: null,
    q50: null,
    q90: null,
    horizon_days: null,
    exit_by: null,
    risk_level: null,
    ...rest,
    reasons: sql.json(reasons),
    warnings: sql.json(warnings),
  })}`
}

/** A small registry like the pipeline's: US-only filings, a source for both markets, a coin source. */
export const SOURCES = [
  { name: 'yfinance_bars', category: 'prices', core: true, cadence: 'per_run', asset_types: ['stock'], markets: ['TSX', 'US'] },
  { name: 'google_news', category: 'news', core: true, cadence: 'per_run', asset_types: ['crypto', 'stock'], markets: ['TSX', 'US'] },
  { name: 'sec_form4', category: 'fundamentals', core: false, cadence: 'daily', asset_types: ['stock'], markets: ['US'] },
  { name: 'sec_8k', category: 'catalysts', core: false, cadence: 'daily', asset_types: ['stock'], markets: ['US'] },
  { name: 'coingecko', category: 'prices', core: true, cadence: 'per_run', asset_types: ['crypto'], markets: [] },
]

export async function seedSources() {
  await sql`insert into sources ${sql(SOURCES, 'name', 'category', 'core', 'cadence', 'asset_types', 'markets')}`
}

/** Health rows for a run, or for a daily check when `runId` is null. */
export async function seedHealth(
  runId: number | null,
  attemptedAt: string,
  rows: { source: string; status: string; latency_ms?: number; records?: number; error?: string; consecutive_failures?: number }[],
) {
  for (const r of rows) {
    await sql`insert into source_health ${sql({
      run_id: runId,
      context: runId === null ? 'health' : 'run',
      latency_ms: 100,
      records: 10,
      error: null,
      consecutive_failures: 0,
      attempted_at: attemptedAt,
      ...r,
    })}`
  }
}

export async function seedNews(
  rows: { symbol: string; asset_type: 'stock' | 'crypto'; hoursAgo: number; outlet: string; url: string; title: string; sentiment: number | null }[],
) {
  for (const [i, { hoursAgo, ...r }] of rows.entries()) {
    await sql`insert into news_items ${sql({
      ...r,
      published_at: new Date(Date.now() - hoursAgo * 3_600_000),
      cluster_id: `story-${i}`,
      story_key: `key-${i}`,
    })}`
  }
}

export async function seedFeatures(runId: number, symbol: string, assetType: 'stock' | 'crypto', features: JSONValue) {
  await sql`insert into features_live (run_id, symbol, asset_type, features, as_of)
            values (${runId}, ${symbol}, ${assetType}, ${sql.json(features)}, now())`
}

/** A market's active model, with its backtest gate in `metrics` (picks_enabled, picks_reason). */
export async function seedModel(kind: 'stock_us' | 'stock_tsx', metrics: JSONValue) {
  await sql`insert into models (version, kind, trained_at, metrics, active)
            values (${`${kind}-test`}, ${kind}, now(), ${sql.json(metrics)}, true)`
}

/** A run's forecast for one asset at one horizon. A coin is judged against BTC, and BTC against SPY. */
export async function seedPrediction(
  runId: number,
  symbol: string,
  horizon: number,
  q: { q10: number; q50: number; q90: number; p: number },
  asset: 'stock' | 'crypto' = 'stock',
) {
  const benchmark =
    asset === 'crypto' ? (symbol === 'BTC' ? 'SPY' : 'BTC') : symbol.endsWith('.TO') ? 'XIU.TO' : 'SPY'
  await sql`insert into predictions (run_id, symbol, asset_type, horizon_days, q10, q50, q90, p_beat, benchmark, model_version)
            values (${runId}, ${symbol}, ${asset}, ${horizon}, ${q.q10}, ${q.q50}, ${q.q90}, ${q.p}, ${benchmark}, 'test')`
}

/** A pick as stage 8 writes it; returns its id. */
export async function seedPick(
  runId: number,
  pick: {
    symbol: string
    market: 'US' | 'TSX'
    style: 'swing' | 'position'
    horizon: number
    rank: number
    exitBy: string
    entry: number
    stop: number
    riskLevel: 'low' | 'medium' | 'high' | 'very_high'
    maxPct: number
    topFactors?: { feature: string; contribution: number }[]
    catalysts?: JSONValue[]
    status?: 'open' | 'exited_early' | 'graded'
  },
) {
  const [row] = await sql`insert into picks ${sql({
    run_id: runId,
    symbol: pick.symbol,
    asset_type: 'stock',
    market: pick.market,
    style: pick.style,
    horizon_days: pick.horizon,
    exit_by: pick.exitBy,
    entry_ref_price: pick.entry,
    stop: pick.stop,
    risk_level: pick.riskLevel,
    risk_score: 50,
    max_position_pct: pick.maxPct,
    rank: pick.rank,
    top_factors: sql.json(pick.topFactors ?? []),
    catalysts: sql.json(pick.catalysts ?? []),
    status: pick.status ?? 'open',
  })} returning id`
  return Number(row.id) // a bigint arrives as a string
}

/** A pick's graded outcome; `gradedAt` decides which run's grading wrote it. */
export async function seedOutcome(
  pickId: number,
  o: { exitPrice: number; exitReason: string; ret: number; benchRet: number; beat: boolean; hitStop?: boolean; gradedAt?: Date },
) {
  await sql`insert into pick_outcomes ${sql({
    pick_id: pickId,
    exit_price: o.exitPrice,
    exit_reason: o.exitReason,
    ret: o.ret,
    ret_net_of_fx: o.ret,
    bench_ret: o.benchRet,
    excess: o.ret - o.benchRet,
    beat: o.beat,
    hit_stop: o.hitStop ?? false,
    graded_at: o.gradedAt ?? new Date(),
  })}`
}

export async function seedVerdict(
  runId: number,
  v: { symbol: string; assetType: 'stock' | 'crypto'; verdict: 'buy' | 'hold' | 'avoid'; reasons: string[]; details?: JSONValue },
) {
  await sql`insert into watchlist_verdicts (run_id, symbol, asset_type, verdict, reasons, details)
            values (${runId}, ${v.symbol}, ${v.assetType}, ${v.verdict}, ${sql.json(v.reasons)}, ${sql.json(v.details ?? {})})`
}

/** RY.TO and AAPL in the TFSA, ETH in the crypto account (part sold at a loss 5 days ago). */
export async function seedPortfolio() {
  const days = weekdays(daysAgo(60))
  const allDays = Array.from({ length: 61 }, (_, i) => daysAgo(60 - i)).filter((d) => d < daysAgo(0))
  await seedSymbols([
    { symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' },
    { symbol: 'AAPL', market: 'US', name: 'Apple Inc.' },
  ])
  await seedCoins([{ symbol: 'ETH', name: 'Ethereum', marketCap: 4.1e11 }])
  await seedFx(days, 1.4)
  await seedCloses('XIU.TO', 'stock', 'CAD', days, 40, 0.05)
  await seedCloses('SPY', 'stock', 'USD', days, 500, 0.5)
  await seedCloses('RY.TO', 'stock', 'CAD', days, 170, 0.25)
  await seedCloses('AAPL', 'stock', 'USD', days, 200, 0.5)
  await seedCloses('ETH', 'crypto', 'USD', allDays, 3000, -5)
  await seedLot({ account: 'tfsa', symbol: 'RY.TO', asset_type: 'stock', qty: 10, price: 170, currency: 'CAD', bought_at: days[0] })
  await seedLot({ account: 'tfsa', symbol: 'AAPL', asset_type: 'stock', qty: 5, price: 200, currency: 'USD', fx_rate_cad: 1.4, bought_at: days[0] })
  await seedLot({ account: 'crypto', symbol: 'ETH', asset_type: 'crypto', qty: 2, price: 4200, currency: 'CAD', bought_at: days[0] })
  await seedSell({ account: 'crypto', symbol: 'ETH', asset_type: 'crypto', qty: 1, price: 3900, currency: 'CAD', sold_at: daysAgo(5) })
}
