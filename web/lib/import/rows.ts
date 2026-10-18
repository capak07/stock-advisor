/**
 * Turning a broker's activity file into trades (spec §7.1, file import). The owner says what each
 * column means; every row then reads as a buy, a sell, or a line with a reason it was left out.
 */

import { ACCOUNTS } from '../portfolio/types'
import type { Account, AssetType, Trade } from '../portfolio/types'
import { isValidSymbol, normalizeSymbol, tradeCurrency } from '../symbols'
import { RATE_RANGE, parseAmount } from '../trade-form'

export type Meaning = 'date' | 'side' | 'symbol' | 'quantity' | 'price' | 'account' | 'currency' | 'fxRate' | 'ignore'

export const MEANINGS: { value: Meaning; label: string }[] = [
  { value: 'date', label: 'Date' },
  { value: 'side', label: 'Buy or sell' },
  { value: 'symbol', label: 'Symbol' },
  { value: 'quantity', label: 'Quantity' },
  { value: 'price', label: 'Price' },
  { value: 'account', label: 'Account' },
  { value: 'currency', label: 'Currency' },
  { value: 'fxRate', label: 'USD/CAD rate' },
  { value: 'ignore', label: 'Ignore' },
]

export const REQUIRED: readonly Meaning[] = ['date', 'side', 'symbol', 'quantity', 'price']

const GUESSES: [Meaning, RegExp][] = [
  ['date', /^(date|tradedate|transactiondate|activitydate|processdate|settlementdate)$/],
  ['side', /^(activitytype|transactiontype|type|action|side|activity|transaction|subtype)$/],
  ['symbol', /^(symbol|ticker|security|securitysymbol)$/],
  ['quantity', /^(quantity|qty|shares|units|numberofshares)$/],
  ['price', /^(price|unitprice|priceperunit|marketprice)$/],
  ['account', /^(account|accounttype|accountname)$/],
  ['currency', /^(currency|ccy|tradecurrency)$/],
  ['fxRate', /^(exchangerate|fxrate|fx|usdcad)$/],
]

/** What each column most likely means, from its header; each meaning is used once. */
export function guessMeanings(headers: readonly string[]): Meaning[] {
  const used = new Set<Meaning>()
  return headers.map((header) => {
    const key = header.toLowerCase().replace(/[^a-z]/g, '')
    const hit = GUESSES.find(([meaning, pattern]) => !used.has(meaning) && pattern.test(key))
    if (!hit) return 'ignore'
    used.add(hit[0])
    return hit[0]
  })
}

/** Meanings chosen for more than one column, and required ones chosen for none. */
export function meaningProblems(meanings: readonly Meaning[], accountFromColumn: boolean): string[] {
  const problems: string[] = []
  for (const m of MEANINGS) {
    const count = meanings.filter((x) => x === m.value).length
    if (m.value !== 'ignore' && count > 1) problems.push(`${m.label} is chosen for ${count} columns.`)
  }
  for (const m of [...REQUIRED, ...(accountFromColumn ? (['account'] as Meaning[]) : [])]) {
    if (!meanings.includes(m)) problems.push(`Choose the column with the ${MEANINGS.find((x) => x.value === m)!.label.toLowerCase()}.`)
  }
  return problems
}

export type DateOrder = 'ymd' | 'mdy' | 'dmy'

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
const pad = (n: number) => String(n).padStart(2, '0')

/** A date written as 2026-10-03 (a time may follow), Oct 3, 2026, 3 Oct 2026, or with slashes in `order`. */
export function readDate(raw: string, order: DateOrder): string | null {
  const text = raw.trim()
  let y: number, m: number, d: number
  let match = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T\s].*)?$/.exec(text)
  if (match) [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])]
  else if ((match = /^([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})$/.exec(text))) {
    ;[y, m, d] = [Number(match[3]), MONTHS.indexOf(match[1].toLowerCase()) + 1, Number(match[2])]
  } else if ((match = /^(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})$/.exec(text))) {
    ;[y, m, d] = [Number(match[3]), MONTHS.indexOf(match[2].toLowerCase()) + 1, Number(match[1])]
  } else if ((match = /^(\d{1,4})[/.](\d{1,2})[/.](\d{1,4})$/.exec(text))) {
    const [a, b, c] = [Number(match[1]), Number(match[2]), Number(match[3])]
    ;[y, m, d] = order === 'ymd' ? [a, b, c] : order === 'mdy' ? [c, a, b] : [c, b, a]
  } else return null
  if (m < 1 || m > 12 || d < 1 || y < 1900) return null
  const iso = `${y}-${pad(m)}-${pad(d)}`
  // Round-trip, so 2026-02-30 isn't accepted as March 2.
  return new Date(`${iso}T00:00:00Z`).toISOString().startsWith(iso) ? iso : null
}

const ACCOUNT_WORDS: [RegExp, Account][] = [
  [/tfsa/, 'tfsa'],
  [/rrsp|rsp/, 'rrsp'],
  [/fhsa/, 'fhsa'],
  [/crypto/, 'crypto'],
  [/non.?registered|personal|cash|margin|taxable/, 'non_registered'],
]

