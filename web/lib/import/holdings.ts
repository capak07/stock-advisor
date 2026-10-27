/**
 * Wealthsimple's holdings report: a snapshot of every position, with no trades in it. Compared with
 * what's recorded, each change becomes a trade dated on the report, so after the import the
 * recorded quantity and CAD cost match Wealthsimple's book value.
 */

import { shortDay } from '../dates'
import { fmtQty } from '../format'
import { positionKey, QTY_EPSILON } from '../portfolio/ledger'
import { ACCOUNT_LABELS } from '../portfolio/types'
import type { Account, AssetType, Close, Trade } from '../portfolio/types'
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
  /** Trades already recorded: a report older than a position's last trade can't be compared with it. */
  existing: readonly Trade[]
}

export const isHoldingsReport = (header: readonly string[]): boolean => COLUMNS.every((c) => header.includes(c))

/** A plain or scientific number (Wealthsimple writes small coin prices as 4.28956E-06). */
function readNumber(raw: string): number | null {
  const text = raw.replace(/[,\s$]/g, '')
  return /^-?\d*\.?\d+(e[-+]?\d+)?$/i.test(text) ? Number(text) : null
}

/** Half a unit in the last place the report printed: 10.147 may stand for a recorded 10.14723. */
function tolerance(raw: string, qty: number): number {
  const decimals = /\.(\d+)$/.exec(raw.replace(/[,\s]/g, ''))?.[1].length
  return decimals ? 0.5 * 10 ** -decimals : QTY_EPSILON * Math.max(1, qty)
}

const label = (p: { symbol: string; account: Account }) => `${p.symbol} (${ACCOUNT_LABELS[p.account]})`

interface Listed {
  account: Account
  assetType: AssetType
  symbol: string
  qty: number
  tolerance: number
  marketPrice: number
  bookCad: number
  /** CAD per USD, from the book values; null for a CAD position. */
  rate: number | null
  day: string
}

/** One row read: its account and position once known, then either the position or why it can't be read. */
interface Read {
  line: number
  account: Account | null
  symbol: string | null
  key: string | null
  listed: Listed | null
  error: string | null
}

function readRow(row: readonly string[], line: number, index: Record<Column, number>, today: string): Read {
  const at = (c: Column) => (row[index[c]] ?? '').trim()
  const read: Read = { line, account: null, symbol: null, key: null, listed: null, error: null }
  const error = (reason: string): Read => ({ ...read, error: reason })

  const account = readAccount(at('Account Type'))
  if (!account) return error(`Unknown account "${at('Account Type')}".`)
  read.account = account
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
  read.symbol = symbol
  read.key = positionKey({ account, assetType, symbol })

  if (at('Position Direction').toUpperCase() !== 'LONG') return error("A short position can't be imported.")
  const day = readDate(at('Date'), 'mdy')
  if (!day) return error(`Can't read the date "${at('Date')}".`)
  if (day > today) return error('The date is after today.')
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
  const rate = currency === 'USD' ? bookCad / bookMarket : null
  if (rate !== null && !(rate >= RATE_RANGE[0] && rate <= RATE_RANGE[1])) {
    return error(`The book values imply a USD/CAD rate of ${rate.toFixed(4)}, which can't be right.`)
  }
  const listed = { account, assetType, symbol, qty, tolerance: tolerance(at('Quantity'), qty), marketPrice, bookCad, rate, day }
  return { ...read, listed }
}

/**
 * Each report row as the trade that brings the recorded position to it, or why it adds nothing;
 * then a sell at the last close for each recorded position the report no longer lists, in the
 * accounts it covers (those rows have no line). A larger position is a buy costing the rise in
 * book value; a smaller one a sell at the report's market price and the Bank of Canada rate.
 * A position the report lists twice, or one in an account with an unreadable row, is never traded.
 */
