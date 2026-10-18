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
  /** In CAD at the trade's own rate (or the Bank of Canada's for old USD trades); null if unknown. */
  amountCad: number | null
  /** Deleting this buy would leave a later sell with more than was held. */
  strandsSells: boolean
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
      amountCad: tradeCad(t, fx),
      strandsSells: stranding.has(t),
    }),
  )
  return lines.sort((a, b) => {
    if (a.day !== b.day) return a.day < b.day ? 1 : -1
    if (a.side !== b.side) return a.side === 'sell' ? -1 : 1
    return b.id - a.id
  })
}
