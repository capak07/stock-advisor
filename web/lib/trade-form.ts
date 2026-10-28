/** Checks for the buy and sell forms (spec §7.1). The server actions run them; the database's
 * CHECK constraints are the last line. */

import { QTY_EPSILON } from './portfolio/ledger'
import { ACCOUNTS, ACCOUNT_LABELS } from './portfolio/types'
import type { Account, AssetType, Currency } from './portfolio/types'
import { fmtQty } from './format'
import { longDay } from './dates'
import { isValidSymbol, normalizeSymbol, tradeCurrency } from './symbols'

export type FieldErrors = Partial<Record<string, string>>

/** What a trade form's server action answers. `at` tells two identical answers apart. */
export interface FormState {
  ok?: boolean
  message?: string
  errors?: FieldErrors
  /** A stock that isn't in the lists: the owner must confirm it. */
  confirm?: string
  at?: number
}

/** A typed amount: "1,234.50" or "$12" read as numbers; anything else is null. */
export const parseAmount = (raw: string | undefined): number | null => {
  const text = (raw ?? '').replace(/[,\s$]/g, '')
  if (text === '' || !/^\d*\.?\d+$/.test(text)) return null
  return Number(text)
}
const number = parseAmount

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/
const validDay = (day: string) => ISO_DAY.test(day) && !Number.isNaN(Date.parse(`${day}T00:00:00Z`))

/** USD/CAD outside this range is a typo, not a rate. */
export const RATE_RANGE = [0.5, 3] as const

interface Common {
  qty: number
  price: number
  day: string
  /** For a USD trade: the rate entered, or null to use the Bank of Canada's. */
  fxRateCad: number | null
}

function common(form: Record<string, string>, today: string, currency: Currency, errors: FieldErrors): Common | null {
  const qty = number(form.qty)
  const price = number(form.price)
  const day = (form.day ?? '').trim()
  if (qty === null || qty <= 0) errors.qty = 'Enter a quantity above 0.'
  if (price === null || price <= 0) errors.price = 'Enter a price above 0.'
  if (!validDay(day)) errors.day = 'Enter a date.'
  else if (day > today) errors.day = "The date can't be after today."
  let fxRateCad: number | null = null
  if (currency === 'USD' && (form.fxRate ?? '').trim() !== '') {
    fxRateCad = number(form.fxRate)
    if (fxRateCad === null || fxRateCad < RATE_RANGE[0] || fxRateCad > RATE_RANGE[1]) {
      errors.fxRate = 'Enter the USD/CAD rate, for example 1.37.'
    }
  }
  if (qty === null || price === null || errors.qty || errors.price || errors.day || errors.fxRate) return null
  return { qty, price, day, fxRateCad }
}

export interface BuyInput extends Common {
  account: Account
  symbol: string
  assetType: AssetType
  currency: Currency
  notes: string | null
  /** The pick this buy came from ("I bought this"), so it's graded as the owner's. */
  pickId: number | null
}

/** A positive integer id, else null: a malformed link is dropped, never an error. */
const parseId = (raw: string | undefined): number | null => {
  const text = (raw ?? '').trim()
  if (!/^\d+$/.test(text)) return null
  const id = Number(text)
  return Number.isSafeInteger(id) && id > 0 ? id : null
}

export function parseBuy(form: Record<string, string>, today: string): { input: BuyInput } | { errors: FieldErrors } {
  const errors: FieldErrors = {}
  const account = form.account as Account
  if (!ACCOUNTS.includes(account)) errors.account = 'Pick an account.'
  const assetType: AssetType = account === 'crypto' ? 'crypto' : 'stock'
  const symbol = normalizeSymbol(form.symbol ?? '')
  if (!isValidSymbol(symbol, assetType)) {
    errors.symbol = assetType === 'crypto' ? 'Enter a coin symbol, like BTC.' : 'Enter a symbol like AAPL or RY.TO.'
  }
  const currency = tradeCurrency(assetType, symbol)
  const notes = (form.notes ?? '').trim()
  if (notes.length > 500) errors.notes = 'Keep notes under 500 characters.'
  const rest = common(form, today, currency, errors)
  if (!rest || Object.keys(errors).length > 0) return { errors }
  return { input: { ...rest, account, symbol, assetType, currency, notes: notes || null, pickId: parseId(form.pick_id) } }
}

/** An open position the sell form can sell from. */
export interface Held {
  key: string
  account: Account
  symbol: string
  assetType: AssetType
  qty: number
  openedOn: string
}

export interface SellInput extends Common {
  account: Account
  symbol: string
  assetType: AssetType
  currency: Currency
}

export function parseSell(
  form: Record<string, string>,
  held: readonly Held[],
  today: string,
): { input: SellInput } | { errors: FieldErrors } {
  const errors: FieldErrors = {}
  const position = held.find((h) => h.key === form.holding)
  if (!position) {
    errors.holding = 'Pick a holding.'
    return { errors }
  }
  const currency = tradeCurrency(position.assetType, position.symbol)
  const rest = common(form, today, currency, errors)
  if (rest && rest.qty > position.qty + QTY_EPSILON) {
    errors.qty = `You hold ${fmtQty(position.qty)} in your ${ACCOUNT_LABELS[position.account]}.`
  }
  if (rest && rest.day < position.openedOn) errors.day = `That's before you bought it, on ${longDay(position.openedOn)}.`
  if (!rest || Object.keys(errors).length > 0) return { errors }
  return {
    input: { ...rest, account: position.account, symbol: position.symbol, assetType: position.assetType, currency },
  }
}

/** FormData as plain strings; files and repeated fields aren't used by these forms. */
export const formFields = (form: FormData): Record<string, string> =>
  Object.fromEntries([...form.entries()].map(([k, v]) => [k, typeof v === 'string' ? v : '']))
