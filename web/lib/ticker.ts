/** What the Ticker page shows before the model exists (spec §9, Plan 5c). */

import { addDays } from './dates'
import type { FxRates } from './portfolio/lookup'
import type { AssetType, Close, Currency } from './portfolio/types'

export type Range = '1d' | '1w' | '1m' | '3m' | '6m' | '1y'
/** Each range in calendar days: a coin closes every day, a stock only on trading days. */
export const RANGES: { value: Range; label: string; days: number }[] = [
  { value: '1d', label: '1D', days: 1 },
  { value: '1w', label: '1W', days: 7 },
  { value: '1m', label: '1M', days: 31 },
  { value: '3m', label: '3M', days: 92 },
  { value: '6m', label: '6M', days: 183 },
  { value: '1y', label: '1Y', days: 365 },
]

export interface PriceSeries {
  days: string[]
  values: number[]
  currency: Currency
}

/**
 * The price history to chart: a stock in its own currency, a coin in CAD at each day's Bank of
 * Canada rate (Coinbase prices coins in USD), as the portfolio values them. Days without a rate yet
 * are left out.
 */
export function priceSeries(closes: readonly Close[], assetType: AssetType, fx: FxRates): PriceSeries {
  const days: string[] = []
  const values: number[] = []
  for (const close of closes) {
    const value = assetType === 'crypto' ? fx.toCad(close) : close.close
    if (value === null) continue
    days.push(close.day)
    values.push(value)
  }
  const currency: Currency = assetType === 'crypto' || closes[0]?.currency !== 'USD' ? 'CAD' : 'USD'
  return { days, values, currency }
}

/**
 * The last `range` of calendar days before the latest close, from the latest close on or before
 * that cutoff, so the chart covers the whole range; from the first close when none is that old.
 */
export function inRange(series: PriceSeries, range: Range): PriceSeries {
  const last = series.days.at(-1)
  if (last === undefined) return series
  const cutoff = addDays(last, -RANGES.find((r) => r.value === range)!.days)
  const start = Math.max(0, series.days.findLastIndex((day) => day <= cutoff))
  return { ...series, days: series.days.slice(start), values: series.values.slice(start) }
}

export interface LastMove {
  price: number
  day: string
  change: number | null
  pct: number | null
}

/** The latest close and its move from the close before. */
export function lastMove(series: PriceSeries): LastMove | null {
  const n = series.values.length
  if (n === 0) return null
  const price = series.values[n - 1]
  const before = n > 1 ? series.values[n - 2] : null
  return {
    price,
    day: series.days[n - 1],
    change: before === null ? null : price - before,
    pct: before === null || before === 0 ? null : ((price - before) / before) * 100,
  }
}

/** The Ticker page of an asset: a coin says so, since a coin and a stock can share a symbol. */
export const tickerHref = (symbol: string, assetType: AssetType): string =>
  `/ticker/${encodeURIComponent(symbol)}${assetType === 'crypto' ? '?asset=crypto' : ''}`

/** Only web links: a headline's link is never allowed to run script. */
export function safeLink(url: string): string | null {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null
  } catch {
    return null
  }
}

/** FinBERT's score, −1 to +1, as the mockup shows it: "+0.25", "−0.22". */
export const fmtScore = (value: number): string => {
  const rounded = Number(value.toFixed(2))
  return `${rounded > 0 ? '+' : rounded < 0 ? '−' : '+'}${Math.abs(rounded).toFixed(2)}`
}

/** The sentiment chip's tone: beyond ±0.2 reads as positive or negative. */
export const tone = (value: number | null): 'pos' | 'neg' | 'neu' =>
  value === null ? 'neu' : value > 0.2 ? 'pos' : value < -0.2 ? 'neg' : 'neu'
