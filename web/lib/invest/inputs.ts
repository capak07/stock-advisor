/** The Invest page's URL inputs (`/invest?amount=1000&asset=stocks&stocks=5`), checked without ever throwing. */

import { addDays } from '../dates'
import { CRYPTO_HOLDS, HOLDS, STOCKS, type Hold } from './allocate'

export const MIN_AMOUNT = 1
export const MAX_AMOUNT = 10_000_000

export type AssetChoice = 'stocks' | 'crypto'

type Param = string | string[] | undefined

export interface InvestInputs {
  /** What the amount box shows again: the owner's own text. */
  amountText: string
  /** Null when the amount is missing or invalid. */
  amount: number | null
  amountError: string | null
  /** Stocks or crypto; null when the address asks for something else. */
  asset: AssetChoice | null
  assetError: string | null
  /** How many names to split over, 1 to STOCKS; null when the address asks for something else. */
  stocks: number | null
  stocksError: string | null
  /** How long to hold, and the horizons it ranks on; null when the address asks for something else. */
  hold: Hold | null
  horizons: readonly number[] | null
  holdError: string | null
}

/** The hold choices for the kind of asset. A coin's horizons are calendar days, a stock's trading days. */
export const holdsFor = (asset: AssetChoice) => (asset === 'crypto' ? CRYPTO_HOLDS : HOLDS)

const first = (value: Param): string | undefined => (Array.isArray(value) ? value[0] : value)

const DECIMAL = /^\d+(\.\d+)?$/

/** "C$1,000", "$1,000.50", "1000" → a number; null for anything else. */
function parseAmount(text: string): number | null {
  const bare = text.trim().replace(/^C\$/i, '').replace(/[$,\s]/g, '')
  return DECIMAL.test(bare) ? Number(bare) : null
}

export function parseInvestInputs(params: { amount?: Param; asset?: Param; stocks?: Param; hold?: Param }): InvestInputs {
  const amountRaw = first(params.amount)
  const amountText = amountRaw ?? ''

  let amount: number | null = null
  let amountError: string | null = null
  if (amountRaw !== undefined) {
    const n = parseAmount(amountRaw)
    if (amountRaw.trim() === '') amountError = 'Enter an amount.'
    else if (n === null || n < MIN_AMOUNT || n > MAX_AMOUNT) amountError = 'Enter an amount from C$1 to C$10,000,000.'
    else amount = n
  }

  const assetRaw = first(params.asset)?.trim() || 'stocks'
  const asset: AssetChoice | null = assetRaw === 'stocks' || assetRaw === 'crypto' ? assetRaw : null
  const assetError = asset ? null : 'Choose stocks or crypto.'
  const noun = asset === 'crypto' ? 'coins' : 'stocks'

  const stocksRaw = first(params.stocks)?.trim()
  const count = !stocksRaw ? STOCKS : /^\d+$/.test(stocksRaw) ? Number(stocksRaw) : null
  const stocks = count !== null && count >= 1 && count <= STOCKS ? count : null
  const stocksError = stocks === null ? `Choose 1 to ${STOCKS} ${noun}.` : null

  const holdRaw = first(params.hold)?.trim() || 'any'
  const chosen = asset ? holdsFor(asset).find((h) => h.value === holdRaw) : undefined
  const hold = chosen?.value ?? null
  const horizons = chosen?.horizons ?? null
  const holdError = chosen ? null : 'Choose how long to hold.'

  return { amountText, amount, amountError, asset, assetError, stocks, stocksError, hold, horizons, holdError }
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
