/** What the Ticker page shows before the model exists (spec §9, Plan 5c). */

import { parseAlert, type AlertDirection } from './alert-form'
import { addDays } from './dates'
import { roundPrice } from './orders'
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

/** The series' last two prices as closes in its currency (a position's day return compares them), or nulls. */
export function lastCloses(series: PriceSeries): { latest: Close | null; previous: Close | null } {
  const at = (i: number): Close | null =>
    i < 0 ? null : { day: series.days[i], close: series.values[i], currency: series.currency }
  const n = series.values.length
  return { latest: at(n - 1), previous: at(n - 2) }
}

/** A held position's figures in CAD at the last close, as My Portfolio values it. */
export interface PositionFigures {
  /** Null without a CAD price (a US stock before the first exchange rate). */
  valueCad: number | null
  /** Average cost (adjusted cost base) per unit; null for a zero quantity. */
  avgCostCad: number | null
  gainCad: number | null
  /** Percent of cost; null without a value or a cost. */
  gainPct: number | null
}

/**
 * Value, average cost and P/L of `qty` units that cost `costCad` in all, at `price` in `currency`
 * (`usdCad` turns a USD price into CAD; a coin's series is already in CAD).
 */
export function positionFigures(
  qty: number,
  costCad: number,
  price: number | null,
  currency: Currency,
  usdCad: number | null,
): PositionFigures {
  const priceCad = price === null ? null : currency === 'CAD' ? price : usdCad === null ? null : price * usdCad
  const valueCad = priceCad === null ? null : qty * priceCad
  const gainCad = valueCad === null ? null : valueCad - costCad
  return {
    valueCad,
    avgCostCad: qty > 0 ? costCad / qty : null,
    gainCad,
    gainPct: gainCad === null || costCad <= 0 ? null : (gainCad / costCad) * 100,
  }
}

/** The Ticker page of an asset: a coin says so, since a coin and a stock can share a symbol. */
export const tickerHref = (symbol: string, assetType: AssetType): string =>
  `/ticker/${encodeURIComponent(symbol)}${assetType === 'crypto' ? '?asset=crypto' : ''}`

/**
 * The Ticker page's alert form, prefilled (exit plan spec §7): `tickerHref` with the level, direction
 * and note, then `#alerts`. The level is rounded as an order form takes it, so the form's 8-decimal
 * rule accepts it. Nothing is saved until the owner adds the alert.
 */
export function alertHref(
  symbol: string,
  assetType: AssetType,
  { level, direction, note }: { level: number; direction: AlertDirection; note: string },
): string {
  const base = tickerHref(symbol, assetType)
  const query = new URLSearchParams({ alertLevel: String(roundPrice(level)), alertDir: direction, alertNote: note })
  return `${base}${base.includes('?') ? '&' : '?'}${query}#alerts`
}

export interface AlertPrefill {
  level: string | null
  direction: AlertDirection | null
  note: string | null
}

/** An `alertHref` link's values, each checked by the alert form's rules; a bad or repeated one is left out. */
export function alertPrefill(
  symbol: string,
  assetType: AssetType,
  query: { [key: string]: string | string[] | undefined },
): AlertPrefill {
  const one = (key: string): string | null => (typeof query[key] === 'string' ? query[key] : null)
  const [level, direction, note] = [one('alertLevel'), one('alertDir'), one('alertNote')]
  const checked = parseAlert({ symbol, assetType, direction: direction ?? '', level: level ?? '', note: note ?? '' })
  const errors = checked.ok ? {} : checked.errors
  return {
    level: level !== null && !errors.level ? level : null,
    direction: direction === 'above' || direction === 'below' ? direction : null,
    note: note !== null && note.trim() !== '' && !errors.note ? note.trim() : null,
  }
}

/** The news stage reads two days of feeds (spec §4.2). */
export const NEWS_HOURS = 48

/**
 * Where the headline list starts: 48 hours before the run whose news counts the page shows, so the
 * list and the counts describe the same stories. Counting back from now emptied the list on a
 * weekend, when the latest run was Friday's; with no run yet, it's 48 hours before now.
 */
export function headlineSince(run: { started_at: string } | null, now: Date): string {
  const end = run ? new Date(run.started_at) : now
  return new Date(end.getTime() - NEWS_HOURS * 3_600_000).toISOString()
}

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
