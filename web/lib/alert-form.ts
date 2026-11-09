import type { AssetType } from './portfolio/types'
import { isValidSymbol, marketOf } from './symbols'
import { parseAmount, type FieldErrors } from './trade-form'

export const MAX_NOTE = 200
export const MAX_ACTIVE_ALERTS = 20

export type AlertDirection = 'above' | 'below'

export interface AlertInput {
  symbol: string
  assetType: string
  direction: string
  level: string
  note?: string
}

export type ParsedAlert =
  | { ok: true; value: { symbol: string; assetType: AssetType; direction: AlertDirection; level: number; note: string | null } }
  | { ok: false; errors: FieldErrors }

/** The currency an alert's level is in: the asset's price currency (CAD for TSX stocks, USD otherwise, coins included). */
export const alertCurrency = (symbol: string, assetType: AssetType): 'USD' | 'CAD' =>
  assetType === 'stock' && marketOf(symbol) === 'TSX' ? 'CAD' : 'USD'

/** The level as the alert lists show it: "$400.00". */
export const fmtLevel = (value: number): string =>
  `$${value.toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 8 })}`

/** The feed line for a hit alert (the card shows the symbol before it). */
export const alertTitle = (direction: AlertDirection, level: number): string =>
  `crossed ${direction} ${fmtLevel(level)} by the last run`

/** Checks an alert form's input; the database's CHECKs are the last line. */
export function parseAlert(input: AlertInput): ParsedAlert {
  const errors: FieldErrors = {}
  const assetType = input.assetType === 'stock' || input.assetType === 'crypto' ? input.assetType : null
  if (!assetType || !isValidSymbol(input.symbol, assetType)) errors.symbol = 'That is not a stock or coin symbol.'
  if (input.direction !== 'above' && input.direction !== 'below') errors.direction = 'Choose above or below.'

  const raw = (input.level ?? '').replace(/[,\s$]/g, '')
  const level = parseAmount(input.level)
  if (level === null || level <= 0) errors.level = 'Enter a price greater than zero.'
  else if (/\.\d{9,}$/.test(raw)) errors.level = 'Use at most 8 decimal places.'

  const note = (input.note ?? '').trim()
  if (note.length > MAX_NOTE) errors.note = `Keep the note to ${MAX_NOTE} characters.`

  if (Object.keys(errors).length || !assetType || level === null) return { ok: false, errors }
  return {
    ok: true,
    value: { symbol: input.symbol, assetType, direction: input.direction as AlertDirection, level, note: note || null },
  }
}
