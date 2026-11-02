/**
 * Which order plan (lib/orders.ts) each page's trade gets: a pick, a watched Buy, a holding's action
 * and its stop, an Invest line (docs/superpowers/specs/2026-10-28-order-guidance-design.md).
 */

import type { PickView } from './data/picks'
import type { StoredVerdict } from './data/watchlist'
import { fmtMoney } from './format'
import type { StockLine } from './invest/allocate'
import {
  DEFAULT_STOP_RULES,
  pickStop,
  planBracket,
  planBuy,
  planRecurring,
  planSell,
  planStop,
  planTrim,
  type Instrument,
  type OrderPlan,
  type StopRules,
} from './orders'
import type { HoldingAction, RiskLevel } from './portfolio/actions'
import type { Close, Market } from './portfolio/types'
import { tradeCurrency } from './symbols'

/** A buy sized for a portfolio with no value yet. */
export const DEFAULT_BUY_CAD = 1000

/** Spec §6.4: each risk level's suggested max position, in percent of the portfolio; for actions stored without one. */
const MAX_POSITION_PCT: Record<RiskLevel, number> = { low: 5, medium: 3, high: 1.5, very_high: 0.5 }

/** The clock and the latest USD/CAD rate; without a rate, nothing priced in USD gets guidance. */
export interface OrderContext {
  now: Date
  usdCad: number | null
}

/** A plan, and the amount it was sized for when the page doesn't already show it. */
export interface Guide {
  plan: OrderPlan
  caption: string | null
}

/** Several plans under one "How to place it": their steps in order, each note once. */
export const joinPlans = (...plans: (OrderPlan | null)[]): OrderPlan => {
  const shown = plans.filter((p): p is OrderPlan => p !== null)
  return { steps: shown.flatMap((p) => p.steps), notes: [...new Set(shown.flatMap((p) => p.notes))] }
}

/** The max size in CAD, or C$1,000 (and saying so) for an empty portfolio. */
function buyAmount(maxPositionPct: number, portfolioCad: number | null): { amountCad: number; caption: string | null } {
  return portfolioCad !== null && portfolioCad > 0
    ? { amountCad: (maxPositionPct * portfolioCad) / 100, caption: null }
    : { amountCad: DEFAULT_BUY_CAD, caption: `for ${fmtMoney(DEFAULT_BUY_CAD)}` }
}

interface StockBuy {
  symbol: string
  price: number
  stop: number
  maxPositionPct: number
  atrPct: number | null
  dollarVolume20: number | null
  /** The top of the forecast range at the hold, for a bracket's take-profit; null when unknown. */
  q90: number | null
  /** The hold's exit-by; without it no bracket is offered. */
  exitBy: string | null
}

/** A stock buy for its max size with its stop, then the same buy as one bracket order. */
function stockBuy(stock: StockBuy, portfolioCad: number | null, { now, usdCad }: OrderContext): Guide | null {
  const currency = tradeCurrency('stock', stock.symbol)
  if (currency === 'USD' && usdCad === null) return null
  const i: Instrument = { assetType: 'stock', currency, price: stock.price, atrPct: stock.atrPct, dollarVolume20: stock.dollarVolume20 }
  const { amountCad, caption } = buyAmount(stock.maxPositionPct, portfolioCad)
  const sized = { amountCad, usdCad: usdCad ?? 1, now, stop: stock.stop }
  const bracket = stock.exitBy === null ? null : planBracket(i, { ...sized, q90: stock.q90, exitBy: stock.exitBy })
  return { plan: joinPlans(planBuy(i, sized), bracket), caption }
}

/** A pick bought at its entry price for its max size, with its stop. */
export const pickGuide = (p: PickView, portfolioCad: number | null, ctx: OrderContext): Guide | null =>
  stockBuy(
    {
      symbol: p.symbol,
      price: p.entry,
      stop: p.stop,
      maxPositionPct: p.maxPositionPct,
      atrPct: p.atrPct,
      dollarVolume20: p.dollarVolume20,
      q90: p.q90,
      exitBy: p.exitBy,
    },
    portfolioCad,
    ctx,
  )

const finite = (value: unknown): number | null => {
  const n = typeof value === 'string' ? Number(value) : value
  return typeof n === 'number' && Number.isFinite(n) ? n : null
}

/** A watched stock's Buy, like a pick, from the pick fields in its details. Holds, Avoids and coins get none. */
export function verdictGuide(symbol: string, v: StoredVerdict, portfolioCad: number | null, ctx: OrderContext): Guide | null {
  if (v.verdict !== 'buy') return null
  const price = finite(v.details.entry_ref_price)
  const stop = finite(v.details.stop)
  const maxPositionPct = finite(v.details.max_position_pct)
  if (price === null || stop === null || maxPositionPct === null) return null
  const exitBy = typeof v.details.exit_by === 'string' ? v.details.exit_by : null
  return stockBuy({ symbol, price, stop, maxPositionPct, atrPct: v.atrPct, dollarVolume20: v.dollarVolume20, q90: v.q90, exitBy }, portfolioCad, ctx)
}