export const readAccount = (raw: string): Account | null =>
  ACCOUNT_WORDS.find(([pattern]) => pattern.test(raw.toLowerCase()))?.[1] ?? null

export const readSide = (raw: string): Trade['side'] | null => {
  const text = raw.toLowerCase()
  if (/\b(buy|bought|purchase)/.test(text)) return 'buy'
  if (/\b(sell|sold|sale)/.test(text)) return 'sell'
  return null
}

/** A trade as the import action receives it: the server sets the currency and fills a blank rate. */
export interface ImportTrade {
  side: Trade['side']
  account: Account
  symbol: string
  assetType: AssetType
  qty: number
  price: number
  day: string
  /** For a US stock, the rate in the file, if any; null to use the Bank of Canada's. */
  fxRate: number | null
}

export type RowStatus = 'ready' | 'skipped' | 'duplicate' | 'error'

export interface ImportRow {
  /** The row's line in the file, counting the header as line 1. */
  line: number
  status: RowStatus
  reason: string | null
  trade: ImportTrade | null
}

export interface ReadOptions {
  meanings: readonly Meaning[]
  /** One account for the whole file, or null to read it from the Account column. */
  account: Account | null
  dateOrder: DateOrder
  today: string
  /** Trades already recorded, so a file imported twice adds nothing. */
  existing: readonly Trade[]
}

const sameTrade = (a: Omit<Trade, 'currency' | 'fxRateCad'>, b: Omit<Trade, 'currency' | 'fxRateCad'>) =>
  a.side === b.side &&
  a.account === b.account &&
  a.symbol === b.symbol &&
  a.assetType === b.assetType &&
  a.day === b.day &&
  Math.abs(a.qty - b.qty) < 1e-9 &&
  Math.abs(a.price - b.price) < 1e-9

/**
 * Each data row (the header is row 1) as a ready trade, a duplicate of one already recorded or
 * earlier in the file, a row that isn't a trade (dividends, deposits), or an error with its reason.
 * A stock symbol without a suffix that the file prices in CAD is read as its TSX listing (RY → RY.TO).
 */
export function readRows(rows: readonly (readonly string[])[], options: ReadOptions): ImportRow[] {
  const col = (m: Meaning) => options.meanings.indexOf(m)
  const at = (row: readonly string[], m: Meaning) => (col(m) >= 0 ? (row[col(m)] ?? '').trim() : '')
  const seen: ImportTrade[] = []
  return rows.slice(1).map((row, i): ImportRow => {
    const line = i + 2
    const skip = (reason: string): ImportRow => ({ line, status: 'skipped', reason, trade: null })
    const error = (reason: string): ImportRow => ({ line, status: 'error', reason, trade: null })

    const sideText = at(row, 'side')
    const side = readSide(sideText)
    if (!side) return skip(sideText ? `Not a buy or a sell (${sideText}).` : 'No buy or sell given.')

    const account = options.account ?? readAccount(at(row, 'account'))
    if (!account || !ACCOUNTS.includes(account)) return error(`Unknown account "${at(row, 'account')}".`)
    const assetType: AssetType = account === 'crypto' ? 'crypto' : 'stock'

    let symbol = normalizeSymbol(at(row, 'symbol'))
    const currency = at(row, 'currency').toUpperCase()
    if (assetType === 'stock' && currency === 'CAD' && !symbol.endsWith('.TO') && /^[A-Z]{1,5}([.-][A-Z]{1,2})?$/.test(symbol)) {
      symbol = normalizeSymbol(`${symbol.replace('.', '-')}.TO`)
    }
    if (!isValidSymbol(symbol, assetType)) {
      return error(`"${at(row, 'symbol')}" isn't a ${assetType === 'crypto' ? 'coin' : 'stock'} symbol.`)
    }

    const day = readDate(at(row, 'date'), options.dateOrder)
    if (!day) return error(`Can't read the date "${at(row, 'date')}".`)
    if (day > options.today) return error('The date is after today.')

    const qty = parseAmount(at(row, 'quantity').replace(/^-/, ''))
    if (qty === null || qty <= 0) return error(`Can't read the quantity "${at(row, 'quantity')}".`)
    const price = parseAmount(at(row, 'price').replace(/^[A-Z]{0,3}\$?/i, ''))
    if (price === null || price <= 0) return error(`Can't read the price "${at(row, 'price')}".`)

    let fxRate: number | null = null
    if (tradeCurrency(assetType, symbol) === 'USD' && at(row, 'fxRate') !== '') {
      fxRate = parseAmount(at(row, 'fxRate'))
      if (fxRate === null || fxRate < RATE_RANGE[0] || fxRate > RATE_RANGE[1]) {
        return error(`Can't read the USD/CAD rate "${at(row, 'fxRate')}".`)
      }
    }

    const trade: ImportTrade = { side, account, symbol, assetType, qty, price, day, fxRate }
    if (options.existing.some((t) => sameTrade(t, trade))) {
      return { line, status: 'duplicate', reason: 'Already recorded.', trade }
    }
    if (seen.some((t) => sameTrade(t, trade))) {
      return { line, status: 'duplicate', reason: 'Twice in this file.', trade }
    }
    seen.push(trade)
    return { line, status: 'ready', reason: null, trade }
  })
}
