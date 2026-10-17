import 'server-only'
import type { AssetType } from '../portfolio/types'
import type { Supabase } from '../supabase/server'
import { must } from './fetch'
import type { AssetRef } from './portfolio'

export interface WatchItem extends AssetRef {
  addedAt: string
}

/** The watchlist, newest first. */
export async function loadWatchlist(supabase: Supabase): Promise<WatchItem[]> {
  const rows = must(
    await supabase.from('watchlist').select('symbol, asset_type, added_at').order('added_at', { ascending: false }),
  ) as { symbol: string; asset_type: AssetType; added_at: string }[]
  return rows.map((r) => ({ symbol: r.symbol, assetType: r.asset_type, addedAt: r.added_at }))
}
