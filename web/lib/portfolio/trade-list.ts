import { buildLedger, positionKey, tradeCad } from './ledger'
import type { FxRates } from './lookup'
import type { Account, AssetType, Currency, RecordedTrade } from './types'

/** One row of the portfolio page's trade list (Plan 5c). */
export interface TradeLine {
  /** `buy:12` or `sell:3`: ids are only unique within their table. */
  key: string
  id: number
  side: 'buy' | 'sell'
  day: string
  account: Account
  symbol: string
  assetType: AssetType
  qty: number
  price: number
  currency: Currency
  /** CAD per USD, when the trade stored one. */
  fxRateCad: number | null
  /** In CAD at the trade's own rate (or the Bank of Canada's for old USD trades); null if unknown. */
  amountCad: number | null
  /** Deleting this buy would leave a later sell with more than was held. */
  strandsSells: boolean
  /** A buy's note; sells have none. */
  notes: string | null
}

/** Problems in `after` that `before` didn't already have, so an edit can be refused for what it breaks. */
/**
 * Whether an edited buy now names a different asset: another symbol, or the same symbol as another
 * kind (a coin moved into a stock account). Such an edit is checked against the stock lists again,
 * and loses its link to the pick it came from.
 */
export function buyChangedAsset(current: RecordedTrade, next: { symbol: string; assetType: AssetType }): boolean {
  return next.symbol !== current.symbol || next.assetType !== current.assetType
}

export function addedProblems(before: readonly string[], after: readonly string[]): string[] {
  const left = new Map<string, number>()
  for (const problem of before) left.set(problem, (left.get(problem) ?? 0) + 1)
  const added: string[] = []
  for (const problem of after) {
    const n = left.get(problem) ?? 0
    if (n > 0) left.set(problem, n - 1)
    else added.push(problem)
  }
  return added
}

/**
 * The book with one stored trade replaced. Refuses a missing row, and an edit that would make the
 * ledger drop or shorten a trade it previously counted.
 */
export function replaceTrade(
  trades: readonly RecordedTrade[],
  next: RecordedTrade,
  fx: FxRates,
): { ok: true } | { error: string } {
  const index = trades.findIndex((t) => t.side === next.side && t.id === next.id)
  if (index < 0) return { error: `That ${next.side} was already gone.` }
  const updated = trades.map((t, i) => (i === index ? next : t))
  const added = addedProblems(buildLedger(trades, fx).problems, buildLedger(updated, fx).problems)
  if (added.length > 0) return { error: added[0] }
  return { ok: true }
}

/**
 * Every trade, newest first (a day's sells before its buys, the reverse of the ledger's order).
 * A buy that later sells depend on is marked, so Delete can say what it would break.
 */
export function tradeList(trades: readonly RecordedTrade[], fx: FxRates): TradeLine[] {
  // Removing a buy only changes its own position's ledger, so each buy is checked against the
  // other trades of its position alone.
  const byPosition = new Map<string, RecordedTrade[]>()
  for (const t of trades) {
    const key = positionKey(t)
    const group = byPosition.get(key) ?? []
    group.push(t)
    byPosition.set(key, group)
  }
  const stranding = new Set<RecordedTrade>()
  for (const group of byPosition.values()) {
    const problems = buildLedger(group, fx).problems.length
    for (const t of group) {
      if (t.side !== 'buy') continue
      const without = group.filter((other) => other !== t)
      if (buildLedger(without, fx).problems.length > problems) stranding.add(t)
    }
  }
  const lines = trades.map(
    (t): TradeLine => ({
      key: `${t.side}:${t.id}`,
      id: t.id,
      side: t.side,
      day: t.day,
      account: t.account,
      symbol: t.symbol,
      assetType: t.assetType,
      qty: t.qty,
      price: t.price,
      currency: t.currency,
      fxRateCad: t.fxRateCad,
      amountCad: tradeCad(t, fx),
      strandsSells: stranding.has(t),
      notes: t.notes,
    }),
  )
  return lines.sort((a, b) => {
    if (a.day !== b.day) return a.day < b.day ? 1 : -1
    if (a.side !== b.side) return a.side === 'sell' ? -1 : 1
    return b.id - a.id
  })
}
