import 'server-only'
import type { AssetType } from '../portfolio/types'
import type { Supabase } from '../supabase/server'
import { displayName, type SearchItem } from '../symbol-search'
import { marketOf } from '../symbols'
import { fetchAll, must } from './fetch'

/** Company names of listed stocks; coins have none stored. */
export async function loadNames(supabase: Supabase, symbols: readonly string[]): Promise<Map<string, string>> {
  if (symbols.length === 0) return new Map()
  const rows = must(
    await supabase.from('symbols').select('symbol, name').eq('asset_type', 'stock').in('symbol', [...new Set(symbols)]),
  ) as { symbol: string; name: string }[]
  return new Map(rows.map((r) => [r.symbol, r.name]))
}

/** Whether a stock is in the US or TSX lists the pipeline keeps (ETFs aren't). */
export async function isListedStock(supabase: Supabase, symbol: string): Promise<boolean> {
  const rows = must(
    await supabase.from('symbols').select('symbol').eq('asset_type', 'stock').eq('symbol', symbol).limit(1),
  ) as unknown[]
  return rows.length > 0
}

/** Whether a symbol is in the active stock lists or the stored coin list: the watchlist takes only these. */
export async function isWatchable(supabase: Supabase, symbol: string, assetType: AssetType): Promise<boolean> {
  const rows = must(
    await supabase.from('symbols').select('symbol').eq('asset_type', assetType).eq('symbol', symbol).eq('active', true).limit(1),
  ) as unknown[]
  return rows.length > 0
}

/** What the search boxes offer: every active listed stock by symbol, then the stored coins, biggest first. */
export async function loadSearchItems(supabase: Supabase): Promise<SearchItem[]> {
  const [stocks, coins] = (await Promise.all([
    fetchAll((from, to) =>
      supabase.from('symbols').select('symbol, name').eq('asset_type', 'stock').eq('active', true).order('symbol').range(from, to),
    ),
    fetchAll((from, to) =>
      supabase
        .from('symbols')
        .select('symbol, name')
        .eq('asset_type', 'crypto')
        .eq('active', true)
        .order('market_cap', { ascending: false, nullsFirst: false })
        .order('symbol')
        .range(from, to),
    ),
  ])) as { symbol: string; name: string }[][]
  return [
    ...stocks.map((r): SearchItem => ({ symbol: r.symbol, name: displayName(r.name), assetType: 'stock', kind: marketOf(r.symbol) })),
    ...coins.map((r): SearchItem => ({ symbol: r.symbol, name: r.name, assetType: 'crypto', kind: 'Crypto' })),
  ]
}