const ADD_BRACKET_NOTE = 'A bracket covers only the shares this buy adds; the shares you hold keep their own stop-limit.'

/**
 * A holding's order for its action (Sell, Trim, Add; a Hold has none) and the stop to keep on it.
 * An Add also gets the buy as one bracket order on the new shares, its take-profit at the top of
 * the holding's range and its stop loss the trailing stop.
 * Prices are converted to the currency the asset trades in: a coin's Coinbase USD prices to CAD.
 */
export function holdingGuides(
  a: HoldingAction,
  { qty, valueCad, portfolioCad, latest = null }: { qty: number; valueCad: number; portfolioCad: number; latest?: Close | null },
  { now, usdCad }: OrderContext,
): { order: OrderPlan | null; stop: OrderPlan | null } {
  const currency = tradeCurrency(a.assetType, a.symbol)
  const needsRate = currency === 'USD' || a.assetType === 'crypto'
  if (needsRate && usdCad === null) return { order: null, stop: null }
  const toTrading = (v: number | null) => (v === null ? null : a.assetType === 'crypto' ? v * usdCad! : v)
  // the latest close (a Refresh's live price when there is one) beats the run's decision price
  const latestPrice =
    latest === null ? null : latest.currency === currency ? latest.close : currency === 'CAD' ? latest.close * usdCad! : latest.close / usdCad!
  const price = latestPrice ?? toTrading(a.refPrice)
  const trailingStop = toTrading(a.trailingStop)
  const instrument = (p: number): Instrument => ({ assetType: a.assetType, currency, price: p, atrPct: a.atrPct, dollarVolume20: a.dollarVolume20 })

  let order: OrderPlan | null = null
  if (price !== null && a.action === 'sell') order = planSell(instrument(price), { qty, now })
  if (price !== null && a.action === 'trim') order = planTrim(instrument(price), { qty, now })
  const maxPct = a.maxPositionPct ?? (a.riskLevel === null ? null : MAX_POSITION_PCT[a.riskLevel])
  if (price !== null && a.action === 'add' && maxPct !== null) {
    const amountCad = (maxPct * portfolioCad) / 100 - valueCad
    if (amountCad > 0) {
      const sized = { amountCad, usdCad: usdCad ?? 1, now, stop: trailingStop }
      // Wealthsimple brackets only a new buy: the added shares, beside the held ones' stop-limit
      const bracket =
        trailingStop === null || a.exitBy === null
          ? null
          : planBracket(instrument(price), { ...sized, stop: trailingStop, q90: a.q90, exitBy: a.exitBy })
      const held = bracket && bracket.steps.length > 0 ? { steps: [], notes: [ADD_BRACKET_NOTE] } : null
      order = joinPlans(planBuy(instrument(price), sized), bracket, held)
    }
  }
  // planStop reads only the stop and the daily range, so a holding without a decision price still gets one
  const stop =
    trailingStop === null ? null : planStop(instrument(price ?? trailingStop), { qty, stop: trailingStop, previousStop: toTrading(a.previousStop) })
  return { order, stop }
}

/**
 * An Invest line bought for its amount with no stop order (the page isn't a pick), then, for a stock
 * with a daily range, the same buy as one bracket order: the picks' stop rule for its hold (the
 * market's tuned one when its model stores it) and the top of its range as the take-profit.
 */
export function investGuide(
  line: StockLine,
  { now, usdCad }: OrderContext,
  stopRules: Partial<Record<Market, StopRules>> = {},
): OrderPlan | null {
  if (line.price === null || (line.currency === 'USD' && usdCad === null)) return null
  const i: Instrument = { assetType: line.assetType, currency: line.currency, price: line.price, atrPct: line.atrPct, dollarVolume20: line.dollarVolume20 }
  const sized = { amountCad: line.amount, usdCad: usdCad ?? 1, now }
  const buy = planBuy(i, sized)
  if (line.assetType !== 'stock' || line.market === null) return buy
  const rules = stopRules[line.market] ?? DEFAULT_STOP_RULES
  const stop = pickStop(line.price, line.atrPct, line.horizonDays, rules)
  if (stop === null) return buy
  const bracket = planBracket(i, { ...sized, stop, q90: line.q90, exitBy: null, horizonDays: line.horizonDays })
  if (bracket.steps.length === 0) return buy
  const rule = `The bracket's stop loss is the picks' rule: ${rules.swingAtr}× the daily range under the price for a hold up to 20 days, ${rules.positionAtr}× (at most 15% under) for longer.`
  return joinPlans(buy, bracket, { steps: [], notes: [rule] })
}

/** The Invest page's BTC share: a limit buy at its CAD price when there is one, and the recurring alternative. */
export function btcGuide(crypto: { amount: number; priceCad: number | null }, { now }: OrderContext): OrderPlan {
  const buy =
    crypto.priceCad === null
      ? null
      : planBuy({ assetType: 'crypto', currency: 'CAD', price: crypto.priceCad, atrPct: null, dollarVolume20: null }, { amountCad: crypto.amount, usdCad: 1, now })
  return joinPlans(buy, planRecurring({ amountCad: crypto.amount, symbol: 'BTC' }))
}
