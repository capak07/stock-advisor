import 'server-only'
import { assetKey, type AssetType } from '../portfolio/types'
import type { Supabase } from '../supabase/server'
import { fetchAll } from './fetch'
import type { AssetRef } from './portfolio'
import type { ForecastHorizon } from './ticker'

/**
 * A run's forecasts for the watched symbols (spec §7.6), by asset key, each with its benchmark and
 * every horizon, shortest first. Read-only; one query for the watched symbols, not the whole run.
 * A symbol the run did not forecast (a coin outside the model, one added since) has no entry.
 */
export async function loadWatchOutlooks(
  supabase: Supabase,
  runId: number,
  items: readonly AssetRef[],
): Promise<Map<string, { benchmark: string; horizons: ForecastHorizon[] }>> {
  const outlooks = new Map<string, { benchmark: string; horizons: ForecastHorizon[] }>()
  const symbols = [...new Set(items.map((i) => i.symbol))]
  if (symbols.length === 0) return outlooks
  const wanted = new Set(items.map((i) => assetKey(i.assetType, i.symbol)))
  const rows = (await fetchAll((from, to) =>
    supabase
      .from('predictions')
      .select('symbol, asset_type, horizon_days, q10, q50, q90, p_beat, benchmark')
      .eq('run_id', runId)
      .in('symbol', symbols)
      .order('symbol')
      .order('asset_type')
      .order('horizon_days')
      .range(from, to),
  )) as {
    symbol: string
    asset_type: AssetType
    horizon_days: number
    q10: number | string
    q50: number | string
    q90: number | string
    p_beat: number | string
    benchmark: string
  }[]
  for (const r of rows) {
    const key = assetKey(r.asset_type, r.symbol)
    // LINK the coin is watched, LINK the stock is not
    if (!wanted.has(key)) continue
    const entry = outlooks.get(key) ?? { benchmark: r.benchmark, horizons: [] }
    entry.horizons.push({ horizon: r.horizon_days, q10: Number(r.q10), q50: Number(r.q50), q90: Number(r.q90), pBeat: Number(r.p_beat) })
    outlooks.set(key, entry)
  }
  return outlooks
}
