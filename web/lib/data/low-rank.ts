import 'server-only'
import { isMissingScreenRanks } from '../low-rank'
import { isValidSymbol, marketOf } from '../symbols'
import type { Supabase } from '../supabase/server'
import { lastPublishedRun } from './runs'

/**
 * The US stocks among `symbols` flagged Low model rank in the latest published run, each with how
 * many stocks that run ranked. Empty before the first flagged run or before migration 0015.
 */
export async function loadLowRanks(supabase: Supabase, symbols: readonly string[]): Promise<Map<string, number>> {
  const us = [...new Set(symbols)].filter((s) => isValidSymbol(s, 'stock') && marketOf(s) === 'US')
  if (us.length === 0) return new Map()
  const run = await lastPublishedRun(supabase)
  if (!run) return new Map()
  const { data, error } = await supabase
    .from('screen_ranks')
    .select('symbol, scored')
    .eq('run_id', run.id)
    .eq('low', true)
    .in('symbol', us)
  if (error) {
    if (isMissingScreenRanks(error)) return new Map()
    throw new Error(error.message)
  }
  return new Map((data as { symbol: string; scored: number }[]).map((r) => [r.symbol, r.scored]))
}