export function readHoldingsReport(rows: readonly (readonly string[])[], options: ReportOptions): ImportRow[] {
  const header = rows[0] ?? []
  const index = Object.fromEntries(COLUMNS.map((c) => [c, header.indexOf(c)])) as Record<Column, number>
  const reads = rows.slice(1).map((row, i) => readRow(row, i + 2, index, options.today))
  const held = new Map(options.held.map((p) => [positionKey(p), p]))
  const times = new Map<string, number>()
  for (const r of reads) if (r.key) times.set(r.key, (times.get(r.key) ?? 0) + 1)
  // an unreadable row in an account might be any of its positions, so none of them is sold as gone
  const unsure = new Set(reads.filter((r) => r.account && !r.key).map((r) => r.account!))
  const covered = new Set(reads.flatMap((r) => (r.account ? [r.account] : [])))
  const days = reads.flatMap((r) => (r.listed ? [r.listed.day] : []))
  const reportDay = days.length > 0 ? days.reduce((a, b) => (a > b ? a : b)) : options.today

  const lastTrade = (key: string) =>
    options.existing.reduce<string | null>((last, t) => (positionKey(t) === key && (last === null || t.day > last) ? t.day : last), null)
  /** Why the position can't be compared with a report of `day`, if a recorded trade comes after it. */
  const tooOld = (p: { symbol: string; account: Account }, key: string, day: string) => {
    const last = lastTrade(key)
    return last !== null && last > day ? `${label(p)} has a trade recorded on ${shortDay(last)}, after this report: import a newer report.` : null
  }
  // The server fills a blank rate with the Bank of Canada's, and has none before `rateFrom`.
  const noRate = (t: ImportTrade) =>
    tradeCurrency(t.assetType, t.symbol) === 'USD' && t.fxRate === null && (options.rateFrom === null || t.day < options.rateFrom)
      ? `No Bank of Canada rate is stored for ${t.day}. Add this trade under Buy or Sell with its rate.`
      : null

  const out = reads.map((r): ImportRow => {
    const error = (reason: string): ImportRow => ({ line: r.line, status: 'error', reason, trade: null })
    const p = r.listed
    if (r.key && times.get(r.key)! > 1) {
      return error(`${label({ symbol: r.symbol!, account: r.account! })} is in the report more than once: add its changes under Buy or Sell.`)
    }
    if (!p || !r.key) return error(r.error!)
    const old = tooOld(p, r.key, p.day)
    if (old) return error(old)

    const before = held.get(r.key)
    const heldQty = before?.qty ?? 0
    const ready = (trade: ImportTrade, reason: string): ImportRow => {
      const missing = noRate(trade)
      return missing ? error(missing) : { line: r.line, status: 'ready', reason, trade }
    }
    if (Math.abs(p.qty - heldQty) <= p.tolerance) {
      return { line: r.line, status: 'duplicate', reason: 'No change since it was recorded.', trade: null }
    }
    const base = { account: p.account, symbol: p.symbol, assetType: p.assetType, day: p.day }
    if (p.qty < heldQty) {
      if (before && p.bookCad >= before.costCad) {
        return error(`${label(p)} fell from ${fmtQty(heldQty)} but its book value didn't: a reverse split or a transfer out? Add it under Sell.`)
      }
      return ready({ ...base, side: 'sell', qty: heldQty - p.qty, price: p.marketPrice, fxRate: null }, `Down from ${fmtQty(heldQty)}.`)
    }
    const added = p.qty - heldQty
    const addedCad = p.bookCad - (before?.costCad ?? 0)
    if (addedCad <= 0) {
      return error(`${label(p)} rose from ${fmtQty(heldQty)} but its book value didn't: a split or a transfer in? Add it under Buy.`)
    }
    const reason = before ? `Up from ${fmtQty(heldQty)}.` : 'New position.'
    return ready({ ...base, side: 'buy', qty: added, price: addedCad / added / (p.rate ?? 1), fxRate: p.rate }, reason)
  })

  for (const p of options.held) {
    const key = positionKey(p)
    if (!covered.has(p.account) || times.has(key)) continue
    const error = (reason: string) => out.push({ line: null, status: 'error', reason, trade: null })
    const currency = tradeCurrency(p.assetType, p.symbol)
    const close = p.lastClose
    const old = tooOld(p, key, reportDay)
    if (unsure.has(p.account)) {
      error(`${label(p)} is not in the report, but some of its ${ACCOUNT_LABELS[p.account]} rows couldn't be read, so it isn't sold.`)
    } else if (old) error(old)
    else if (!close) error(`${label(p)} is not in the report and has no stored close: add its sell under Sell.`)
    else if (close.currency !== currency) {
      error(`${label(p)} is not in the report and its last close is in ${close.currency}, not ${currency}: add its sell under Sell.`)
    } else {
      const trade: ImportTrade = { side: 'sell', account: p.account, symbol: p.symbol, assetType: p.assetType, qty: p.qty, price: close.close, day: reportDay, fxRate: null }
      const missing = noRate(trade)
      if (missing) error(missing)
      else out.push({ line: null, status: 'ready', reason: `Not in the report: sold at the last close (${shortDay(close.day)}).`, trade })
    }
  }
  return out
}
