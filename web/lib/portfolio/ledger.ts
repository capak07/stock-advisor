import { daysBetween } from '../dates'
import type { FxRates } from './lookup'
import type { Position, Sale, Trade } from './types'

/** Below this, a quantity is a rounding leftover and the position is closed. */
export const QTY_EPSILON = 1e-9

/**
 * A trade's amount in CAD. A USD trade uses its own rate; trades recorded before spec rev 2 have
 * none, so they use the Bank of Canada rate of that day. Null when no rate is known.
 */
export function tradeCad(trade: Trade, fx: FxRates): number | null {
  const amount = trade.qty * trade.price
  if (trade.currency === 'CAD') return amount
  const rate = trade.fxRateCad ?? fx.on(trade.day)
  return rate === null ? null : amount * rate
}

/** Trades in the order they count: by day, and a day's buys before its sells. */
export function inOrder(trades: readonly Trade[]): Trade[] {
  return [...trades].sort((a, b) => {
    if (a.day !== b.day) return a.day < b.day ? -1 : 1
    if (a.side !== b.side) return a.side === 'buy' ? -1 : 1
    return 0
  })
}

export const positionKey = (p: Pick<Trade, 'account' | 'assetType' | 'symbol'>): string =>
  `${p.account}:${p.assetType}:${p.symbol}`

export interface Ledger {
  /** Open positions, by account and asset. */
  positions: Position[]
  /** Every sell, at average cost. */
  sales: Sale[]
  /** Trades that couldn't be applied as entered, in plain words. */
  problems: string[]
}

/**
 * Average cost (adjusted cost base) per account and asset, as Canadian tax rules require
 * (spec §7.1). A sell reduces the quantity at average cost; its gain is proceeds minus average
 * cost × quantity, in CAD. A sell of more than is held is applied to what is held.
 */
export function buildLedger(trades: readonly Trade[], fx: FxRates): Ledger {
  const open = new Map<string, Position>()
  const sales: Sale[] = []
  const problems: string[] = []

  for (const trade of inOrder(trades)) {
    const key = positionKey(trade)
    const cad = tradeCad(trade, fx)
    if (cad === null) {
      problems.push(`${trade.symbol} on ${trade.day}: no USD/CAD rate for that day, so it's left out.`)
      continue
    }
    const held = open.get(key)
    if (trade.side === 'buy') {
      if (held) {
        held.qty += trade.qty
        held.costCad += cad
      } else {
        open.set(key, {
          account: trade.account,
          symbol: trade.symbol,
          assetType: trade.assetType,
          qty: trade.qty,
          costCad: cad,
          openedOn: trade.day,
        })
      }
      continue
    }
    if (!held) {
      problems.push(`${trade.symbol} on ${trade.day}: a sell with nothing held, so it's left out.`)
      continue
    }
    let qty = trade.qty
    let proceeds = cad
    if (qty > held.qty + QTY_EPSILON) {
      problems.push(
        `${trade.symbol} on ${trade.day}: sold ${trade.qty} but held ${held.qty}; counted as ${held.qty}.`,
      )
      proceeds = (cad * held.qty) / qty
      qty = held.qty
    }
    const cost = (held.costCad * qty) / held.qty
    sales.push({
      account: trade.account,
      symbol: trade.symbol,
      assetType: trade.assetType,
      day: trade.day,
      qty,
      proceedsCad: proceeds,
      costCad: cost,
      gainCad: proceeds - cost,
      heldDays: daysBetween(held.openedOn, trade.day),
    })
    held.qty -= qty
    held.costCad -= cost
    if (held.qty <= QTY_EPSILON) open.delete(key)
  }

  return { positions: [...open.values()], sales, problems }
}
