/**
 * Yahoo's prices for the runners between the morning checks (owner request 2026-11-25): the paper trade
 * bought at the open, its plan from that real open, and what it is worth at the latest price or close.
 * The record (status, R, the paper gate) stays the pipeline's: advisor/runners writes it at the 8:15 AM ET
 * check on the day's final prices. This mirrors that code on Yahoo's daily bars: the entry is the first bar
 * after the signal day (track.py), and the plan and the exit follow plan.py (plan_for, gapped, settle).
 * Display only: nothing here places an order.
 */

import { etClock, nyTime, priceOf } from './daytrade'
import { shortDay } from './dates'
import { fmtPct } from './format'
import { chartBase } from './intraday'
import { getJson, type Fetch } from './quotes'
import { paperValue, usdMoney, usdSigned, type PaperValue, type Runner } from './runners'

/** One regular session from Yahoo; `day` is its New York date. */
export interface DayBar {
  day: string
  open: number
  high: number
  low: number
  close: number
}

export interface RunnerQuote {
  /** Oldest first, one per day. */
  bars: DayBar[]
  /** When Yahoo last priced it (ISO). */
  at: string
  /** True once the latest bar's session is over, so its close is the day's close. */
  closed: boolean
}

/** The trade plan's part of a rule (advisor/runners/rule.py Rule). */
export interface PlanRule {
  /** Skip an open more than this above the signal close (0.15 = 15%); null = never. */
  gapSkip: number | null
  /** The stop is at most this far under the entry (0.25 = 25%); null = the signal day's low alone. */
  stopFloor: number | null
  targetR: number
}

/** rule.py's STARTING values: rule version 0, and any key a frozen rule leaves out. */
export const STARTING_PLAN: PlanRule = { gapSkip: null, stopFloor: 0.25, targetR: 2 }

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** A `runner_rules` row's settings as a plan rule; a missing key takes the starting value, as Rule.from_settings does. */
export function planRuleOf(settings: Record<string, unknown> | null | undefined): PlanRule {
  const s = settings ?? {}
  const orNull = (key: string, fallback: number | null) => (key in s ? (finite(s[key]) ? s[key] : null) : fallback)
  return {
    gapSkip: orNull('gap_skip', STARTING_PLAN.gapSkip),
    stopFloor: orNull('stop_floor', STARTING_PLAN.stopFloor),
    targetR: finite(s.target_r) ? s.target_r : STARTING_PLAN.targetR,
  }
}

export interface LivePlan {
  entry: number
  stop: number
  target: number
}

/** plan.py's _floor_cent: rounded to 4 places first, so 1.92 * 0.75 gives 1.44. */
const floorCent = (x: number): number => Math.floor(Number((x * 100).toFixed(4))) / 100

/** plan.py's plan_for: the stop is the closer of the signal day's low and the floor under the entry; null without a stop under the entry. */
export function planFor(entry: number, signalLow: number, rule: PlanRule): LivePlan | null {
  const candidates: number[] = []
  if (signalLow < entry) candidates.push(signalLow)
  if (rule.stopFloor !== null) candidates.push(entry * (1 - rule.stopFloor))
  if (candidates.length === 0) return null
  const stop = floorCent(Math.max(...candidates))
  if (stop <= 0 || stop >= entry) return null
  return { entry, stop, target: Number((entry + rule.targetR * (entry - stop)).toFixed(2)) }
}

/** The pipeline's skip reasons (track.py GAPPED, UNDER_STOP). */
export const GAPPED = 'gapped up at the open'
export const UNDER_STOP = 'opened under the stop'

export type LiveRunner =
  | { kind: 'skipped'; entryDay: string; entry: number; reason: string }
  | { kind: 'open'; entryDay: string; plan: LivePlan; day: string; price: number; closed: boolean; at: string }
  | {
      kind: 'exited'
      entryDay: string
      plan: LivePlan
      status: 'target' | 'stop' | 'held'
      day: string
      price: number
      /** The bar opened past the stop or the target, so it filled at the open. */
      atOpen: boolean
    }

type Settled =
  | { kind: 'open'; day: string; price: number }
  | { kind: 'exited'; status: 'target' | 'stop' | 'held'; day: string; price: number; atOpen: boolean }

