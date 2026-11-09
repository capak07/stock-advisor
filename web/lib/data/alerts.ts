import 'server-only'
import type { AssetType } from '../portfolio/types'
import type { Supabase } from '../supabase/server'
import { must } from './fetch'

/** Active (not yet hit) alerts on one asset. */
export async function countActiveAlerts(supabase: Supabase, symbol: string, assetType: AssetType): Promise<number> {
  const { count, error } = await supabase
    .from('price_alerts')
    .select('id', { count: 'exact', head: true })
    .eq('symbol', symbol)
    .eq('asset_type', assetType)
    .is('hit_at', null)
  if (error) throw new Error(error.message)
  return count ?? 0
}

/** Whether the app knows the asset: in its symbol lists, or with stored closes. */
export async function isKnownAsset(supabase: Supabase, symbol: string, assetType: AssetType): Promise<boolean> {
  const [listed, priced] = await Promise.all([
    supabase.from('symbols').select('symbol').eq('asset_type', assetType).eq('symbol', symbol).limit(1),
    supabase.from('daily_closes').select('symbol').eq('asset_type', assetType).eq('symbol', symbol).limit(1),
  ])
  return (must(listed) as unknown[]).length > 0 || (must(priced) as unknown[]).length > 0
}
