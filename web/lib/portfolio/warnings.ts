import { addDays, longDay, shortDay } from '../dates'
import { QTY_EPSILON, inOrder } from './ledger'
import { TAXABLE } from './types'
import type { Sale, Trade } from './types'

export interface Warning {
  title: string
  detail: string
  /** The holding the warning is about, for the holdings table's notes. */
  symbol?: string
  note?: string
}

export interface TfsaGuideline {
  roundTrips: number
  /** Share of holds under 30 days, 0..1. */
  shortHoldShare: number
}

/** Warn this far ahead of the round-trip guideline. */
export const ROUND_TRIP_WARN_AT = 0.75
/** Too few sells to call holds "mostly short". */
export const MIN_SALES_FOR_SHARE = 4
const SHORT_HOLD_DAYS = 30

/**
 * TFSA trading frequency (spec §7.5): each TFSA sell in the last 12 months closes a round trip.
 * Warns as round trips reach 75% of the owner's guideline, and when more than the guideline's
 * share of those holds lasted under 30 days (once there are at least four).
 */
export function tfsaWarnings(sales: readonly Sale[], guideline: TfsaGuideline, today: string): Warning[] {
  const since = addDays(today, -365)
  const recent = sales.filter((s) => s.account === 'tfsa' && s.day > since && s.day <= today)
  const warnings: Warning[] = []
  if (recent.length > 0 && recent.length >= Math.ceil(guideline.roundTrips * ROUND_TRIP_WARN_AT)) {
    warnings.push({
      title: `TFSA: ${recent.length} round trips in 12 months`,
      detail: `Your guideline is ${guideline.roundTrips}. Frequent TFSA trading can make gains taxable as business income.`,
    })
  }
  const short = recent.filter((s) => s.heldDays < SHORT_HOLD_DAYS).length
  if (recent.length >= MIN_SALES_FOR_SHARE && short / recent.length > guideline.shortHoldShare) {
    warnings.push({
      title: `TFSA: ${short} of ${recent.length} holds under 30 days`,
      detail: `Your guideline is ${Math.round(guideline.shortHoldShare * 100)}% of holds. Frequent TFSA trading can make gains taxable as business income.`,
    })
  }
  return warnings
}

/** How much of an asset is held, across accounts, after the trades of `day`. */
function heldAfter(trades: readonly Trade[], symbol: string, assetType: Trade['assetType'], day: string): number {
  let qty = 0
  for (const t of inOrder(trades)) {
    if (t.day > day) break
    if (t.symbol !== symbol || t.assetType !== assetType) continue
    qty = t.side === 'buy' ? qty + t.qty : Math.max(0, qty - t.qty)
  }
  return qty
}

/**
 * Superficial losses (spec §7.5): a loss realized in a taxable account is denied when the same
 * asset is bought within 30 days before or after the sale and still held 30 days after it.
 * Covers sales from the last 30 days; until the window ends, "still held" means held today.
 */
export function superficialLossWarnings(sales: readonly Sale[], trades: readonly Trade[], today: string): Warning[] {
  return sales
    .filter((s) => TAXABLE.has(s.account) && s.gainCad < 0 && s.day > addDays(today, -31) && s.day <= today)
    .map((sale) => {
      const end = addDays(sale.day, 30)
      const bought = trades.find(
        (t) =>
          t.side === 'buy' &&
          t.symbol === sale.symbol &&
          t.assetType === sale.assetType &&
          t.day >= addDays(sale.day, -30) &&
          t.day <= end,
      )
      const stillHeld = heldAfter(trades, sale.symbol, sale.assetType, end < today ? end : today) > QTY_EPSILON
      if (bought && stillHeld) {
        return {
          symbol: sale.symbol,
          title: `${sale.symbol}: the loss is likely superficial`,
          detail: `You sold at a loss on ${longDay(sale.day)}, bought on ${longDay(bought.day)}, within 30 days, and still hold it. The loss is likely denied and added to the cost of what you hold.`,
          note: 'Loss likely denied',
        }
      }
      return {
        symbol: sale.symbol,
        title: `${sale.symbol}: superficial-loss window`,
        detail: `You sold ${sale.symbol} at a loss on ${longDay(sale.day)}. Buying it back before ${longDay(end)} denies that loss.`,
        note: `Loss window to ${shortDay(end)}`,
      }
    })
}
