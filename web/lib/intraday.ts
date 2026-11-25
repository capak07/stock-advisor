/**
 * The 1D charts (owner request 2026-11-23): a session's 5-minute prices from Yahoo's chart endpoint, keyless, fetched
 * when the 1D tab is picked. A stock is charted on its regular session, 9:30 to 4:00 New York time, against the
 * previous close; a coin on its UTC day in CAD (Yahoo's `BTC-CAD`), as Wealthsimple trades it. The portfolio's day is
 * every holding valued at each 5 minutes, as a percent of what the holdings were worth at the previous close.
 */

import { getJson, listedAs, type Fetch } from './quotes'
import { assetKey, type AssetType, type Currency } from './portfolio/types'

export const BAR_SECONDS = 300

/** One asset's session: each 5-minute bar's start (epoch seconds) and close. */
export interface Intraday {
  times: number[]
  closes: number[]
  previousClose: number
  currency: Currency
  /** The session's start and end (epoch seconds): its 5-minute slots set how wide the day's chart is. */
  start: number
  end: number
}

/** A day to chart: the values so far, the line they're measured against and how many slots the whole session has. */
export interface DayChart {
  /** Each point's time in Toronto, "10:35 a.m.". */
  labels: string[]
  values: number[]
  /** The previous close, or 0 for a percent. */
  base: number
  slots: number
  /** The session's day in Toronto (`YYYY-MM-DD`). */
  day: string
}

/** Yahoo's chart endpoint; the browser tests point it at a stub (e2e/yahoo-stub.mjs). */
export const chartBase = () => process.env.YAHOO_CHART_URL ?? 'https://query1.finance.yahoo.com/v8/finance/chart'

export const intradayUrl = (yahooSymbol: string): string =>
  `${chartBase()}/${encodeURIComponent(yahooSymbol)}?range=1d&interval=5m`

/** A stock under its own symbol; a coin as its CAD pair. */
export const yahooSymbolOf = (symbol: string, assetType: AssetType): string =>
  assetType === 'crypto' ? `${listedAs(symbol)}-CAD` : symbol

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** The session's bars from a Yahoo chart response, or null without a previous close, a session or a single bar. */
export function parseIntraday(body: unknown): Intraday | null {
  const result = (body as { chart?: { result?: Record<string, unknown>[] | null } })?.chart?.result?.[0]
  const meta = result?.meta as Record<string, unknown> | undefined
  if (!result || !meta) return null
  const previousClose = meta.chartPreviousClose ?? meta.previousClose
  const currency = meta.currency
  type Period = { start?: unknown; end?: unknown }
  const period =
    (meta.tradingPeriods as Period[][] | undefined)?.[0]?.[0] ??
    (meta.currentTradingPeriod as { regular?: Period } | undefined)?.regular
  if (!finite(previousClose) || previousClose <= 0 || (currency !== 'USD' && currency !== 'CAD')) return null
  const start = period?.start
  const end = period?.end
  if (!finite(start) || !finite(end) || end <= start) return null
  const stamps = (result.timestamp as unknown[] | undefined) ?? []
  const quote = (result.indicators as { quote?: { close?: unknown[] }[] } | undefined)?.quote?.[0]?.close ?? []
  const times: number[] = []
  const closes: number[] = []
  stamps.forEach((t, i) => {
    const close = quote[i]
    // a 5 minutes without trades has no close; the line carries on from the last one
    if (finite(t) && finite(close) && close > 0 && t >= start && t <= end) {
      times.push(t)
      closes.push(close)
    }
  })
  if (times.length === 0) return null
  return { times, closes, previousClose, currency, start, end }
}

const clock = new Intl.DateTimeFormat('en-CA', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Toronto' })
const calendar = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Toronto' })
const label = (t: number) => clock.format(new Date(t * 1000))
const slotsOf = (d: Intraday) => Math.floor((d.end - d.start) / BAR_SECONDS) + 1

/** One asset's day: its price at each bar against the previous close. */
export function priceDay(d: Intraday): DayChart {
  return {
    labels: d.times.map(label),
    values: d.closes,
    base: d.previousClose,
    slots: slotsOf(d),
    day: calendar.format(new Date(d.times.at(-1)! * 1000)),
  }
}

/** The close at or before `t`: the last bar that started by then, else the previous close. */
function closeAt(d: Intraday, t: number): number {
  let price = d.previousClose
  for (let i = 0; i < d.times.length && d.times[i] <= t; i += 1) price = d.closes[i]
  return price
}

export interface DayHolding {
  qty: number
  /** CAD per unit of the asset's currency. */
  toCad: number
  day: Intraday
}

/**
 * The portfolio's day, in percent: the holdings' value every 5 minutes of the latest session against their value at
 * the previous close. A holding whose market didn't trade in that session (a holiday on one exchange, or a stock on a
 * weekend while coins trade) counts at its last price both ways, so it moves nothing. Null without holdings.
 */
export function portfolioDay(holdings: readonly DayHolding[]): DayChart | null {
  if (holdings.length === 0) return null
  const grid = holdings.map((h) => h.day).reduce((a, b) => (b.start > a.start ? b : a))
  const live = (h: DayHolding) => h.day.times.some((t) => t >= grid.start && t <= grid.end)
  const lastBar = Math.max(...holdings.filter(live).flatMap((h) => h.day.times.filter((t) => t <= grid.end)))
  const base = holdings.reduce((sum, h) => sum + h.qty * h.toCad * (live(h) ? h.day.previousClose : h.day.closes.at(-1)!), 0)
  if (base <= 0) return null
  const times: number[] = []
  for (let t = grid.start; t <= lastBar; t += BAR_SECONDS) times.push(t)
  const values = times.map((t) => {
    const value = holdings.reduce((sum, h) => sum + h.qty * h.toCad * (live(h) ? closeAt(h.day, t) : h.day.closes.at(-1)!), 0)
    return (value / base - 1) * 100
  })
  return { labels: times.map(label), values, base: 0, slots: slotsOf(grid), day: calendar.format(new Date(lastBar * 1000)) }
}

/** Each asset's session by `assetKey`; one that doesn't answer is left out. Never throws. */
export async function fetchIntraday(
  assets: readonly { symbol: string; assetType: AssetType }[],
  fetchImpl: Fetch = fetch,
): Promise<Map<string, Intraday>> {
  const unique = [...new Map(assets.map((a) => [assetKey(a.assetType, a.symbol), a])).entries()]
  const rows = await Promise.all(
    unique.map(async ([key, a]) => {
      const body = await getJson(fetchImpl, intradayUrl(yahooSymbolOf(a.symbol, a.assetType)), {
        headers: { 'User-Agent': 'Mozilla/5.0 (stock-advisor)' },
      })
      return [key, parseIntraday(body)] as const
    }),
  )
  return new Map(rows.filter((r): r is readonly [string, Intraday] => r[1] !== null))
}
