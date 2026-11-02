import 'server-only'
import type { AssetType } from '../portfolio/types'
import { assetKey } from '../portfolio/types'
import type { Run } from '../runs'
import type { Supabase } from '../supabase/server'
import type { HeldCall, Verdict } from '../verdicts'
import { loadHeldCalls } from './actions'
import { must } from './fetch'
import type { AssetRef } from './portfolio'
import { lastPublishedRun } from './runs'

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

export interface StoredVerdict {
  verdict: Verdict
  reasons: string[]
  details: Record<string, unknown>
  /** A stock's 14-day daily range and 20-day dollar volume this run, for a Buy's order guidance (lib/orders.ts). */
  atrPct: number | null
  dollarVolume20: number | null
  /** A stock Buy's top of the forecast range at its hold, for a bracket's take-profit; else null. */
  q90: number | null
}

const num = (value: unknown): number | null => {
  const n = typeof value === 'string' ? Number(value) : value
  return typeof n === 'number' && Number.isFinite(n) ? n : null
}

/**
 * The latest published run's verdicts by asset key, and what My Portfolio said that run of each
 * symbol held (a watched symbol you hold shows that instead of its verdict); null before any published run.
 */
export async function loadVerdicts(
  supabase: Supabase,
): Promise<{ run: Run; verdicts: Map<string, StoredVerdict>; held: Map<string, HeldCall> } | null> {
  const run = await lastPublishedRun(supabase)
  if (!run) return null
  const [verdictRows, held] = await Promise.all([
    supabase.from('watchlist_verdicts').select('symbol, asset_type, verdict, reasons, details').eq('run_id', run.id),
    loadHeldCalls(supabase, run.id),
  ])
  const rows = must(verdictRows) as { symbol: string; asset_type: AssetType; verdict: Verdict; reasons: string[] | null; details: Record<string, unknown> | null }[]
  const buys = rows.filter((r) => r.verdict === 'buy' && r.asset_type === 'stock').map((r) => r.symbol)
  const [featureRows, predictionRows] = buys.length
    ? await Promise.all([
        supabase
          .from('features_live')
          .select('symbol, atr:features->atr_14_pct, adv:features->log_adv20')
          .eq('run_id', run.id)
          .eq('asset_type', 'stock')
          .in('symbol', buys),
        supabase.from('predictions').select('symbol, horizon_days, q90').eq('run_id', run.id).eq('asset_type', 'stock').in('symbol', buys),
      ])
    : [null, null]
  const features = featureRows ? (must(featureRows) as { symbol: string; atr: unknown; adv: unknown }[]) : []
  const predictions = predictionRows ? (must(predictionRows) as { symbol: string; horizon_days: number; q90: unknown }[]) : []
  const byStock = new Map(features.map((f) => [f.symbol, f]))
  // a Buy's range is its pick's, at the horizon in its details
  const q90At = new Map(predictions.map((p) => [`${p.symbol}:${p.horizon_days}`, num(p.q90)]))
  return {
    run,
    held,
    verdicts: new Map(
      rows.map((r) => {
        const f = r.asset_type === 'stock' ? byStock.get(r.symbol) : undefined
        const adv = num(f?.adv)
        return [
          assetKey(r.asset_type, r.symbol),
          {
            verdict: r.verdict,
            reasons: r.reasons ?? [],
            details: r.details ?? {},
            atrPct: num(f?.atr),
            dollarVolume20: adv === null ? null : Math.expm1(adv), // the pipeline stores log1p(ADV)
            q90: r.verdict === 'buy' ? (q90At.get(`${r.symbol}:${num(r.details?.horizon_days)}`) ?? null) : null,
          },
        ]
      }),
    ),
  }
}