/**
 * plan.py's settle, bar by bar: a bar that touches both the stop and the target is a stop. A held trade sells
 * at its hold-by close, so a hold-by session still trading is open.
 */
function settle(bars: readonly DayBar[], plan: LivePlan, holdBy: string, lastClosed: boolean): Settled {
  for (const [i, bar] of bars.entries()) {
    if (bar.open <= plan.stop) return { kind: 'exited', status: 'stop', day: bar.day, price: bar.open, atOpen: true }
    if (bar.open >= plan.target) return { kind: 'exited', status: 'target', day: bar.day, price: bar.open, atOpen: true }
    if (bar.low <= plan.stop) return { kind: 'exited', status: 'stop', day: bar.day, price: plan.stop, atOpen: false }
    if (bar.high >= plan.target) return { kind: 'exited', status: 'target', day: bar.day, price: plan.target, atOpen: false }
    const final = i < bars.length - 1 || lastClosed
    if (bar.day >= holdBy && final) return { kind: 'exited', status: 'held', day: bar.day, price: bar.close, atOpen: false }
  }
  const last = bars[bars.length - 1]
  return { kind: 'open', day: last.day, price: last.close }
}

/**
 * A waiting or open runner on Yahoo's bars newer than its record: a waiting one from its entry (the first bar after
 * the signal day), an open one from the bar after its last stored close. Null when there is no newer bar (before the
 * open, or Yahoo has nothing past the record) or the runner is neither waiting nor open.
 */
export function liveRunner(r: Runner, quote: RunnerQuote, rule: PlanRule): LiveRunner | null {
  if (r.status === 'waiting') {
    const after = quote.bars.filter((b) => b.day > r.signalDay)
    if (after.length === 0) return null
    const entryDay = after[0].day
    const entry = after[0].open
    if (rule.gapSkip !== null && entry / r.signalClose - 1 > rule.gapSkip) return { kind: 'skipped', entryDay, entry, reason: GAPPED }
    const plan = planFor(entry, r.signalLow, rule)
    if (plan === null) return { kind: 'skipped', entryDay, entry, reason: UNDER_STOP }
    return withPlan(entryDay, plan, settle(after, plan, r.holdBy, quote.closed), quote)
  }
  if (r.status === 'open' && r.entry !== null && r.entryDay !== null) {
    const entryDay = r.entryDay
    const lastDay = r.lastDay
    const after = quote.bars.filter((b) => (lastDay === null ? b.day >= entryDay : b.day > lastDay))
    if (after.length === 0) return null
    const plan = { entry: r.entry, stop: r.stop, target: r.target }
    return withPlan(r.entryDay, plan, settle(after, plan, r.holdBy, quote.closed), quote)
  }
  return null
}

const withPlan = (entryDay: string, plan: LivePlan, s: Settled, quote: RunnerQuote): LiveRunner =>
  s.kind === 'open'
    ? { kind: 'open', entryDay, plan, day: s.day, price: s.price, closed: quote.closed, at: quote.at }
    : { kind: 'exited', entryDay, plan, status: s.status, day: s.day, price: s.price, atOpen: s.atOpen }

const usd = (value: number) => priceOf(value, 'US')

/** The paper trade at the live price: what it is worth (or got back), the gain and the R. */
export interface LiveValue {
  /** "Closed US$0.8998 on Nov 25: worth US$89.98", "Hit the stop at US$0.62 on Nov 25: got back US$62.00" */
  text: string
  paper: PaperValue
  r: number
}

/** Null for a skipped signal. */
export function liveValue(live: LiveRunner): LiveValue | null {
  if (live.kind === 'skipped') return null
  const paper = paperValue(live.plan.entry, live.price)
  if (paper === null) return null
  const r = (live.price - live.plan.entry) / (live.plan.entry - live.plan.stop)
  const day = shortDay(live.day)
  let lead: string
  if (live.kind === 'open') {
    lead = live.closed ? `Closed ${usd(live.price)} on ${day}` : `Now ${usd(live.price)} at ${etClock(live.at)} ET`
    return { text: `${lead}: worth ${usdMoney(paper.value)}`, paper, r }
  }
  if (live.status === 'held') lead = `Held to ${day}: sold at the close, ${usd(live.price)}`
  else if (live.atOpen) lead = `Opened ${live.status === 'stop' ? 'under the stop' : 'over the target'} at ${usd(live.price)} on ${day}`
  else lead = `Hit the ${live.status} at ${usd(live.price)} on ${day}`
  return { text: `${lead}: got back ${usdMoney(paper.value)}`, paper, r }
}

