import { marketOf } from '../symbols'
import { RISK_LABELS, RISK_LEVELS, type HoldingAction } from './actions'
import { positionKey } from './ledger'
import type { FxRates, PriceBook } from './lookup'
import { ACCOUNT_LABELS, TAXABLE, assetKey } from './types'
import type { Account, Market, Position } from './types'
import type { Warning } from './warnings'

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

export const NOT_RATED = 'Not rated'

/**
 * Shares of portfolio value by the risk level of each holding's latest action (spec §7.4), from Low
 * to Very high. A holding with no action row, or none with a risk level, is "Not rated", last.
 */
export function byRisk(holdings: readonly Holding[], actions: readonly HoldingAction[]): Slice[] {
  const total = holdings.reduce((sum, h) => sum + h.valueCad, 0)
  if (total <= 0) return []
  const risk = new Map(actions.map((a) => [positionKey(a), a.riskLevel]))
  const sums = new Map<string, number>()
  for (const h of holdings) {
    const level = risk.get(positionKey(h))
    const label = level ? RISK_LABELS[level] : NOT_RATED
    sums.set(label, (sums.get(label) ?? 0) + h.valueCad)
  }
  return [...RISK_LEVELS.map((level) => RISK_LABELS[level]), NOT_RATED]
    .filter((label) => sums.has(label))
    .map((label) => ({ label, share: ((sums.get(label) ?? 0) / total) * 100 }))
}

/** The most of the portfolio's value one sector should hold (spec §7.4). */
export const SECTOR_GUIDELINE_PCT = 25

/**
 * One warning per sector above 25% of the portfolio's value (spec §7.4). Coins and stocks with no
 * sector label count toward the total but belong to no sector.
 */
export function sectorWarnings(holdings: readonly Holding[], sectors: ReadonlyMap<string, string>): Warning[] {
  const total = holdings.reduce((sum, h) => sum + h.valueCad, 0)
  if (total <= 0) return []
  const bySector = new Map<string, { value: number; symbols: Map<string, number> }>()
  for (const h of holdings) {
    const sector = h.assetType === 'stock' ? sectors.get(h.symbol) : undefined
    if (!sector) continue
    const entry = bySector.get(sector) ?? { value: 0, symbols: new Map<string, number>() }
    entry.value += h.valueCad
    entry.symbols.set(h.symbol, (entry.symbols.get(h.symbol) ?? 0) + h.valueCad)
    bySector.set(sector, entry)
  }
  return [...bySector]
    .map(([sector, { value, symbols }]) => ({ sector, share: (value / total) * 100, symbols }))
    .filter((s) => s.share > SECTOR_GUIDELINE_PCT)
    .sort((a, b) => b.share - a.share)
    .map(({ sector, share, symbols }) => ({
      title: `${sector} is ${share.toFixed(1)}% of the portfolio (guideline ${SECTOR_GUIDELINE_PCT}%)`,
      detail: listed([...symbols].sort((a, b) => b[1] - a[1]).map(([symbol]) => symbol)),
    }))
}

/** "AAPL", "AAPL and MSFT", "AAPL, MSFT and NVDA" */
const listed = (items: readonly string[]): string =>
  items.length <= 1 ? (items[0] ?? '') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`

/** The estimated taxable amount of an unrealized gain or loss: 50% inclusion (spec §7.5). */
export const taxableEstimate = (h: Holding): number | null => (TAXABLE.has(h.account) ? h.gainCad * 0.5 : null)
