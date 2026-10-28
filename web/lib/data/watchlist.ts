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
}

/** The latest published run's verdicts by asset key; null before any published run. */
export async function loadVerdicts(supabase: Supabase): Promise<{ run: Run; verdicts: Map<string, StoredVerdict> } | null> {
  const run = await lastPublishedRun(supabase)
  if (!run) return null
  const rows = must(
    await supabase.from('watchlist_verdicts').select('symbol, asset_type, verdict, reasons, details').eq('run_id', run.id),
  ) as { symbol: string; asset_type: AssetType; verdict: Verdict; reasons: string[] | null; details: Record<string, unknown> | null }[]
  return {
    run,
    verdicts: new Map(
      rows.map((r) => [assetKey(r.asset_type, r.symbol), { verdict: r.verdict, reasons: r.reasons ?? [], details: r.details ?? {} }]),
    ),
  }
}
