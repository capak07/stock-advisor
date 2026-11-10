/**
 * The day trade tab's pure parts: share sizing, freshness, the status line and the text of a signal.
 * The pipeline (advisor/daytrade) finds, replays, ranks and tracks the signals; this only shows them.
 * Times are New York's (the same clock as Toronto's).
 */
import { fmtMoney, fmtPrice } from './format'

export type DayStatus = 'waiting' | 'scanning' | 'done' | 'failed' | 'closed'
export type SignalStatus = 'open' | 'target' | 'stop' | 'flat'
export type DaytradeMarket = 'US' | 'TSX'

/** A `daytrade_days` row. */
export interface DayRow {
  day: string
  status: DayStatus
  cycles: number
  lastUpdate: string | null
  scanned: number | null
  usable: number | null
  candidates: number | null
  error: string | null
}

/** A step the pipeline could not run for this signal (too little history, a failed chart). */
export interface Skipped {
  skipped: string
}

/** The 10,000 replays of the rest of the day (fractions of the replays). */
export interface ReplayStats {
  replays: number
  target_first: number
  stop_first: number
  neither: number
  green: number
  avg_r: number
  sessions: number
}

/** The same rule on each of the stock's past full sessions. */
export interface HistoryStats {
  sessions: number
  fired: number
  target: number
  stop: number
  neither: number
  avg_r: number
}

export interface Headline {
  title: string
  url: string
  published_at: string
  outlet: string
}

/** A `daytrade_signals` row. */
export interface Signal {
  id: number
  day: string
  symbol: string
  market: DaytradeMarket
  name: string | null
  triggerAt: string
  entry: number
  orHigh: number
  orLow: number
  stop: number
  target: number
  volumeX: number
  costPct: number
  costR: number
  replay: ReplayStats | Skipped
  history: HistoryStats | Skipped
  netReplayR: number | null
  netHistoryR: number | null
  eligible: boolean
  rank: number | null
  headlines: Headline[]
  status: SignalStatus
  lastPrice: number | null
  lastAt: string | null
  exitAt: string | null
  exitPrice: number | null
  grossR: number | null
  netR: number | null
}

export const BEFORE_RANGE = 'Before 9:50 AM: the opening range is still forming.'
export const MARKET_CLOSED = 'Market closed today.'
export const LATE_LINE = 'Late: the price has moved since the signal; entering now is a different trade.'
export const TRACK_LABEL = "Paper: what the rule's top-3 trades would have done, after costs."
export const NO_RECORD = 'No finished day-trade signals yet.'
export const NOTES = [
  'Not financial advice. Nothing is ordered: you place trades yourself.',
  'Frequent day trading in a TFSA can be treated as a business, which makes the gains taxable (not tax advice).',
  "Yahoo's free 5-minute bars can lag a few minutes.",
] as const
export const noTradeLine = (n: number) => `No signal today has a positive record after costs (${n} signals checked).`

/** The pipeline's eligibility floor (advisor/daytrade/score.py MIN_FIRED). */
export const MIN_FIRED = 20
const FRESH_MS = 10 * 60_000
const BAR_MIN = 5
const FIRST_CYCLE = 9 * 60 + 50
const SESSION_END = 16 * 60

/**
 * The 1:00 PM closes in the pipeline's market calendars (pandas_market_calendars, 2026-2027): flat by
 * 12:55 PM on these days. Other days, and later years until this list grows, are 3:55 PM.
 */
const EARLY_CLOSES: Record<string, readonly DaytradeMarket[]> = {
  '2026-11-27': ['US'],
  '2026-12-24': ['US', 'TSX'],
  '2027-11-26': ['US'],
  '2027-12-24': ['TSX'],
}

const nyParts = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  weekday: 'short',
  hour: 'numeric',
  minute: 'numeric',
  hourCycle: 'h23',
})

/** A moment on New York's clock: its date, weekday and minutes after midnight. */
export function nyTime(iso: string): { day: string; weekday: string; minutes: number } {
  const parts = nyParts.formatToParts(new Date(iso))
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? ''
  return {
    day: `${get('year')}-${get('month')}-${get('day')}`,
    weekday: get('weekday'),
    minutes: (Number(get('hour')) % 24) * 60 + Number(get('minute')),
  }
}

/** Minutes after midnight as "10:35 AM" (a plain space: ICU's narrow one varies by Node version). */
const clockOf = (minutes: number): string => {
  const h = Math.floor(minutes / 60) % 24
  const m = minutes % 60
  return `${h % 12 === 0 ? 12 : h % 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`
}

/** "10:35 AM" on New York's clock. */
export const etClock = (iso: string): string => clockOf(nyTime(iso).minutes)

const isWeekend = (weekday: string) => weekday === 'Sat' || weekday === 'Sun'

const closesEarly = (day: string, market: DaytradeMarket) => EARLY_CLOSES[day]?.includes(market) ?? false

