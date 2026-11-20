/**
 * A holding's exit plan as the pipeline stores it (`holding_actions.exit_plan`, pipeline
 * portfolio/exit_plan.py), and the text lines the pages build from it. Chances count daily
 * closes, so the wording is "closes at or above" / "reached in N% of cases", never "will reach".
 * Prices are in the asset's own currency. Any number can be null: a "fail" plan has none, a
 * "range_only" plan has no sell-at numbers; an "unvalidated" plan keeps its numbers.
 */

import { shortDay } from '../dates'
import { fmtPct, fmtPrice } from '../format'
import type { ActionKind } from './actions'
import type { AssetType } from './types'

export type Currency = 'CAD' | 'USD'
export type PlanStatus = 'pass' | 'range_only' | 'fail' | 'unvalidated'
export type PlanBasis = 'forecast' | 'volatility'

export interface ExitPlan {
  /** The holding's asset type: it says what a day of the horizon is. */
  assetType: AssetType
  status: PlanStatus
  basis: PlanBasis
  /** Days (trading sessions for a stock, calendar days for a coin) the chances are simulated over. */
  horizon: number
  /** ISO date of the plan's horizon, or null. */
  recheckBy: string | null
  low: number | null
  mid: number | null
  high: number | null
  sellAt: number | null
  /** Chances as fractions (0.33 is 33%). */
  pTouch: number | null
  pStopFirst: number | null
  pUp: number | null
  breakeven: number | null
  pBreakeven: number | null
  /** The benchmark's drift over the horizon, as a fraction; null without a forecast. */
  drift: number | null
  /** The owner's cost per unit, in the asset's own currency. */
  costPrice: number | null
}

const STATUSES: readonly PlanStatus[] = ['pass', 'range_only', 'fail', 'unvalidated']
const BASES: readonly PlanBasis[] = ['forecast', 'volatility']

const num = (value: unknown): number | null => {
  const n = typeof value === 'string' && value.trim() !== '' ? Number(value) : value
  return typeof n === 'number' && Number.isFinite(n) ? n : null
}

/** The stored plan (snake_case jsonb) of a holding of `assetType`, or null when there is none or it cannot be read. */
export function parseExitPlan(raw: unknown, assetType: AssetType): ExitPlan | null {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return null
  const r = raw as Record<string, unknown>
  const status = STATUSES.find((s) => s === r.status)
  const basis = BASES.find((b) => b === r.basis)
  const horizon = num(r.horizon)
  if (!status || !basis || horizon === null || horizon <= 0) return null
  return {
    assetType,
    status,
    basis,
    horizon,
    recheckBy: typeof r.recheck_by === 'string' && r.recheck_by !== '' ? r.recheck_by : null,
    low: num(r.low),
    mid: num(r.mid),
    high: num(r.high),
    sellAt: num(r.sell_at),
    pTouch: num(r.p_touch),
    pStopFirst: num(r.p_stop_first),
    pUp: num(r.p_up),
    breakeven: num(r.breakeven),
    pBreakeven: num(r.p_breakeven),
    drift: num(r.drift),
    costPrice: num(r.cost_price),
  }
}

/** CAD for a TSX stock (symbol ends `.TO`), else USD; coins are USD. */
export const assetCurrency = (assetType: AssetType, symbol: string): Currency =>
  assetType === 'stock' && symbol.endsWith('.TO') ? 'CAD' : 'USD'

const prefixOf = (currency: Currency): string => (currency === 'USD' ? 'US$' : 'C$')
/** A price without its currency prefix, for the middle and high of a range. */
export const barePrice = (value: number, currency: Currency): string =>
  fmtPrice(value, currency).slice(prefixOf(currency).length)
const pct = (fraction: number): string => `${Math.round(fraction * 100)}%`
const pctOf = (value: number, base: number): string => fmtPct((value / base - 1) * 100, 0)
/** The plan's horizon in words: "21 trading days" for a stock (sessions), "21 days" for a coin. */
export const horizonText = (plan: Pick<ExitPlan, 'assetType' | 'horizon'>): string =>
  `${plan.horizon} ${plan.assetType === 'crypto' ? 'days' : 'trading days'}`

