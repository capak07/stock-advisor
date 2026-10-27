/**
 * Wealthsimple's holdings report: a snapshot of every position, with no trades in it. Compared with
 * what's recorded, each change becomes a trade dated on the report, so after the import the
 * recorded quantity and CAD cost match Wealthsimple's book value.
 */

import { shortDay } from '../dates'
import { positionKey, QTY_EPSILON } from '../portfolio/ledger'
import { ACCOUNT_LABELS } from '../portfolio/types'
import type { Account, AssetType, Close } from '../portfolio/types'
import { isValidSymbol, normalizeSymbol, tradeCurrency } from '../symbols'
import { RATE_RANGE } from '../trade-form'
import { readAccount, readDate, type ImportRow, type ImportTrade } from './rows'

const COLUMNS = [
  'Account Type', 'Symbol', 'MIC', 'Security Type', 'Quantity', 'Position Direction', 'Market Price',
  'Market Price Currency', 'Book Value (CAD)', 'Book Value (Market)', 'Book Value Currency (Market)', 'Date',
] as const
type Column = (typeof COLUMNS)[number]

const TSX_MIC = 'XTSE'

/** A recorded open position, as the portfolio's sell options give it. */
export interface HeldPosition {
  account: Account
  assetType: AssetType
  symbol: string
  qty: number
  costCad: number
  /** The latest stored close, in the asset's trade currency, or null when none is stored. */
  lastClose: Close | null
}

export interface ReportOptions {
  today: string
  held: readonly HeldPosition[]
  /** The earliest day with a stored USD/CAD rate (`fx_rates`), or null when none is stored. */
  rateFrom: string | null
}

export const isHoldingsReport = (header: readonly string[]): boolean => COLUMNS.every((c) => header.includes(c))

/** A plain or scientific number (Wealthsimple writes small coin prices as 4.28956E-06). */
function readNumber(raw: string): number | null {
  const text = raw.replace(/[,\s$]/g, '')
  return /^-?\d*\.?\d+(e[-+]?\d+)?$/i.test(text) ? Number(text) : null
}

const label = (p: { symbol: string; account: Account }) => `${p.symbol} (${ACCOUNT_LABELS[p.account]})`

/**
 * Each report row as the trade that brings the recorded position to it, or why it adds nothing;
 * then a sell at the last close for each recorded position the report no longer lists, in the
 * accounts it covers (those rows have no line). A larger position is a buy costing the rise in
 * book value; a smaller one a sell at the report's market price and the Bank of Canada rate.
 */
