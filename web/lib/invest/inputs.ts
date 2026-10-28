/** The Invest page's URL inputs (`/invest?amount=1000&crypto=10&stocks=5`), checked without ever throwing. */

import { addDays } from '../dates'
import { HOLDS, STOCKS, type Hold } from './allocate'

export const MIN_AMOUNT = 1
export const MAX_AMOUNT = 10_000_000
export const DEFAULT_CRYPTO_PCT = 10

type Param = string | string[] | undefined

export interface InvestInputs {
  /** What the boxes show again: the owner's own text. */
  amountText: string
  cryptoText: string
  /** Null when the amount is missing or invalid. */
  amount: number | null
  cryptoPct: number | null
  amountError: string | null
  cryptoError: string | null
  /** How many stocks to split over, 1 to STOCKS; null when the address asks for something else. */
  stocks: number | null
  stocksError: string | null
  /** How long to hold (a HOLDS value, 'any' by default), and the horizons it ranks on; null when the address asks for something else. */
  hold: Hold | null
  horizons: readonly number[] | null
  holdError: string | null
}

const first = (value: Param): string | undefined => (Array.isArray(value) ? value[0] : value)

const DECIMAL = /^\d+(\.\d+)?$/

/** "C$1,000", "$1,000.50", "1000" → a number; null for anything else. */
function parseAmount(text: string): number | null {
  const bare = text.trim().replace(/^C\$/i, '').replace(/[$,\s]/g, '')
  return DECIMAL.test(bare) ? Number(bare) : null
}

export function parseInvestInputs(params: { amount?: Param; crypto?: Param; stocks?: Param; hold?: Param }): InvestInputs {
  const amountRaw = first(params.amount)
  const cryptoRaw = first(params.crypto)
  const amountText = amountRaw ?? ''
  const cryptoText = cryptoRaw ?? String(DEFAULT_CRYPTO_PCT)

  let cryptoPct: number | null = DEFAULT_CRYPTO_PCT
  let cryptoError: string | null = null
  if (cryptoRaw !== undefined && cryptoRaw.trim() !== '') {
    const bare = cryptoRaw.trim().replace(/%$/, '').trim()
    const n = DECIMAL.test(bare) ? Number(bare) : null
    if (n === null || n > 100) {
      cryptoPct = null
      cryptoError = 'Enter a share from 0 to 100.'
    } else cryptoPct = n
  }

  let amount: number | null = null
  let amountError: string | null = null
  if (amountRaw !== undefined) {
    const n = parseAmount(amountRaw)
    if (amountRaw.trim() === '') amountError = 'Enter an amount.'
    else if (n === null || n < MIN_AMOUNT || n > MAX_AMOUNT) amountError = 'Enter an amount from C$1 to C$10,000,000.'
    else amount = n
  }

  const stocksRaw = first(params.stocks)?.trim()
  const count = !stocksRaw ? STOCKS : /^\d+$/.test(stocksRaw) ? Number(stocksRaw) : null
  const stocks = count !== null && count >= 1 && count <= STOCKS ? count : null
  const stocksError = stocks === null ? `Choose 1 to ${STOCKS} stocks.` : null

  const holdRaw = first(params.hold)?.trim() || 'any'
  const chosen = HOLDS.find((h) => h.value === holdRaw)
  const hold = chosen?.value ?? null
  const horizons = chosen?.horizons ?? null
  const holdError = chosen ? null : 'Choose how long to hold.'

  return { amountText, cryptoText, amount, cryptoPct, amountError, cryptoError, stocks, stocksError, hold, horizons, holdError }
}

/** The day `count` weekdays after `day`: an approximation of that many trading sessions. */
export function addWeekdays(day: string, count: number): string {
  let out = day
  for (let left = count; left > 0; ) {
    out = addDays(out, 1)
    const weekday = new Date(`${out}T12:00:00Z`).getUTCDay()
    if (weekday !== 0 && weekday !== 6) left--
  }
  return out
}