/** "by Dec 19", or "in 21 trading days" without a date. */
const when = (plan: ExitPlan): string =>
  plan.recheckBy !== null ? `by ${shortDay(plan.recheckBy)}` : `in ${horizonText(plan)}`

/**
 * The sell-at price the pages may show or use for a holding with this action (R20a): only for a Hold
 * or an Add, and only when the plan's status is pass or unvalidated; null for a Sell or a Trim (they
 * sell now), for a range-only or failed plan, and without a plan. Every sell-at line, stop-first
 * line, alert link and limit sell goes through it.
 */
export function shownSellAt(plan: ExitPlan | null, action: ActionKind | null): number | null {
  if (plan === null || plan.sellAt === null) return null
  if (plan.status !== 'pass' && plan.status !== 'unvalidated') return null
  return action === 'hold' || action === 'add' ? plan.sellAt : null
}

/** "Range by Dec 19: US$4.20 – 5.05 – 6.10 (+4%)"; the percent is the middle against `price`. */
export function rangeLine(plan: ExitPlan, currency: Currency, price: number | null): string | null {
  if (plan.low === null || plan.mid === null || plan.high === null) return null
  const move = price !== null && price > 0 ? ` (${pctOf(plan.mid, price)})` : ''
  return `Range ${when(plan)}: ${fmtPrice(plan.low, currency)} – ${barePrice(plan.mid, currency)} – ${barePrice(plan.high, currency)}${move}`
}

/** "Sell at US$5.60 · about 1 in 3 · +18% on cost": the chance a daily close is at or above it. */
export function sellAtLine(plan: ExitPlan, currency: Currency): string | null {
  if (plan.sellAt === null) return null
  const parts = [`Sell at ${fmtPrice(plan.sellAt, currency)}`]
  if (plan.pTouch !== null) {
    parts.push(plan.pTouch >= 0.3 && plan.pTouch <= 0.37 ? 'about 1 in 3' : `reached in ${pct(plan.pTouch)} of cases`)
  }
  if (plan.costPrice !== null && plan.costPrice > 0) parts.push(`${pctOf(plan.sellAt, plan.costPrice)} on cost`)
  return parts.join(' · ')
}

/** "Stop first: 22%" */
export const stopFirstLine = (plan: ExitPlan): string | null =>
  plan.pStopFirst === null ? null : `Stop first: ${pct(plan.pStopFirst)}`

const UNLIKELY = 0.25

/** The break-even price and its chance; `warn` when getting back to cost is unlikely. */
export function breakevenLine(plan: ExitPlan, currency: Currency): { text: string; warn: boolean } | null {
  if (plan.breakeven === null) return null
  if (plan.pBreakeven === null) return { text: `Break-even ${fmtPrice(plan.breakeven, currency)}`, warn: false }
  if (plan.pBreakeven < UNLIKELY) {
    return {
      text: `Unlikely to get back to your cost ${when(plan)}: reached in ${pct(plan.pBreakeven)} of cases. Your cost doesn't change where it goes next.`,
      warn: true,
    }
  }
  return {
    text: `Break-even ${fmtPrice(plan.breakeven, currency)} · reached in ${pct(plan.pBreakeven)} of cases`,
    warn: false,
  }
}

/** Where the plan comes from; `benchmark` is the symbol whose drift a forecast plan assumes. */
export function basisLine(plan: ExitPlan, benchmark: string): string {
  if (plan.basis === 'volatility') return 'From volatility only — no view on direction'
  const base = "From the model's forecast"
  return plan.drift === null
    ? base
    : `${base} · assumes ${benchmark} drifts ${fmtPct(plan.drift * 100, 1)} over ${horizonText(plan)}`
}

/** What the plan's status hides or qualifies; null for a plan that passed. */
export function statusNote(plan: ExitPlan): string | null {
  switch (plan.status) {
    case 'unvalidated':
      return 'Not validated yet: the first benchmark run after this change checks these chances.'
    case 'range_only':
      return 'The sell-at price is hidden: it missed the benchmark check.'
    case 'fail':
      return 'The exit plan is hidden: its range missed the benchmark check.'
    default:
      return null
  }
}
