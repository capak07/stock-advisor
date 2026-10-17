/** Number formats from the Ledger mockups: a real minus sign, and en-CA grouping. */

const MINUS = '−'

/** "+6.0%", "−16.1%", "0.0%" */
export const fmtPct = (value: number, digits = 1): string => {
  const rounded = Number(Math.abs(value).toFixed(digits))
  const sign = rounded === 0 ? '' : value > 0 ? '+' : MINUS
  return `${sign}${rounded.toFixed(digits)}%`
}

const grouped = (value: number, digits: number): string =>
  Math.abs(value).toLocaleString('en-CA', { minimumFractionDigits: digits, maximumFractionDigits: digits })

/** "C$34,237", "−C$405"; `signed` adds "+" to gains. */
export const fmtMoney = (value: number, { prefix = 'C$', digits = 0, signed = false } = {}): string => {
  const text = grouped(value, digits)
  const zero = Number(text.replace(/,/g, '')) === 0
  const sign = zero ? '' : value < 0 ? MINUS : signed ? '+' : ''
  return `${sign}${prefix}${text}`
}

/** A bare amount for table cells: "2,115", "−405", "+937" when signed. */
export const fmtAmount = (value: number, { digits = 0, signed = false } = {}): string =>
  fmtMoney(value, { prefix: '', digits, signed })

/** A price in its own currency: "US$163.40", "C$171.20". */
export const fmtPrice = (value: number, currency: 'CAD' | 'USD'): string =>
  fmtMoney(value, { prefix: currency === 'USD' ? 'US$' : 'C$', digits: value < 1 ? 4 : 2 })

/** Quantities keep up to 8 decimals for coins: "10", "0.5", "1.25". */
export const fmtQty = (value: number): string =>
  value.toLocaleString('en-CA', { maximumFractionDigits: 8 })
