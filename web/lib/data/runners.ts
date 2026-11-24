import 'server-only'
import type { Backtest, BacktestReport, Runner, RunnerWarning } from '../runners'
import type { Supabase } from '../supabase/server'
import { must } from './fetch'
import { loadSettings } from './settings'

/** Settled signals the track record reads, newest first. */
const CLOSED_ROWS = 400

export interface RunnersData {
  /** The latest signal day's signals still waiting for the open. */
  today: Runner[]
  open: Runner[]
  /** The last 400 settled signals (target, stop, held or skipped), newest first. */
  closed: Runner[]
  /** The live rule's version; 0 before a backtest froze one. */
  version: number
  /** The newest weekly backtest; null before the first one. */
  backtest: Backtest | null
  /** The latest stored USD/CAD; null before the first rate. */
  usdCad: number | null
  maxLossCad: number
  /** The latest pre-open run's runners check: its day and its error, if it failed. Null before the first. */
  lastCheck: { day: string; error: string | null } | null
}

const num = (value: unknown): number | null => {
  if (value === null || value === undefined) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

type SignalDb = {
  id: number
  signal_day: string
  symbol: string
  name: string | null
  rule_version: number
  change_pct: unknown
  volume_x: unknown
  dollar_volume: unknown
  close_pos: unknown
  signal_close: unknown
  spread_pct: unknown
  cost_r: unknown
  warnings: RunnerWarning[] | null
  warnings_checked: boolean
  status: Runner['status']
  skip_reason: string | null
  entry_day: string | null
  entry: unknown
  stop: unknown
  target: unknown
  hold_by: string
  last_day: string | null
  last_close: unknown
  exit_day: string | null
  exit_price: unknown
  gross_r: unknown
  net_r: unknown
}

type BacktestDb = {
  ran_at: string
  data_from: string
  data_to: string
  cutoff: string
  variants_tried: number
  rule_version: number | null
  frozen: { older: BacktestReport; newer: BacktestReport } | null
  pick: { name: string; note: string | null; older: BacktestReport; newer: BacktestReport }
}

const toRunner = (r: SignalDb): Runner => ({
  id: r.id,
  signalDay: r.signal_day,
  symbol: r.symbol,
  name: r.name,
  ruleVersion: r.rule_version,
  changePct: Number(r.change_pct),
  volumeX: Number(r.volume_x),
  dollarVolume: Number(r.dollar_volume),
  closePos: Number(r.close_pos),
  signalClose: Number(r.signal_close),
  spreadPct: Number(r.spread_pct),
  costR: Number(r.cost_r),
  warnings: Array.isArray(r.warnings) ? r.warnings : [],
  warningsChecked: r.warnings_checked,
  status: r.status,
  skipReason: r.skip_reason,
  entryDay: r.entry_day,
  entry: num(r.entry),
  stop: Number(r.stop),
  target: Number(r.target),
  holdBy: r.hold_by,
  lastDay: r.last_day,
  lastClose: num(r.last_close),
  exitDay: r.exit_day,
  exitPrice: num(r.exit_price),
  grossR: num(r.gross_r),
  netR: num(r.net_r),
})

const toBacktest = (b: BacktestDb): Backtest => ({
  ranAt: b.ran_at,
  dataFrom: b.data_from,
  dataTo: b.data_to,
  cutoff: b.cutoff,
  variantsTried: b.variants_tried,
  ruleVersion: b.rule_version,
  frozen: b.frozen === null ? null : { older: b.frozen.older, newer: b.frozen.newer },
  pick: { name: b.pick.name, note: b.pick.note ?? null, older: b.pick.older, newer: b.pick.newer },
})

/**
 * The Runners page: the latest signal day's waiting signals, the open runners, the settled record, the
 * live rule's version, the newest backtest, the latest USD/CAD, the max loss per trade and how the
 * latest pre-open run's runners check went.
 */
export async function loadRunners(supabase: Supabase): Promise<RunnersData> {
  const signals = () => supabase.from('runner_signals').select('*')
  const [latestRows, waitingRows, openRows, closedRows, ruleRows, backtestRows, fxRows, settings, checkRows] =
    await Promise.all([
      supabase.from('runner_signals').select('signal_day').order('signal_day', { ascending: false }).limit(1),
      signals().eq('status', 'waiting').order('signal_day', { ascending: false }).order('symbol'),
      signals().eq('status', 'open').order('signal_day', { ascending: false }).order('symbol'),
      signals()
        .in('status', ['target', 'stop', 'held', 'skipped'])
        .order('signal_day', { ascending: false })
        .order('id', { ascending: false })
        .limit(CLOSED_ROWS),
      supabase.from('runner_rules').select('version').eq('live', true).limit(1),
      supabase
        .from('runner_backtests')
        .select('ran_at, data_from, data_to, cutoff, variants_tried, rule_version, frozen, pick')
        .order('ran_at', { ascending: false })
        .order('id', { ascending: false })
        .limit(1),
      supabase.from('fx_rates').select('usd_cad').order('day', { ascending: false }).limit(1),
      loadSettings(supabase),
      supabase
        .from('runs')
        .select('et_date, runners_error:summary->>runners_error')
        .eq('kind', 'pre_open')
        .or('summary->runners.not.is.null,summary->runners_error.not.is.null')
        .order('id', { ascending: false })
        .limit(1),
    ])
  const latest = (must(latestRows) as { signal_day: string }[])[0]?.signal_day ?? null
  const rule = (must(ruleRows) as { version: number }[])[0]
  const backtest = (must(backtestRows) as BacktestDb[])[0]
  const fx = (must(fxRows) as { usd_cad: unknown }[])[0]
  const check = (must(checkRows) as { et_date: string; runners_error: string | null }[])[0]
  return {
    today: (must(waitingRows) as SignalDb[]).filter((r) => r.signal_day === latest).map(toRunner),
    open: (must(openRows) as SignalDb[]).map(toRunner),
    closed: (must(closedRows) as SignalDb[]).map(toRunner),
    version: rule ? rule.version : 0,
    backtest: backtest ? toBacktest(backtest) : null,
    usdCad: fx ? num(fx.usd_cad) : null,
    maxLossCad: settings.runners_max_loss_cad,
    lastCheck: check ? { day: check.et_date, error: check.runners_error ?? null } : null,
  }
}
