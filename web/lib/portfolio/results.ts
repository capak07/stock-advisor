import { daysBetween, shortDay } from '../dates'
import { fmtMoney, fmtPct, fmtPrice, fmtQty } from '../format'
import { buildLedger, inOrder, positionKey, QTY_EPSILON, tradeCad } from './ledger'
import type { FxRates, PriceBook } from './lookup'
import { ACCOUNT_LABELS, type Account, type AssetType, type Currency, type Trade } from './types'
import { valueHoldings } from './valuation'
import { lastClose } from './view'

/** A profit or loss in CAD and as a percent of what it cost (null without a cost). */
export interface Result {
  cad: number
  pct: number | null
}

/** What is still held of a holding, valued as the holdings table values it. */
export interface OpenPart {
  qty: number
  /** Average cost per unit in the trade currency; sells leave it unchanged. Null with mixed currencies. */
  avgCost: number | null
  /** The latest price in the trade currency (a live quote after a Refresh); null without one. */
  price: number | null
  /** In CAD as the holdings table values it: at cost without a price. */
  valueCad: number
  /** Null without a price: the holdings table shows such a holding at cost. */
  cad: number | null
  pct: number | null
}

/**
 * One holding of a stock or coin in one account, from its first buy until it was all sold: a stock sold in
 * full and bought again is two lines.
 */
export interface ResultLine {
  key: string
  account: Account
  symbol: string
  assetType: AssetType
  /** The currency its trades are in. */
  currency: Currency
  status: 'holding' | 'part' | 'sold'
  openedOn: string
  /** The day of the last sell, for a holding sold in full. */
  closedOn: string | null
  heldDays: number | null
  /** Average price of every buy and of every sell, in the trade currency; null without one or with mixed currencies. */
  avgBuy: number | null
  avgSell: number | null
  soldQty: number
  /** What the sells made, at average cost; null before any sell. */
  realized: Result | null
  /** Null once sold in full. */
  open: OpenPart | null
}

export interface Results {
  lines: ResultLine[]
  /** Everything the sells made, in CAD. */
  realizedCad: number
  /** What the holdings are up or down right now, in CAD (those with a price). */
  openCad: number
}

const average = (trades: readonly { qty: number; price: number; currency: Currency }[]): number | null => {
  const qty = trades.reduce((sum, t) => sum + t.qty, 0)
  if (qty <= 0 || new Set(trades.map((t) => t.currency)).size !== 1) return null
  return trades.reduce((sum, t) => sum + t.qty * t.price, 0) / qty
}

/**
 * Splits each position's trades into holdings, each ending when the quantity reaches zero. Trades are counted as the
 * ledger counts them: one without a CAD rate is left out, a sell with nothing held is left out, and a sell of more
 * than is held sells what is held.
 */
function holdingsOf(trades: readonly Trade[], fx: FxRates): Trade[][] {
  const byPosition = new Map<string, Trade[][]>()
  const held = new Map<string, number>()
  for (const t of inOrder(trades)) {
    if (tradeCad(t, fx) === null) continue
    const key = positionKey(t)
    const qty = held.get(key) ?? 0
    const groups = byPosition.get(key) ?? []
    byPosition.set(key, groups)
    if (t.side === 'buy') {
      if (qty <= QTY_EPSILON) groups.push([])
      groups.at(-1)!.push(t)
      held.set(key, qty + t.qty)
      continue
    }
    if (qty <= QTY_EPSILON) continue
    const counted = Math.min(t.qty, qty)
    groups.at(-1)!.push({ ...t, qty: counted })
    held.set(key, qty - counted <= QTY_EPSILON ? 0 : qty - counted)
  }
  return [...byPosition.values()].flat()
}

/** The average cost per unit, in the trade currency, of what is left after these trades. */
function openAvgCost(trades: readonly Trade[]): number | null {
  if (new Set(trades.map((t) => t.currency)).size !== 1) return null
  let qty = 0
  let cost = 0
  for (const t of trades) {
    if (t.side === 'buy') {
      qty += t.qty
      cost += t.qty * t.price
    } else {
      cost -= (cost * t.qty) / qty
      qty -= t.qty
    }
  }
  return qty > QTY_EPSILON ? cost / qty : null
}

