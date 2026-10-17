import { QTY_EPSILON, inOrder, tradeCad } from './ledger'
import type { FxRates, PriceBook } from './lookup'
import { assetKey } from './types'
import type { Trade } from './types'

export const BENCHMARKS = { xiu: assetKey('stock', 'XIU.TO'), spy: assetKey('stock', 'SPY') } as const

/**
 * Growth of 1 C$ over the trading days since the first buy: the portfolio's, and XIU.TO's and
 * SPY's in CAD. A benchmark is null when it has no close on the first day.
 */
export interface Growth {
  days: string[]
  portfolio: number[]
  xiu: number[] | null
  spy: number[] | null
}

/** The days to measure on: the benchmarks' trading days, else the held assets', from the first buy on. */
function tradingDays(trades: readonly Trade[], prices: PriceBook, start: string): string[] {
  const pick = (keys: string[]) =>
    [...new Set(keys.flatMap((key) => prices.days(key)))].filter((day) => day >= start).sort()
  const benchmarkDays = pick([BENCHMARKS.xiu, BENCHMARKS.spy])
  if (benchmarkDays.length > 0) return benchmarkDays
  return pick([...new Set(trades.map((t) => assetKey(t.assetType, t.symbol)))])
}

/**
 * Time-weighted growth, so buys and sells don't count as gains or losses. Each day's return is
 * (value at the close + sell proceeds) / (yesterday's value + buy cost) − 1: buys put money in
 * before the close, sells take it out after. Trades on days without a close (a coin bought on a
 * Saturday) count on the next trading day. An asset without a close yet is valued at cost.
 */
export function growth(trades: readonly Trade[], prices: PriceBook, fx: FxRates): Growth | null {
  const ordered = inOrder(trades)
  if (ordered.length === 0) return null
  const days = tradingDays(ordered, prices, ordered[0].day)
  if (days.length === 0) return null

  const held = new Map<string, { qty: number; costCad: number }>()
  const portfolio: number[] = []
  let next = 0
  let lastValue = 0
  let index = 1
  for (const day of days) {
    let bought = 0
    let sold = 0
    for (; next < ordered.length && ordered[next].day <= day; next += 1) {
      const trade = ordered[next]
      const cad = tradeCad(trade, fx)
      if (cad === null) continue
      const key = assetKey(trade.assetType, trade.symbol)
      const asset = held.get(key) ?? { qty: 0, costCad: 0 }
      if (trade.side === 'buy') {
        asset.qty += trade.qty
        asset.costCad += cad
        bought += cad
      } else if (asset.qty > QTY_EPSILON) {
        const qty = Math.min(trade.qty, asset.qty)
        asset.costCad -= (asset.costCad * qty) / asset.qty
        asset.qty -= qty
        sold += (cad * qty) / trade.qty
      }
      held.set(key, asset)
    }
    let value = 0
    for (const [key, asset] of held) {
      if (asset.qty <= QTY_EPSILON) continue
      const close = prices.on(key, day)
      const cad = close === null ? null : fx.toCad(close, day)
      value += cad === null ? asset.costCad : asset.qty * cad
    }
    const invested = lastValue + bought
    index *= invested > 0 ? (value + sold) / invested : 1
    portfolio.push(index)
    lastValue = value
  }

  const benchmark = (key: string): number[] | null => {
    const inCad = days.map((day) => {
      const close = prices.on(key, day)
      return close === null ? null : fx.toCad(close, day)
    })
    const first = inCad[0]
    if (first === null || first === undefined) return null
    let last = first
    return inCad.map((v) => {
      last = v ?? last
      return last / first
    })
  }
  return { days, portfolio, xiu: benchmark(BENCHMARKS.xiu), spy: benchmark(BENCHMARKS.spy) }
}

export type Period = '1m' | '3m' | '12m' | 'all'
export const PERIODS: readonly Period[] = ['1m', '3m', '12m', 'all']
const TRADING_DAYS: Record<Exclude<Period, 'all'>, number> = { '1m': 21, '3m': 63, '12m': 252 }

/** A period's returns in percent, each line starting at 0 (the portfolio's "all" starts at cost). */
export interface PeriodReturns {
  days: string[]
  portfolio: number[]
  xiu: number[] | null
  spy: number[] | null
}

export function periodReturns(g: Growth, period: Period): PeriodReturns {
  const start = period === 'all' ? 0 : Math.max(0, g.days.length - 1 - TRADING_DAYS[period])
  const pct = (values: number[], base: number) => values.slice(start).map((v) => (v / base - 1) * 100)
  return {
    days: g.days.slice(start),
    // Over the whole history the portfolio is measured from what was paid, so the first day's
    // move from the buy price to the close counts; benchmarks start at their first close.
    portfolio: pct(g.portfolio, period === 'all' ? 1 : g.portfolio[start]),
    xiu: g.xiu && pct(g.xiu, g.xiu[start]),
    spy: g.spy && pct(g.spy, g.spy[start]),
  }
}
