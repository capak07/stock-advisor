import 'server-only'
import type { AssetType } from '../portfolio/types'
import { assetKey } from '../portfolio/types'
import type { Run } from '../runs'
import type { Supabase } from '../supabase/server'
import type { Verdict } from '../verdicts'
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
}

const num = (value: unknown): number | null => {
  const n = typeof value === 'string' ? Number(value) : value
  return typeof n === 'number' && Number.isFinite(n) ? n : null
}

/** The latest published run's verdicts by asset key; null before any published run. */
export async function loadVerdicts(supabase: Supabase): Promise<{ run: Run; verdicts: Map<string, StoredVerdict> } | null> {
  const run = await lastPublishedRun(supabase)
  if (!run) return null
  const rows = must(
    await supabase.from('watchlist_verdicts').select('symbol, asset_type, verdict, reasons, details').eq('run_id', run.id),
  ) as { symbol: string; asset_type: AssetType; verdict: Verdict; reasons: string[] | null; details: Record<string, unknown> | null }[]
  const buys = rows.filter((r) => r.verdict === 'buy' && r.asset_type === 'stock').map((r) => r.symbol)
  const features = buys.length
    ? (must(
        await supabase
          .from('features_live')
          .select('symbol, atr:features->atr_14_pct, adv:features->log_adv20')
          .eq('run_id', run.id)
          .eq('asset_type', 'stock')
          .in('symbol', buys),
      ) as { symbol: string; atr: unknown; adv: unknown }[])
    : []
  const byStock = new Map(features.map((f) => [f.symbol, f]))
  return {
    run,
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
          },
        ]
      }),
    ),
  }
}