/** When a signal must be closed: 3:55 PM, or 12:55 PM on a 1:00 PM close. */
export const flatBy = (day: string, market: DaytradeMarket): string => (closesEarly(day, market) ? '12:55 PM' : '3:55 PM')

/** The last bar a day's cycles run for: the later flat-by of the two markets. */
const lastBarMinutes = (day: string) => (closesEarly(day, 'US') && closesEarly(day, 'TSX') ? 12 * 60 + 55 : 15 * 60 + 55)

/**
 * Shares sized so the loss at the stop fits the max loss per trade: floor(max loss in the stock's
 * currency / risk a share), a US max loss converted at USD/CAD. Null when even one share risks more,
 * or a US stock has no rate.
 */
export function shares(
  maxLossCad: number,
  risk: number,
  market: DaytradeMarket,
  usdCad: number | null,
): { shares: number; riskCad: number } | null {
  if (!(risk > 0) || !(maxLossCad > 0)) return null
  const rate = market === 'US' ? usdCad : 1
  if (rate === null || !(rate > 0)) return null
  // the epsilon keeps 0.7 / 0.1 (6.999…) at 7
  const n = Math.floor(maxLossCad / rate / risk + 1e-9)
  if (n < 1) return null
  return { shares: n, riskCad: n * risk * rate }
}

const moneyLimit = (cad: number) => fmtMoney(cad, { digits: Number.isInteger(cad) ? 0 : 2 })

/** "≈ 22 shares (risking ≈ C$49 at the stop)", or why there are none. */
export function sharesLine(maxLossCad: number, risk: number, market: DaytradeMarket, usdCad: number | null): string {
  if (market === 'US' && (usdCad === null || !(usdCad > 0))) return 'No USD/CAD rate yet.'
  const s = shares(maxLossCad, risk, market, usdCad)
  if (s === null) return `Even one share risks more than your ${moneyLimit(maxLossCad)} limit.`
  return `≈ ${s.shares.toLocaleString('en-CA')} ${s.shares === 1 ? 'share' : 'shares'} (risking ≈ ${fmtMoney(s.riskCad)} at the stop)`
}

/** Fresh for 10 minutes after the trigger bar closes. */
export const isFresh = (triggerAt: string, now: string): boolean => Date.parse(now) - Date.parse(triggerAt) <= FRESH_MS

/** The line at the top of the page for today's row (or none) at `now`. */
export function statusLine(day: DayRow | null, now: string): string {
  const t = nyTime(now)
  if (day?.status === 'closed') return MARKET_CLOSED
  if (day === null || day.status === 'waiting') {
    if (isWeekend(t.weekday)) return MARKET_CLOSED
    if (t.minutes < FIRST_CYCLE) return BEFORE_RANGE
    return day === null ? 'No scan has run yet today.' : 'Waiting for the first scan.'
  }
  const last = day.lastUpdate === null ? null : `last update ${etClock(day.lastUpdate)} ET`
  if (day.status === 'failed') return `Today's scan failed: ${day.error ?? 'no reason given'} · ${last ?? 'no update yet today'}`
  if (day.status === 'done') return last === null ? 'Done for today' : `Done for today · ${last}`
  // scanning: the next cycle runs after the next 5-minute bar closes, up to the last bar
  if (last === null) return 'Scanning'
  const at = nyTime(day.lastUpdate!).minutes
  const next = at - (at % BAR_MIN) + BAR_MIN
  return next <= lastBarMinutes(day.day) ? `Scanning · ${last} · next ~${clockOf(next).replace(/ [AP]M$/, '')}` : `Scanning · ${last}`
}

/** Refresh the page while the day is waiting or scanning, or after a failed cycle during the session. */
export function isLive(day: DayRow | null, now: string): boolean {
  if (day === null) return false
  if (day.status === 'waiting' || day.status === 'scanning') return true
  return day.status === 'failed' && nyTime(now).minutes < SESSION_END
}

const MINUS = '−'

/** "+0.53R", "−0.12R", "0.00R" */
export const fmtR = (r: number): string => {
  const text = Math.abs(r).toFixed(2)
  const sign = Number(text) === 0 ? '' : r > 0 ? '+' : MINUS
  return `${sign}${text}R`
}

/** A fraction as a whole percent: "34%". */
export const fmtShare = (fraction: number): string => `${Math.round(fraction * 100)}%`

/** A price in the stock's own currency: "US$67.65", "C$150.00". */
export const priceOf = (value: number, market: DaytradeMarket): string => fmtPrice(value, market === 'US' ? 'USD' : 'CAD')

export const isSkipped = (stats: object): stats is Skipped => 'skipped' in stats

