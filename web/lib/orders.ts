/**
 * How to place a trade in Wealthsimple (docs/superpowers/specs/2026-10-28-order-guidance-design.md).
 * Execution rules of thumb, not forecasts. They rest on Wealthsimple's order rules as checked on
 * 2026-10-28: fractions trade only at market; a stop-limit lasts to the close unless extended to 90
 * days; a crypto limit order cancels after 24 hours unless extended; recurring buys run daily,
 * weekly, every two weeks or monthly. The numbers marked ★ in the design are its calls.
 */

import { fmtMoney, fmtPrice, fmtQty } from './format'
import type { AssetType, Currency } from './portfolio/types'

/** ★ A buy's limit sits this share of the daily range above the price, within these bounds. */
const BUY_BUFFER = { share: 0.25, min: 0.002, max: 0.015, unknown: 0.01 }
/** ★ A stop-limit's limit sits this share of the daily range below its stop, within these bounds. */
const STOP_GAP = { share: 0.5, min: 0.01, max: 0.05, unknown: 0.03 }
/** ★ At this 20-day dollar volume a stock is liquid enough for a market order. */
const LIQUID_DOLLAR_VOLUME = 10_000_000
/** ★ A fractional remainder smaller than this isn't worth a separate market order. */
const MIN_FRACTION_CAD = 25
/** ★ A trim sells this share of the position. */
const TRIM_SHARE = 1 / 3
/** ★ The Invest page's BTC share is spread weekly over this many weeks. */
const RECURRING_WEEKS = 4

const OPEN_MINUTE = 9 * 60 + 30
const CLOSE_MINUTE = 16 * 60

/** What an order is placed on: its price in its trading currency (coins trade in CAD) and how it moves. */
export interface Instrument {
  assetType: AssetType
  currency: Currency
  price: number
  /** The 14-day average daily range as a fraction of price; null when unknown. */
  atrPct: number | null
  /** Average daily dollar volume over 20 sessions; null when unknown. */
  dollarVolume20: number | null
}

export interface OrderStep {
  kind: 'limit' | 'market' | 'stop-limit' | 'alert' | 'recurring'
  side: 'buy' | 'sell'
  /** Shares or coins; null when the order is by amount. */
  qty: number | null
  /** The order's CAD amount when it is placed by amount; else null. */
  amountCad: number | null
  /** A limit order's price. */
  price: number | null
  stop: number | null
  /** A stop-limit's limit price. */
  limit: number | null
  /** 'day', 'next trading day', '24 hours', '90 days' or null. */
  expiry: string | null
  /** The step in words, as the page shows it. */
  text: string
}

