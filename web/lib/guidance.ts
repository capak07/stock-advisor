/**
 * Which order plan (lib/orders.ts) each page's trade gets: a pick, a watched Buy, a holding's action
 * and its stop, an Invest line (docs/superpowers/specs/2026-10-28-order-guidance-design.md).
 */

import type { PickView } from './data/picks'
import type { StoredVerdict } from './data/watchlist'
import { fmtMoney } from './format'
import type { StockLine } from './invest/allocate'
import { planBuy, planRecurring, planSell, planStop, planTrim, type Instrument, type OrderPlan } from './orders'
import type { HoldingAction, RiskLevel } from './portfolio/actions'
import { tradeCurrency } from './symbols'

/** A buy sized for a portfolio with no value yet. */
export const DEFAULT_BUY_CAD = 1000

/** Spec §6.4: each risk level's suggested max position, in percent of the portfolio. */
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

function stockBuy(
  stock: { symbol: string; price: number; stop: number; maxPositionPct: number; atrPct: number | null; dollarVolume20: number | null },
  portfolioCad: number | null,
  { now, usdCad }: OrderContext,
): Guide | null {
  const currency = tradeCurrency('stock', stock.symbol)
  if (currency === 'USD' && usdCad === null) return null
  const i: Instrument = { assetType: 'stock', currency, price: stock.price, atrPct: stock.atrPct, dollarVolume20: stock.dollarVolume20 }
  const { amountCad, caption } = buyAmount(stock.maxPositionPct, portfolioCad)
  return { plan: planBuy(i, { amountCad, usdCad: usdCad ?? 1, now, stop: stock.stop }), caption }
}

/** A pick bought at its entry price for its max size, with its stop. */
export const pickGuide = (p: PickView, portfolioCad: number | null, ctx: OrderContext): Guide | null =>
  stockBuy({ symbol: p.symbol, price: p.entry, stop: p.stop, maxPositionPct: p.maxPositionPct, atrPct: p.atrPct, dollarVolume20: p.dollarVolume20 }, portfolioCad, ctx)

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
  return stockBuy({ symbol, price, stop, maxPositionPct, atrPct: v.atrPct, dollarVolume20: v.dollarVolume20 }, portfolioCad, ctx)
}

/**
 * A holding's order for its action (Sell, Trim, Add; a Hold has none) and the stop to keep on it.
 * Prices are converted to the currency the asset trades in: a coin's Coinbase USD prices to CAD.
 */
export function holdingGuides(
  a: HoldingAction,
  { qty, valueCad, portfolioCad }: { qty: number; valueCad: number; portfolioCad: number },
  { now, usdCad }: OrderContext,
): { order: OrderPlan | null; stop: OrderPlan | null } {
  const currency = tradeCurrency(a.assetType, a.symbol)
  const needsRate = currency === 'USD' || a.assetType === 'crypto'
  if (needsRate && usdCad === null) return { order: null, stop: null }
  const toTrading = (v: number | null) => (v === null ? null : a.assetType === 'crypto' ? v * usdCad! : v)
  const price = toTrading(a.refPrice)
  const trailingStop = toTrading(a.trailingStop)
  const instrument = (p: number): Instrument => ({ assetType: a.assetType, currency, price: p, atrPct: a.atrPct, dollarVolume20: a.dollarVolume20 })

  let order: OrderPlan | null = null
  if (price !== null && a.action === 'sell') order = planSell(instrument(price), { qty, now })
  if (price !== null && a.action === 'trim') order = planTrim(instrument(price), { qty, now })
  if (price !== null && a.action === 'add' && a.riskLevel !== null) {
    const amountCad = (MAX_POSITION_PCT[a.riskLevel] * portfolioCad) / 100 - valueCad
    if (amountCad > 0) order = planBuy(instrument(price), { amountCad, usdCad: usdCad ?? 1, now, stop: trailingStop })
  }
  // planStop reads only the stop and the daily range, so a holding without a decision price still gets one
  const stop =
    trailingStop === null ? null : planStop(instrument(price ?? trailingStop), { qty, stop: trailingStop, previousStop: toTrading(a.previousStop) })
  return { order, stop }
}

/** An Invest stock line bought for its amount, with no stop (the page isn't a pick). */
export function investGuide(line: StockLine, { now, usdCad }: OrderContext): OrderPlan | null {
  if (line.price === null || (line.currency === 'USD' && usdCad === null)) return null
  const i: Instrument = { assetType: 'stock', currency: line.currency, price: line.price, atrPct: line.atrPct, dollarVolume20: line.dollarVolume20 }
  return planBuy(i, { amountCad: line.amount, usdCad: usdCad ?? 1, now })
}

/** The Invest page's BTC share: a limit buy at its CAD price when there is one, and the recurring alternative. */
export function btcGuide(crypto: { amount: number; priceCad: number | null }, { now }: OrderContext): OrderPlan {
  const buy =
    crypto.priceCad === null
      ? null
      : planBuy({ assetType: 'crypto', currency: 'CAD', price: crypto.priceCad, atrPct: null, dollarVolume20: null }, { amountCad: crypto.amount, usdCad: 1, now })
  return joinPlans(buy, planRecurring({ amountCad: crypto.amount, symbol: 'BTC' }))
}