function resultLine(trades: Trade[], prices: PriceBook, fx: FxRates): ResultLine {
  const first = trades[0]
  const buys = trades.filter((t) => t.side === 'buy')
  const sells = trades.filter((t) => t.side === 'sell')
  const ledger = buildLedger(trades, fx)
  const position = ledger.positions[0] ?? null
  const soldCost = ledger.sales.reduce((sum, s) => sum + s.costCad, 0)
  const realizedCad = ledger.sales.reduce((sum, s) => sum + s.gainCad, 0)
  const lastSell = sells.at(-1)?.day ?? null
  let open: OpenPart | null = null
  if (position !== null) {
    const [valued] = valueHoldings([position], prices, fx)
    const priced = valued.priceCad !== null
    open = {
      qty: position.qty,
      avgCost: openAvgCost(trades),
      price: priced ? (lastClose(position, prices, fx)?.close ?? null) : null,
      valueCad: valued.valueCad,
      cad: priced ? valued.gainCad : null,
      pct: priced && position.costCad > 0 ? valued.gainPct : null,
    }
  }
  const closedOn = position === null ? lastSell : null
  return {
    key: `${positionKey(first)}:${first.day}`,
    account: first.account,
    symbol: first.symbol,
    assetType: first.assetType,
    currency: first.currency,
    status: position === null ? 'sold' : sells.length > 0 ? 'part' : 'holding',
    openedOn: first.day,
    closedOn,
    heldDays: closedOn === null ? null : daysBetween(first.day, closedOn),
    avgBuy: average(buys),
    avgSell: average(sells),
    soldQty: sells.reduce((sum, t) => sum + t.qty, 0),
    realized: ledger.sales.length === 0 ? null : { cad: realizedCad, pct: soldCost > 0 ? (realizedCad / soldCost) * 100 : null },
    open,
  }
}

/**
 * Each holding's result (Results by stock): a stock sold in full shows what it made, one still held what it is up or
 * down right now, at average cost in CAD as the ledger counts it. Holdings come first, largest first, then the stocks
 * sold, most recently sold first.
 */
export function stockResults(trades: readonly Trade[], prices: PriceBook, fx: FxRates): Results {
  const lines = holdingsOf(trades, fx).map((group) => resultLine(group, prices, fx))
  const held = lines.filter((l) => l.open !== null).sort((a, b) => b.open!.valueCad - a.open!.valueCad)
  const sold = lines.filter((l) => l.open === null).sort((a, b) => (a.closedOn! < b.closedOn! ? 1 : a.closedOn! > b.closedOn! ? -1 : 0))
  return {
    lines: [...held, ...sold],
    realizedCad: lines.reduce((sum, l) => sum + (l.realized?.cad ?? 0), 0),
    openCad: lines.reduce((sum, l) => sum + (l.open?.cad ?? 0), 0),
  }
}

/** A line's two lines of detail: quantities and prices, then the account and dates. */
export function resultDetail(line: ResultLine): [string, string] {
  /** " @ US$200.00 avg", or nothing without an average (mixed currencies). */
  const at = (value: number | null) => (value === null ? '' : ` @ ${fmtPrice(value, line.currency)} avg`)
  const account = ACCOUNT_LABELS[line.account]
  if (line.open === null) {
    const days = line.heldDays ?? 0
    const bought = line.avgBuy === null ? '' : ` · bought${at(line.avgBuy)}`
    const sold = line.avgSell === null ? '' : ` → sold${at(line.avgSell)}`
    return [
      `${fmtQty(line.soldQty)}${bought}${sold}`,
      `${account} · ${shortDay(line.openedOn)} – ${shortDay(line.closedOn ?? line.openedOn)} · held ${days} ${days === 1 ? 'day' : 'days'}`,
    ]
  }
  const { qty, avgCost, price } = line.open
  const now = price === null ? 'no price yet' : `now ${fmtPrice(price, line.currency)}`
  const first =
    line.status === 'part'
      ? `Sold ${fmtQty(line.soldQty)}${at(line.avgSell)} · ${fmtQty(qty)} left${at(avgCost)} · ${now}`
      : `${fmtQty(qty)}${at(avgCost)} · ${now}`
  return [first, `${account} · since ${shortDay(line.openedOn)}`]
}

export interface ResultPart {
  label: 'sold' | 'now'
  amount: string
  pct: string | null
  tone: 'gain' | 'loss' | null
}

/** The profit or loss column: what the sells made, then what is left is up or down now. */
export function resultParts(line: ResultLine): ResultPart[] {
  const part = (label: ResultPart['label'], cad: number | null, pct: number | null): ResultPart =>
    cad === null
      ? { label, amount: '—', pct: null, tone: null }
      : { label, amount: fmtMoney(cad, { signed: true }), pct: pct === null ? null : fmtPct(pct), tone: cad < 0 ? 'loss' : 'gain' }
  const parts: ResultPart[] = []
  if (line.realized !== null) parts.push(part('sold', line.realized.cad, line.realized.pct))
  if (line.open !== null) parts.push(part('now', line.open.cad, line.open.pct))
  return parts
}
