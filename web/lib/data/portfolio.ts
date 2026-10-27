import 'server-only'
import { addDays } from '../dates'
import { FxRates, PriceBook } from '../portfolio/lookup'
import { assetKey } from '../portfolio/types'
import type { Account, AssetType, Close, Currency, RecordedTrade, Trade } from '../portfolio/types'
import type { Supabase } from '../supabase/server'
import { fetchAll } from './fetch'
import { loadSettings, type Settings } from './settings'
import { loadNames, loadSectors } from './symbols'

interface TradeRow {
  id: number
  account: Account
  symbol: string
  asset_type: AssetType
  qty: string | number
  price: string | number
  currency: Currency
  fx_rate_cad: string | number | null
}

const toTrade = (side: Trade['side'], day: string, row: TradeRow): RecordedTrade => ({
  id: row.id,
  side,
  account: row.account,
  symbol: row.symbol,
  assetType: row.asset_type,
  qty: Number(row.qty),
  price: Number(row.price),
  currency: row.currency,
  fxRateCad: row.fx_rate_cad === null ? null : Number(row.fx_rate_cad),
  day,
})

const TRADE_COLUMNS = 'id, account, symbol, asset_type, qty, price, currency, fx_rate_cad'

/** Every buy (`lots`) and sell (`sells`), or only one asset's. Postgres numerics arrive as strings. */
export async function loadTrades(supabase: Supabase, only?: AssetRef): Promise<RecordedTrade[]> {
  const lotsQuery = () => {
    const query = supabase.from('lots').select(`${TRADE_COLUMNS}, bought_at`)
    return only ? query.eq('symbol', only.symbol).eq('asset_type', only.assetType) : query
  }
  const sellsQuery = () => {
    const query = supabase.from('sells').select(`${TRADE_COLUMNS}, sold_at`)
    return only ? query.eq('symbol', only.symbol).eq('asset_type', only.assetType) : query
  }
  const [lots, sells] = await Promise.all([
    fetchAll((from, to) => lotsQuery().order('id').range(from, to)),
    fetchAll((from, to) => sellsQuery().order('id').range(from, to)),
  ])
  return [
    ...(lots as (TradeRow & { bought_at: string })[]).map((r) => toTrade('buy', r.bought_at, r)),
    ...(sells as (TradeRow & { sold_at: string })[]).map((r) => toTrade('sell', r.sold_at, r)),
  ]
}

export async function loadFx(supabase: Supabase): Promise<FxRates> {
  const rows = (await fetchAll((from, to) =>
    supabase.from('fx_rates').select('day, usd_cad').order('day').range(from, to),
  )) as { day: string; usd_cad: string | number }[]
  return new FxRates(rows.map((r) => ({ day: r.day, usdCad: Number(r.usd_cad) })))
}

export interface AssetRef {
  symbol: string
  assetType: AssetType
}

/** Closes for these assets from `since` on, one request per asset type and page. */
export async function loadCloses(supabase: Supabase, assets: readonly AssetRef[], since: string): Promise<PriceBook> {
  const byKey = new Map<string, Close[]>()
  for (const assetType of ['stock', 'crypto'] as const) {
    const symbols = [...new Set(assets.filter((a) => a.assetType === assetType).map((a) => a.symbol))]
    if (symbols.length === 0) continue
    const rows = (await fetchAll((from, to) =>
      supabase
        .from('daily_closes')
        .select('symbol, day, close, currency')
        .eq('asset_type', assetType)
        .in('symbol', symbols)
        .gte('day', since)
        .order('symbol')
        .order('day')
        .range(from, to),
    )) as { symbol: string; day: string; close: string | number; currency: Currency }[]
    for (const row of rows) {
      const key = assetKey(assetType, row.symbol)
      const list = byKey.get(key) ?? []
      list.push({ day: row.day, close: Number(row.close), currency: row.currency })
      byKey.set(key, list)
    }
  }
  return new PriceBook(byKey)
}

export const BENCHMARK_ASSETS: AssetRef[] = [
  { symbol: 'XIU.TO', assetType: 'stock' },
  { symbol: 'SPY', assetType: 'stock' },
]

export interface PortfolioData {
  trades: RecordedTrade[]
  prices: PriceBook
  fx: FxRates
  names: Map<string, string>
  sectors: Map<string, string>
  settings: Settings
}

/** Everything the portfolio page values and charts. */
export async function loadPortfolio(supabase: Supabase): Promise<PortfolioData> {
  const [trades, fx, settings] = await Promise.all([loadTrades(supabase), loadFx(supabase), loadSettings(supabase)])
  const traded = trades.map((t) => ({ symbol: t.symbol, assetType: t.assetType }))
  const firstDay = trades.reduce<string | null>((min, t) => (min === null || t.day < min ? t.day : min), null)
  // A week before the first buy, so a buy on a holiday still finds the close before it.
  const since = firstDay === null ? '9999-12-31' : addDays(firstDay, -7)
  const stocks = traded.filter((a) => a.assetType === 'stock').map((a) => a.symbol)
  const [prices, names, sectors] = await Promise.all([
    loadCloses(supabase, firstDay === null ? [] : [...traded, ...BENCHMARK_ASSETS], since),
    loadNames(supabase, stocks),
    loadSectors(supabase, stocks),
  ])
  return { trades, prices, fx, names, sectors, settings }
}