/** "+US$6.22 (+7.4%)" */
export const gainText = (paper: PaperValue): string => `${usdSigned(paper.gain)} (${fmtPct(paper.gainPct)})`

/** Where the live prices come from, under the cards that show them. */
export const LIVE_NOTE = 'Prices from Yahoo. The record (R, stop or target, the label) updates at the 8:15 AM ET check.'

/** Yahoo's chart endpoint, daily bars over 3 months: an open runner's bars back to its entry are inside. */
export const runnerChartUrl = (symbol: string): string =>
  `${chartBase()}/${encodeURIComponent(symbol.replaceAll('.', '-'))}?range=3mo&interval=1d`

/** Yahoo's daily bars from a chart response, one per New York day; null without a US$ bar. */
export function parseDaily(body: unknown, now: Date): RunnerQuote | null {
  const result = (body as { chart?: { result?: Record<string, unknown>[] | null } })?.chart?.result?.[0]
  const meta = result?.meta as Record<string, unknown> | undefined
  if (!result || !meta || meta.currency !== 'USD') return null
  const stamps = (result.timestamp as unknown[] | undefined) ?? []
  const q = (result.indicators as { quote?: Record<string, unknown[] | undefined>[] } | undefined)?.quote?.[0] ?? {}
  const byDay = new Map<string, DayBar>()
  stamps.forEach((t, i) => {
    const [open, high, low, close] = (['open', 'high', 'low', 'close'] as const).map((k) => q[k]?.[i])
    if (!finite(t) || ![open, high, low, close].every((v) => finite(v) && v > 0)) return
    const day = nyTime(new Date(t * 1000).toISOString()).day
    // Yahoo can send the current session twice; the later one is the latest
    byDay.set(day, { day, open: open as number, high: high as number, low: low as number, close: close as number })
  })
  const bars = [...byDay.values()].sort((a, b) => (a.day < b.day ? -1 : 1))
  if (bars.length === 0) return null
  const at = finite(meta.regularMarketTime) ? new Date(meta.regularMarketTime * 1000).toISOString() : now.toISOString()
  const today = nyTime(now.toISOString())
  const end = (meta.currentTradingPeriod as { regular?: { end?: unknown } } | undefined)?.regular?.end
  const closed = bars[bars.length - 1].day < today.day || (finite(end) ? now.getTime() >= end * 1000 : today.minutes >= 16 * 60)
  return { bars, at, closed }
}

/** Each symbol's daily bars; one Yahoo doesn't answer is left out. Never throws. */
export async function fetchRunnerQuotes(
  symbols: readonly string[],
  fetchImpl: Fetch = fetch,
  now: Date = new Date(),
): Promise<Map<string, RunnerQuote>> {
  const rows = await Promise.all(
    [...new Set(symbols)].map(async (symbol) => {
      const body = await getJson(fetchImpl, runnerChartUrl(symbol), { headers: { 'User-Agent': 'Mozilla/5.0 (stock-advisor)' } })
      return [symbol, parseDaily(body, now)] as const
    }),
  )
  return new Map(rows.filter((row): row is readonly [string, RunnerQuote] => row[1] !== null))
}

/** Each waiting or open runner's live view by id, from the quotes and its rule version's plan. */
export function liveRunners(
  runners: readonly Runner[],
  quotes: ReadonlyMap<string, RunnerQuote>,
  rules: Readonly<Record<number, PlanRule>>,
): Map<number, LiveRunner> {
  const out = new Map<number, LiveRunner>()
  for (const r of runners) {
    const quote = quotes.get(r.symbol)
    const live = quote ? liveRunner(r, quote, rules[r.ruleVersion] ?? STARTING_PLAN) : null
    if (live) out.set(r.id, live)
  }
  return out
}
