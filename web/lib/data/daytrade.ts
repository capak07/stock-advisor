import 'server-only'
import {
  orderSignals,
  trackRecord,
  type DayRow,
  type Headline,
  type HistoryStats,
  type RecordSummary,
  type ReplayStats,
  type Signal,
  type Skipped,
} from '../daytrade'
import type { Supabase } from '../supabase/server'
import { fetchAll, must } from './fetch'
import { loadSettings } from './settings'

/** Finished days the track record looks back over (each one a trading day). */
const RECORD_DAYS = 60

export interface DaytradeData {
  /** Today's row; null before the morning job starts (or on a day it never ran). */
  day: DayRow | null
  /** Today's signals: the top 3 first. */
  signals: Signal[]
  record: { last20: RecordSummary; last60: RecordSummary }
  maxLossCad: number
  /** The latest stored USD/CAD; null before the first rate. */
  usdCad: number | null
}

const num = (value: unknown): number | null => {
  if (value === null || value === undefined) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

type DayDb = {
  day: string
  status: DayRow['status']
  cycles: number
  last_update: string | null
  scanned: number | null
  usable: number | null
  candidates: number | null
  error: string | null
}

type SignalDb = {
  id: number
  day: string
  symbol: string
  market: Signal['market']
  name: string | null
  trigger_at: string
  entry: unknown
  or_high: unknown
  or_low: unknown
  stop: unknown
  target: unknown
  flat_by: string
  volume_x: unknown
  cost_pct: unknown
  cost_r: unknown
  replay: ReplayStats | Skipped
  history: HistoryStats | Skipped
  net_replay_r: unknown
  net_history_r: unknown
  eligible: boolean
  rank: number | null
  best_rank: number | null
  headlines: Headline[] | null
  status: Signal['status']
  last_price: unknown
  last_at: string | null
  exit_at: string | null
  exit_price: unknown
  gross_r: unknown
  net_r: unknown
}

const toSignal = (r: SignalDb): Signal => ({
  id: r.id,
  day: r.day,
  symbol: r.symbol,
  market: r.market,
  name: r.name,
  triggerAt: r.trigger_at,
  entry: Number(r.entry),
  orHigh: Number(r.or_high),
  orLow: Number(r.or_low),
  stop: Number(r.stop),
  target: Number(r.target),
  flatBy: r.flat_by,
  volumeX: Number(r.volume_x),
  costPct: Number(r.cost_pct),
  costR: Number(r.cost_r),
  replay: r.replay,
  history: r.history,
  netReplayR: num(r.net_replay_r),
  netHistoryR: num(r.net_history_r),
  eligible: r.eligible,
  rank: r.rank,
  bestRank: r.best_rank,
  headlines: Array.isArray(r.headlines) ? r.headlines : [],
  status: r.status,
  lastPrice: num(r.last_price),
  lastAt: r.last_at,
  exitAt: r.exit_at,
  exitPrice: num(r.exit_price),
  grossR: num(r.gross_r),
  netR: num(r.net_r),
})

/**
 * The Day trade page for `day` (New York's date): the day's row and signals, the track record of the
 * last 20 and 60 finished days' top-3 signals (any signal shown in the top 3 that day, even if displaced later), the max loss per trade and the latest USD/CAD.
 */
export async function loadDaytrade(supabase: Supabase, day: string): Promise<DaytradeData> {
  const [dayRows, signalRows, doneRows, settings, fxRows] = await Promise.all([
    supabase
      .from('daytrade_days')
      .select('day, status, cycles, last_update, scanned, usable, candidates, error')
      .eq('day', day)
      .limit(1),
    fetchAll((from, to) =>
      supabase.from('daytrade_signals').select('*').eq('day', day).order('trigger_at').order('id').range(from, to),
    ),
    supabase.from('daytrade_days').select('day').eq('status', 'done').order('day', { ascending: false }).limit(RECORD_DAYS),
    loadSettings(supabase),
    supabase.from('fx_rates').select('usd_cad').order('day', { ascending: false }).limit(1),
  ])
  const d = (must(dayRows) as DayDb[])[0]
  const doneDays = (must(doneRows) as { day: string }[]).map((r) => r.day)
  const recordRows = doneDays.length
    ? ((await fetchAll((from, to) =>
        supabase
          .from('daytrade_signals')
          .select('day, status, net_r')
          .in('day', doneDays)
          .not('best_rank', 'is', null)
          .order('day')
          .order('id')
          .range(from, to),
      )) as { day: string; status: Signal['status']; net_r: unknown }[])
    : []
  const fx = (must(fxRows) as { usd_cad: unknown }[])[0]
  return {
    day: d
      ? {
          day: d.day,
          status: d.status,
          cycles: d.cycles,
          lastUpdate: d.last_update,
          scanned: d.scanned,
          usable: d.usable,
          candidates: d.candidates,
          error: d.error,
        }
      : null,
    signals: orderSignals((signalRows as SignalDb[]).map(toSignal)),
    record: trackRecord(
      recordRows.map((r) => ({ day: r.day, status: r.status, netR: num(r.net_r) })),
      doneDays,
    ),
    maxLossCad: settings.daytrade_max_loss_cad,
    usdCad: fx ? num(fx.usd_cad) : null,
  }
}