export interface OrderPlan {
  steps: OrderStep[]
  /** Cautions shown under the steps. */
  notes: string[]
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
const buffer = (atr: number | null) => (atr === null ? BUY_BUFFER.unknown : clamp(atr * BUY_BUFFER.share, BUY_BUFFER.min, BUY_BUFFER.max))
const gap = (atr: number | null) => (atr === null ? STOP_GAP.unknown : clamp(atr * STOP_GAP.share, STOP_GAP.min, STOP_GAP.max))
const liquid = (i: Instrument) => i.assetType === 'stock' && i.dollarVolume20 !== null && i.dollarVolume20 >= LIQUID_DOLLAR_VOLUME

/** A price an order form accepts: cents from 1 up, four significant figures below. */
export const roundPrice = (v: number): number => (v >= 1 ? Math.round(v * 100) / 100 : Number(v.toPrecision(4)))
const roundQty = (q: number) => Math.round(q * 1e6) / 1e6

const TORONTO = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Toronto', weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })

/** Weekdays 9:30 to 16:00 in Toronto. Holidays aren't modelled (★). */
export function isMarketHours(now: Date): boolean {
  const parts = Object.fromEntries(TORONTO.formatToParts(now).map((p) => [p.type, p.value]))
  if (parts.weekday === 'Sat' || parts.weekday === 'Sun') return false
  const minute = Number(parts.hour) * 60 + Number(parts.minute)
  return minute >= OPEN_MINUTE && minute < CLOSE_MINUTE
}

const step = (s: Partial<OrderStep> & Pick<OrderStep, 'kind' | 'side' | 'text'>): OrderStep => ({
  qty: null,
  amountCad: null,
  price: null,
  stop: null,
  limit: null,
  expiry: null,
  ...s,
})

/** How long a stock limit order lasts, and how the page says it. */
function stockExpiry(now: Date): { expiry: string; words: string } {
  return isMarketHours(now)
    ? { expiry: 'day', words: 'Day order' }
    : { expiry: 'next trading day', words: 'set it to expire at the end of the next trading day' }
}

const CRYPTO_EXPIRY = 'it cancels after 24 hours unless you extend it'
const GAP_NOTE = 'A stop-limit won’t fill if the price gaps below its limit; a stop-market order sells in a gap at whatever price comes.'
const fractionNote = (fraction: number) =>
  `The ${fmtQty(fraction)} sh fraction can’t carry a stop order; Wealthsimple trades fractions only at market.`

function stopLimit(i: Instrument, qty: number, stop: number, prefix: string, previousStop: number | null): OrderStep {
  const limit = roundPrice(stop * (1 - gap(i.atrPct)))
  const raise = previousStop !== null && stop > previousStop * (1 + 1e-9) ? ` · raise it from ${fmtPrice(previousStop, i.currency)}` : ''
  return step({
    kind: 'stop-limit',
    side: 'sell',
    qty,
    stop,
    limit,
    expiry: '90 days',
    text: `${prefix} ${qty} sh: stop ${fmtPrice(stop, i.currency)}, limit ${fmtPrice(limit, i.currency)}, expiry 90 days${raise}`,
  })
}

/**
 * A buy of `amountCad`: whole shares with a limit order, a fractional remainder of C$25 or more at
 * market, then (for a stock, with a `stop`) a 90-day stop-limit on the whole shares. A coin is a
 * limit buy by amount, in CAD (pass its CAD price), with no stop order.
 */
export function planBuy(i: Instrument, { amountCad, usdCad, now, stop }: { amountCad: number; usdCad: number; now: Date; stop?: number | null }): OrderPlan {
  const price = roundPrice(i.price * (1 + buffer(i.atrPct)))
  if (i.assetType === 'crypto') {
    return {
      steps: [
        step({
          kind: 'limit',
          side: 'buy',
          qty: roundQty(amountCad / price),
          amountCad,
          price,
          expiry: '24 hours',
          text: `Limit buy ${fmtMoney(amountCad)} of it at ${fmtPrice(price, 'CAD')} · ${CRYPTO_EXPIRY}`,
        }),
      ],
      notes: [],
    }
  }

  const toCad = i.currency === 'USD' ? usdCad : 1
  const whole = Math.floor(amountCad / (price * toCad))
  const left = amountCad - whole * price * toCad
  const steps: OrderStep[] = []
  const notes: string[] = []
  const { expiry, words } = stockExpiry(now)
  if (whole >= 1) {
    steps.push(step({ kind: 'limit', side: 'buy', qty: whole, price, expiry, text: `Limit buy ${whole} sh at ${fmtPrice(price, i.currency)} · ${words}` }))
  }
  const fraction = whole >= 1 ? (left >= MIN_FRACTION_CAD ? Math.round(left) : 0) : amountCad
  if (fraction > 0) {
    steps.push(
      step({
        kind: 'market',
        side: 'buy',
        amountCad: fraction,
        text: `Market buy ${fmtMoney(fraction)} (fractional: Wealthsimple fills fractions only as market orders; not in the first 15 minutes after the open)`,
      }),
    )
  }
  if (liquid(i)) notes.push('A market buy is fine too for a stock this liquid, but not in the first 15 minutes after the open.')
  if (stop && whole >= 1) {
    steps.push(stopLimit(i, whole, stop, 'Then a stop-limit sell', null))
    notes.push(GAP_NOTE)
  }
  return { steps, notes }
}

/** Whole shares by a limit `price`, and any fraction at market. */
function sellSteps(i: Instrument, qty: number, price: number, now: Date): OrderStep[] {
  const whole = Math.floor(qty + 1e-9)
  const fraction = roundQty(qty - whole)
  const steps: OrderStep[] = []
  if (i.assetType === 'crypto') {
    return [step({ kind: 'limit', side: 'sell', qty: roundQty(qty), price, expiry: '24 hours', text: `Limit sell ${fmtQty(roundQty(qty))} at ${fmtPrice(price, 'CAD')} · ${CRYPTO_EXPIRY}` })]
  }
  const { expiry, words } = stockExpiry(now)
  if (whole >= 1) steps.push(step({ kind: 'limit', side: 'sell', qty: whole, price, expiry, text: `Limit sell ${whole} sh at ${fmtPrice(price, i.currency)} · ${words}` }))
  if (fraction > 0) {
    steps.push(step({ kind: 'market', side: 'sell', qty: fraction, text: `Market sell the ${fmtQty(fraction)} sh fraction (Wealthsimple sells fractions only at market)` }))
  }
  return steps
}

/** A Sell: everything, with a limit a buffer under the price; a liquid stock may simply sell at market. */
export function planSell(i: Instrument, { qty, now }: { qty: number; now: Date }): OrderPlan {
  const price = roundPrice(i.price * (1 - buffer(i.atrPct)))
  return {
    steps: sellSteps(i, qty, price, now),
    notes: liquid(i) ? ['A market sell is fine for a stock this liquid; this one needs out.'] : [],
  }
}

/** A Trim: about a third of the position (at least one share), with a limit a half-buffer above the price. */
export function planTrim(i: Instrument, { qty, now }: { qty: number; now: Date }): OrderPlan {
  const price = roundPrice(i.price * (1 + buffer(i.atrPct) / 2))
  if (i.assetType === 'stock' && qty < 1) {
    const part = roundQty(qty * TRIM_SHARE)
    return { steps: [step({ kind: 'market', side: 'sell', qty: part, text: `Market sell ${fmtQty(part)} sh (Wealthsimple sells fractions only at market)` })], notes: [] }
  }
  const part = i.assetType === 'crypto' ? roundQty(qty * TRIM_SHARE) : Math.max(1, Math.floor(qty * TRIM_SHARE))
  return { steps: sellSteps(i, part, price, now), notes: ['A trim isn’t urgent, so ask a little above the price.'] }
}

/**
 * The stop to keep on a holding: a 90-day stop-limit on its whole shares, saying when it should be
 * raised from the previous run's stop. A coin gets one only if Wealthsimple offers it, else a price alert.
 */
export function planStop(i: Instrument, { qty, stop, previousStop }: { qty: number; stop: number; previousStop: number | null }): OrderPlan {
  if (i.assetType === 'crypto') {
    const limit = roundPrice(stop * (1 - gap(i.atrPct)))
    return {
      steps: [
        step({
          kind: 'alert',
          side: 'sell',
          qty,
          stop,
          limit,
          text: `If Wealthsimple offers a stop order for this coin, stop ${fmtPrice(stop, 'CAD')}, limit ${fmtPrice(limit, 'CAD')}; otherwise set a price alert at ${fmtPrice(stop, 'CAD')}`,
        }),
      ],
      notes: [],
    }
  }
  const whole = Math.floor(qty + 1e-9)
  const fraction = roundQty(qty - whole)
  const steps = whole >= 1 ? [stopLimit(i, whole, stop, 'Stop-limit sell', previousStop)] : []
  const notes = [...(whole >= 1 ? [GAP_NOTE] : []), ...(fraction > 0 ? [fractionNote(fraction)] : [])]
  return { steps, notes }
}

/** The Invest page's BTC share as a weekly recurring buy, as an alternative to buying it at once. */
export function planRecurring({ amountCad, symbol }: { amountCad: number; symbol: string }): OrderPlan {
  const each = Math.round(amountCad / RECURRING_WEEKS)
  return {
    steps: [
      step({
        kind: 'recurring',
        side: 'buy',
        amountCad: each,
        text: `Or a recurring buy of ${fmtMoney(each)} of ${symbol} weekly for ${RECURRING_WEEKS} weeks (Wealthsimple offers daily, weekly, every two weeks or monthly)`,
      }),
    ],
    notes: [],
  }
}
