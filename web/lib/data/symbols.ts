import 'server-only'
import type { Supabase } from '../supabase/server'
import { must } from './fetch'

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