export function readHoldingsReport(rows: readonly (readonly string[])[], options: ReportOptions): ImportRow[] {
  const header = rows[0] ?? []
  const index = Object.fromEntries(COLUMNS.map((c) => [c, header.indexOf(c)])) as Record<Column, number>
  const held = new Map(options.held.map((p) => [positionKey(p), p]))
  const covered = new Set<Account>()
  const listed = new Set<string>()
  const ready = new Set<string>()
  let reportDay: string | null = null

  // The server fills a blank rate with the Bank of Canada's, and has none before `rateFrom`.
  const noRate = (t: ImportTrade) =>
    tradeCurrency(t.assetType, t.symbol) === 'USD' && t.fxRate === null && (options.rateFrom === null || t.day < options.rateFrom)
  const noRateReason = (day: string) =>
    `No Bank of Canada rate is stored for ${day}. Add this trade under Buy or Sell with its rate.`

  const out: ImportRow[] = rows.slice(1).map((row, i): ImportRow => {
    const line = i + 2
    const at = (c: Column) => (row[index[c]] ?? '').trim()
    const error = (reason: string): ImportRow => ({ line, status: 'error', reason, trade: null })

    const account = readAccount(at('Account Type'))
    if (!account) return error(`Unknown account "${at('Account Type')}".`)
    covered.add(account)
    const assetType: AssetType = at('Security Type').toUpperCase() === 'CRYPTOCURRENCY' ? 'crypto' : 'stock'
    const raw = at('Symbol')
    let symbol = normalizeSymbol(raw)
    if (assetType === 'stock') {
      const mic = at('MIC').toUpperCase()
      if (mic === TSX_MIC) symbol = normalizeSymbol(`${symbol.replace('.', '-')}.TO`)
      else if (at('Book Value Currency (Market)').toUpperCase() !== 'USD') {
        return error(`Only TSX and US listings can be imported (${raw} trades on ${mic || 'an unknown exchange'}).`)
      }
    }
    if ((assetType === 'crypto') !== (account === 'crypto')) {
      return error(`${raw} is ${assetType === 'crypto' ? 'a coin' : 'a stock'}, but the account is ${ACCOUNT_LABELS[account]}.`)
    }
    if (!isValidSymbol(symbol, assetType)) return error(`"${raw}" isn't a ${assetType === 'crypto' ? 'coin' : 'stock'} symbol.`)
    const key = positionKey({ account, assetType, symbol })
    if (listed.has(key)) return error(`${label({ symbol, account })} is in the report twice.`)
    listed.add(key)

    if (at('Position Direction').toUpperCase() !== 'LONG') return error("A short position can't be imported.")
    const day = readDate(at('Date'), 'mdy')
    if (!day) return error(`Can't read the date "${at('Date')}".`)
    if (day > options.today) return error('The date is after today.')
    const qty = readNumber(at('Quantity'))
    if (qty === null || qty <= 0) return error(`Can't read the quantity "${at('Quantity')}".`)
    const currency = tradeCurrency(assetType, symbol)
    const marketPrice = readNumber(at('Market Price'))
    if (marketPrice === null || marketPrice <= 0 || at('Market Price Currency').toUpperCase() !== currency) {
      return error(`Can't read the market price "${at('Market Price')} ${at('Market Price Currency')}".`)
    }
    const bookCad = readNumber(at('Book Value (CAD)'))
    const bookMarket = readNumber(at('Book Value (Market)'))
    if (bookCad === null || bookCad <= 0 || bookMarket === null || bookMarket <= 0) {
      return error(`Can't read the book value "${at('Book Value (CAD)')}".`)
    }
    // the rate the book values imply: what the position cost in CAD per USD
    const rate = currency === 'USD' ? bookCad / bookMarket : null
    if (rate !== null && !(rate >= RATE_RANGE[0] && rate <= RATE_RANGE[1])) {
      return error(`The book values imply a USD/CAD rate of ${rate.toFixed(4)}, which can't be right.`)
    }
    reportDay = reportDay === null || day > reportDay ? day : reportDay

    const before = held.get(key)
    const heldQty = before?.qty ?? 0
    const base = { account, symbol, assetType, day }
    const done = (trade: ImportTrade, reason: string): ImportRow => {
      if (noRate(trade)) return error(noRateReason(day))
      ready.add(key)
      return { line, status: 'ready', reason, trade }
    }
    if (Math.abs(qty - heldQty) <= QTY_EPSILON * Math.max(1, qty)) {
      return { line, status: 'duplicate', reason: 'No change since it was recorded.', trade: null }
    }
    if (qty < heldQty) {
      return done({ ...base, side: 'sell', qty: heldQty - qty, price: marketPrice, fxRate: null }, `Down from ${heldQty}.`)
    }
    const added = qty - heldQty
    const addedCad = bookCad - (before?.costCad ?? 0)
    const reason = before ? `Up from ${heldQty}.` : 'New position.'
    if (addedCad <= 0) {
      return done(
        { ...base, side: 'buy', qty: added, price: marketPrice, fxRate: rate },
        `Up from ${heldQty}; the book value didn't rise, so at the market price.`,
      )
    }
    return done({ ...base, side: 'buy', qty: added, price: addedCad / added / (rate ?? 1), fxRate: rate }, reason)
  })

  const day = reportDay ?? options.today
  for (const p of options.held) {
    const key = positionKey(p)
    if (!covered.has(p.account) || listed.has(key)) continue
    const close = p.lastClose
    if (!close || close.currency !== tradeCurrency(p.assetType, p.symbol)) {
      out.push({ line: null, status: 'error', reason: `${label(p)} is not in the report and has no stored close: add its sell under Sell.`, trade: null })
      continue
    }
    const trade: ImportTrade = { side: 'sell', account: p.account, symbol: p.symbol, assetType: p.assetType, qty: p.qty, price: close.close, day, fxRate: null }
    if (noRate(trade)) out.push({ line: null, status: 'error', reason: noRateReason(day), trade: null })
    else out.push({ line: null, status: 'ready', reason: `Not in the report: sold at the last close (${shortDay(close.day)}).`, trade })
  }
  return out
}
