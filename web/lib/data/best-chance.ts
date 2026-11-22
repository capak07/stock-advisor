import 'server-only'
import type { Supabase } from '../supabase/server'
import type { BestChance } from '../today'
import { must } from './fetch'

const BENCHMARKS: readonly BestChance['benchmark'][] = ['SPY', 'XIU.TO']

/**
 * Today's Picks card (spec §7.1): per market, the run's highest P(beat) among its stock predictions
 * against that market's benchmark, over all horizons. A market with no prediction is left out.
 * Read-only; the number never appears on a pick card.
 */
export async function loadBestChances(supabase: Supabase, runId: number): Promise<BestChance[]> {
  const answers = await Promise.all(
    BENCHMARKS.map(async (benchmark) => {
      const rows = must(
        await supabase
          .from('predictions')
          .select('p_beat')
          .eq('run_id', runId)
          .eq('asset_type', 'stock')
          .eq('benchmark', benchmark)
          .not('p_beat', 'is', null)
          .order('p_beat', { ascending: false })
          .limit(1),
      ) as { p_beat: number | string }[]
      const pBeat = rows.length === 0 ? NaN : Number(rows[0].p_beat) // numeric can arrive as a string
      return Number.isFinite(pBeat) ? [{ benchmark, pBeat }] : []
    }),
  )
  return answers.flat()
}