/** "This rule on TGTX's last 55 sessions: fired 37 times, 5 target, 20 stop; average −0.12R before costs" */
export function historyLine(symbol: string, h: HistoryStats | Skipped): string {
  if (isSkipped(h)) return `No history: ${h.skipped}`
  return `This rule on ${symbol}'s last ${h.sessions} sessions: fired ${h.fired} times, ${h.target} target, ${h.stop} stop; average ${fmtR(h.avg_r)} before costs`
}

/** "Cost 3.10% round trip = 0.53R" */
export const costLine = (costPct: number, costR: number): string => `Cost ${costPct.toFixed(2)}% round trip = ${costR.toFixed(2)}R`

/** "10,000 replays: target first 34% · stop first 52% · neither 14% · green at close 48%" */
export function oddsLine(r: ReplayStats | Skipped): string {
  if (isSkipped(r)) return `No replay: ${r.skipped}`
  return `${r.replays.toLocaleString('en-CA')} replays: target first ${fmtShare(r.target_first)} · stop first ${fmtShare(r.stop_first)} · neither ${fmtShare(r.neither)} · green at close ${fmtShare(r.green)}`
}

const afterCosts = (netR: number | null) => (netR === null ? '' : ` · ${fmtR(netR)} after costs`)
const exitText = (s: Signal) =>
  `${s.exitAt === null ? '' : ` ${etClock(s.exitAt)}`}${s.exitPrice === null ? '' : ` (${priceOf(s.exitPrice, s.market)})`}`

/** Where the tracked signal stands: open with its last price, or how it ended and its R after costs. */
export function outcomeLine(s: Signal): string {
  switch (s.status) {
    case 'open':
      return s.lastPrice === null || s.lastAt === null
        ? 'Open: no price since the signal yet'
        : `Open · last ${priceOf(s.lastPrice, s.market)} at ${etClock(s.lastAt)}`
    case 'target':
      return `Target hit${s.exitAt === null ? '' : ' at'}${exitText(s)}${afterCosts(s.netR)}`
    case 'stop':
      return `Stopped out${s.exitAt === null ? '' : ' at'}${exitText(s)}${afterCosts(s.netR)}`
    case 'flat':
      return `Flat at close${exitText(s)}${afterCosts(s.netR)}`
  }
}

/** The top 3 by rank, then the eligible ones, then by net history R (missing last), then the earliest. */
export function orderSignals(list: readonly Signal[]): Signal[] {
  const key = (s: Signal) => [s.rank ?? 99, s.eligible ? 0 : 1, -(s.netHistoryR ?? -Infinity)]
  return [...list].sort((a, b) => {
    const ka = key(a)
    const kb = key(b)
    for (let i = 0; i < ka.length; i++) if (ka[i] !== kb[i]) return ka[i] - kb[i]
    return a.triggerAt.localeCompare(b.triggerAt) || a.symbol.localeCompare(b.symbol)
  })
}

/** Why a signal is (or is not) one of the top 3, in the pipeline's order of checks. */
export function whyNotTop3(s: Signal): string {
  if (s.rank !== null) return `Top 3 (#${s.rank})`
  if (s.eligible) return 'Ranked below the top 3'
  if (isSkipped(s.history)) return `Not enough history: ${s.history.skipped}`
  if (isSkipped(s.replay)) return `No replay: ${s.replay.skipped}`
  if (s.history.fired < MIN_FIRED || s.netHistoryR === null) return `Fired only ${s.history.fired} times in its history (needs ${MIN_FIRED})`
  if (s.netHistoryR <= 0) return `History is ${fmtR(s.netHistoryR)} after costs`
  if (s.netReplayR !== null && s.netReplayR <= 0) return `Replays are ${fmtR(s.netReplayR)} after costs`
  return 'Not eligible'
}

export interface RecordSummary {
  /** Finished trading days counted (at most 20 or 60). */
  days: number
  count: number
  target: number
  stop: number
  flat: number
  avgNetR: number | null
  sumNetR: number
}

export interface RecordRow {
  day: string
  status: SignalStatus
  netR: number | null
}

function summarize(rows: readonly RecordRow[], days: readonly string[]): RecordSummary {
  const within = new Set(days)
  const mine = rows.filter((r) => within.has(r.day))
  const nets = mine.map((r) => r.netR).filter((r): r is number => r !== null)
  const sum = nets.reduce((a, b) => a + b, 0)
  return {
    days: days.length,
    count: mine.length,
    target: mine.filter((r) => r.status === 'target').length,
    stop: mine.filter((r) => r.status === 'stop').length,
    flat: mine.filter((r) => r.status === 'flat').length,
    avgNetR: nets.length ? sum / nets.length : null,
    sumNetR: sum,
  }
}

/** The top-3 signals' outcomes over the last 20 and 60 finished days (`doneDays` newest first). */
export function trackRecord(rows: readonly RecordRow[], doneDays: readonly string[]): { last20: RecordSummary; last60: RecordSummary } {
  return { last20: summarize(rows, doneDays.slice(0, 20)), last60: summarize(rows, doneDays.slice(0, 60)) }
}
