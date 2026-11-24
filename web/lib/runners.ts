/**
 * The Runners page's pure parts: the record, the paper gate and the text of a signal.
 * The pipeline (advisor/runners) finds, plans and tracks the signals; this only shows them.
 */
import { daysBetween } from './dates'

export type RunnerStatus = 'waiting' | 'open' | 'skipped' | 'target' | 'stop' | 'held'

/** A warning from the stock's filings; `form` is "split" for a reverse split read from Yahoo's split record. */
export interface RunnerWarning {
  kind: 'share_sale' | 'reverse_split' | 'deficiency'
  form: string
  filed: string
  text: string
}

/** A `runner_signals` row. */
export interface Runner {
  id: number
  signalDay: string
  symbol: string
  name: string | null
  /** 0 = the starting values, before a backtest froze a rule. */
  ruleVersion: number
  changePct: number
  volumeX: number
  dollarVolume: number
  /** Where the signal day closed in its high–low range, 0..1. */
  closePos: number
  signalClose: number
  spreadPct: number
  costR: number
  warnings: RunnerWarning[]
  /** False when the filings or the split record could not be checked. */
  warningsChecked: boolean
  status: RunnerStatus
  skipReason: string | null
  entryDay: string | null
  entry: number | null
  stop: number
  target: number
  /** The preview date while waiting; counted from the entry day once there is an entry. */
  holdBy: string
  lastDay: string | null
  lastClose: number | null
  exitDay: string | null
  exitPrice: number | null
  grossR: number | null
  netR: number | null
}

/** One part of a backtest (the older two thirds or the newest third), as the pipeline stores it. */
export interface BacktestReport {
  signals: number
  skipped_gap: number
  skipped_other: number
  target: number
  stop: number
  held: number
  avg_net_r: number | null
  median_net_r: number | null
  lost_over_1r: number | null
  worst: { symbol: string; signal_day: string; net_r: number }[]
}

/** A `runner_backtests` row: the frozen rule on fresh history, and what the search would pick now. */
export interface Backtest {
  ranAt: string
  dataFrom: string
  dataTo: string
  /** The first day of the newest third, unseen when the rule was chosen. */
  cutoff: string
  variantsTried: number
  ruleVersion: number | null
  frozen: { older: BacktestReport; newer: BacktestReport } | null
  pick: { name: string; note: string | null; older: BacktestReport; newer: BacktestReport }
}

export interface RecordSummary {
  /** Closed runners: target, stop or held to the hold-by day. */
  count: number
  target: number
  stop: number
  held: number
  /** Not trades: left out of the count and the averages. */
  skipped: number
  avgNetR: number | null
  medianNetR: number | null
  sumNetR: number
}

/** What the paper label needs before it goes (the spec's gate). */
export const GATE = { backtestSignals: 100, liveSignals: 40, liveDays: 60 } as const

const CLOSED: ReadonlySet<RunnerStatus> = new Set(['target', 'stop', 'held'])

const median = (values: readonly number[]): number | null => {
  if (values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

/** The record of closed runners after costs; skips are counted apart, waiting and open ones left out. */
export function recordOf(rows: readonly Runner[]): RecordSummary {
  const closed = rows.filter((r) => CLOSED.has(r.status))
  const net = closed.flatMap((r) => (r.netR === null ? [] : [r.netR]))
  const sum = net.reduce((a, b) => a + b, 0)
  return {
    count: closed.length,
    target: closed.filter((r) => r.status === 'target').length,
    stop: closed.filter((r) => r.status === 'stop').length,
    held: closed.filter((r) => r.status === 'held').length,
    skipped: rows.filter((r) => r.status === 'skipped').length,
    avgNetR: net.length === 0 ? null : sum / net.length,
    medianNetR: median(net),
    sumNetR: sum,
  }
}

/**
 * Whether rule `version` has earned dropping the paper label: its backtest made money after costs on at
 * least 100 signals of the unseen third, and its live record has 40 closed signals over 2 months that
 * made money after costs. Otherwise each failed part, in plain words.
 */
export function gate(
  version: number,
  backtest: Backtest | null,
  rows: readonly Runner[],
  today: string,
): { passed: boolean; reasons: string[] } {
  if (version === 0) return { passed: false, reasons: ['No rule has been chosen by a backtest yet.'] }
  const reasons: string[] = []
  const newer = backtest !== null && backtest.ruleVersion === version ? (backtest.frozen?.newer ?? null) : null
  if (newer === null) {
    reasons.push('No backtest of this rule yet.')
  } else {
    if (newer.signals < GATE.backtestSignals) {
      reasons.push(`${newer.signals} of ${GATE.backtestSignals} backtest signals in the unseen third.`)
    }
    // no average means no trades, which the count above already says
    if (newer.avg_net_r !== null && newer.avg_net_r <= 0) {
      reasons.push('The backtest lost money on the unseen third after costs.')
    }
  }
  const live = rows.filter((r) => r.ruleVersion === version && CLOSED.has(r.status))
  const record = recordOf(live)
  if (record.count < GATE.liveSignals) reasons.push(`${record.count} of ${GATE.liveSignals} closed live signals so far.`)
  const first = live.reduce<string | null>((min, r) => (min === null || r.signalDay < min ? r.signalDay : min), null)
  if (first === null || daysBetween(first, today) < GATE.liveDays) reasons.push('The live record is under 2 months old.')
  if (record.avgNetR !== null && record.avgNetR <= 0) reasons.push('The live record is losing after costs.')
  return { passed: reasons.length === 0, reasons }
}

/** An open runner's R at its last close; null before it has an entry and a close. */
export function rSoFar(r: Runner): number | null {
  if (r.entry === null || r.lastClose === null || !(r.entry > r.stop)) return null
  return (r.lastClose - r.entry) / (r.entry - r.stop)
}

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] as const

/** "89M", "4.2M", "600K" */
const shareCount = (n: number): string => {
  if (n < 999_500) return `${Math.round(n / 1000)}K`
  const m = n / 1_000_000
  return m < 9.95 ? `${Number(m.toFixed(1))}M` : `${Math.round(m)}M`
}

/** "Ignition Fri: +102% on 89M shares (892× normal), closed at 65% of the day's range" */
export const ignitionLine = (r: Runner): string => {
  const weekday = WEEKDAYS[new Date(`${r.signalDay}T12:00:00Z`).getUTCDay()]
  const change = Math.round(r.changePct)
  return (
    `Ignition ${weekday}: ${change > 0 ? '+' : ''}${change}% on ${shareCount(r.dollarVolume / r.signalClose)} shares ` +
    `(${Math.round(r.volumeX)}× normal), closed at ${Math.round(r.closePos * 100)}% of the day's range`
  )
}

export const PAPER = 'Paper: testing'

export const TESTED = 'Tested: positive after costs so far'

export const BIAS_NOTE = 'Optimistic: stocks that were delisted or went bust are missing from the data.'

/** The standing notes (the design's "Standing notes"). */
export const NOTES: readonly string[] = [
  'Not financial advice. Nothing is ordered.',
  'Cheap stocks gap, halt and get diluted. A stop can fill far below its price.',
  'Frequent short trades in a TFSA can be treated as business income, so the non-registered account is the natural home (not tax advice).',
]
