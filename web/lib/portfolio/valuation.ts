import { marketOf } from '../symbols'
import type { FxRates, PriceBook } from './lookup'
import { ACCOUNT_LABELS, TAXABLE, assetKey } from './types'
import type { Account, Market, Position } from './types'

export interface Holding extends Position {
  market: Market | null
  /** The latest close, in CAD at the latest Bank of Canada rate; null before the first close. */
  priceCad: number | null
  priceDay: string | null
  /** At the latest close; at cost when there's no close yet. */
  valueCad: number
  gainCad: number
  gainPct: number
}

/**
 * Values each position at its latest close. USD closes (US stocks, and coins, which Coinbase
 * prices in USD) convert at the latest Bank of Canada rate (spec §7.4).
 */
export function valueHoldings(positions: readonly Position[], prices: PriceBook, fx: FxRates): Holding[] {
  const rate = fx.latest()?.usdCad ?? null
  return positions.map((position) => {
    const close = prices.latest(assetKey(position.assetType, position.symbol))
    const priceCad =
      close === null ? null : close.currency === 'CAD' ? close.close : rate === null ? null : close.close * rate
    const valueCad = priceCad === null ? position.costCad : position.qty * priceCad
    const gainCad = valueCad - position.costCad
    return {
      ...position,
      market: position.assetType === 'stock' ? marketOf(position.symbol) : null,
      priceCad,
      priceDay: priceCad === null ? null : (close?.day ?? null),
      valueCad,
      gainCad,
      gainPct: position.costCad > 0 ? (gainCad / position.costCad) * 100 : 0,
    }
  })
}

export interface Totals {
  valueCad: number
  costCad: number
  gainCad: number
  /** Symbols valued at cost because they have no close yet. */
  unpriced: string[]
}

export function totals(holdings: readonly Holding[]): Totals {
  const valueCad = holdings.reduce((sum, h) => sum + h.valueCad, 0)
  const costCad = holdings.reduce((sum, h) => sum + h.costCad, 0)
  const unpriced = [...new Set(holdings.filter((h) => h.priceCad === null).map((h) => h.symbol))].sort()
  return { valueCad, costCad, gainCad: valueCad - costCad, unpriced }
}

export interface Slice {
  label: string
  share: number
}

/** Shares of portfolio value by market (US, TSX, Crypto) or by account, largest first. */
export function breakdown(holdings: readonly Holding[], by: 'market' | 'account'): Slice[] {
  const total = holdings.reduce((sum, h) => sum + h.valueCad, 0)
  if (total <= 0) return []
  const sums = new Map<string, number>()
  for (const h of holdings) {
    const label = by === 'market' ? (h.market ?? 'Crypto') : ACCOUNT_LABELS[h.account as Account]
    sums.set(label, (sums.get(label) ?? 0) + h.valueCad)
  }
  return [...sums]
    .map(([label, value]) => ({ label, share: (value / total) * 100 }))
    .sort((a, b) => b.share - a.share)
}

/** The estimated taxable amount of an unrealized gain or loss: 50% inclusion (spec §7.5). */
export const taxableEstimate = (h: Holding): number | null => (TAXABLE.has(h.account) ? h.gainCad * 0.5 : null)
