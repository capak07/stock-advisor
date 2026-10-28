/**
 * The Invest page's split of an amount (docs/superpowers/specs/2026-10-27-invest-page-design.md):
 * up to five stocks ranked by the picks' own rule, weighted by 1 / volatility, and a crypto share
 * for BTC. The qualify, ratio and cost rules mirror pipeline/src/advisor/recommend/picks.py and
 * advisor.model.backtest.round_trip_cost; keep them the same.
 */

import type { Market } from '../portfolio/types'

export const P_MIN = 0.58
export const STOCKS = 5
export const PER_SECTOR = 2
export const MAX_SHARE = 0.4
const LARGE_DOLLAR_VOLUME = 10_000_000
const SPREAD_LARGE = 0.001
const SPREAD_SMALL = 0.003

/** One forecast horizon of a stock, as `predictions` stores it: fractions of excess return. */
export interface ForecastRow {
  horizonDays: number
  q10: number
  q50: number
  q90: number
  pBeat: number
  benchmark: string
}

/** A stock the run forecast, with what ranking and sizing read. */
export interface Candidate {
  symbol: string
  name: string | null
  market: Market
  sector: string | null
  rows: ForecastRow[]
  /** Annualised 60-day volatility, a fraction. */
  vol60: number | null
  /** Average daily dollar volume over 20 sessions. */
  dollarVolume20: number | null
  /** 0 when no flagged jump in the last 5 sessions; null when unknown. */
  jump5d: number | null
  /** The latest close in CAD. */
  priceCad: number | null
  /** The latest close in the stock's own currency, and that currency, for order guidance. */
  price: number | null
  currency: 'CAD' | 'USD'
  /** The 14-day daily range as a fraction, for order guidance. */
  atrPct: number | null
}

export interface InvestInput {
  amount: number
  /** Percent of the amount for BTC, 0 to 100. */
  cryptoPct: number
  /** How many stocks to split over, 1 to STOCKS (default STOCKS); 1 puts it all in the top-ranked one. */
  stocks?: number
  usdFxFeePct: number
  candidates: Candidate[]
  /** Stocks already held: they get holding actions on My Portfolio instead. */
  held: ReadonlySet<string>
  btcPriceCad: number | null
}

export type Volatility = 'low' | 'medium' | 'high' | 'very high'

export interface StockLine extends ForecastRow {
  symbol: string
  name: string | null
  market: Market
  sector: string | null
  /** Whole dollars. */
  amount: number
  /** Approximate shares at the latest price; null without a price. */
  shares: number | null
  /** Whether the chosen horizon passes the picks' bar (P >= 0.58 and q50 above cost). */
  qualifies: boolean
  /** Round-trip cost as a fraction. */
  cost: number
  vol60: number | null
  volatility: Volatility | null
  /** For order guidance (lib/orders.ts). */
  price: number | null
  currency: 'CAD' | 'USD'
  atrPct: number | null
  dollarVolume20: number | null
}

export interface Allocation {
  stocks: StockLine[]
  crypto: { symbol: 'BTC'; amount: number; priceCad: number | null; units: number | null }
  /** Money no stock is shown for: none was expected to beat its benchmark. */
  uninvested: number
  /** At least one stock shown doesn't pass the bar. */
  notValidated: boolean
  /** Two stocks, so the 40% cap couldn't hold and the money is split evenly. */
  evenSplit: boolean
}

/** Buy-and-sell cost: the spread, plus the currency fee both ways for a US stock. */
export function roundTripCost(market: Market, dollarVolume20: number | null, usdFxFeePct: number): number {
  const spread = dollarVolume20 !== null && dollarVolume20 >= LARGE_DOLLAR_VOLUME ? SPREAD_LARGE : SPREAD_SMALL
  return market === 'US' ? spread + (2 * usdFxFeePct) / 100 : spread
}

const ratio = (r: ForecastRow): number | null => {
  const width = r.q90 - r.q10
  return width > 0 ? r.q50 / width : null
}

/** The best-ratio row of those `keep` allows; a tie goes to the shorter horizon. */
function best(rows: readonly ForecastRow[], keep: (r: ForecastRow) => boolean): { row: ForecastRow; ratio: number } | null {
  let found: { row: ForecastRow; ratio: number } | null = null
  for (const r of rows) {
    const x = ratio(r)
    if (x === null || !keep(r)) continue
    if (!found || x > found.ratio || (x === found.ratio && r.horizonDays < found.row.horizonDays)) found = { row: r, ratio: x }
  }
  return found
}

/** Percentile (0-100) of each value among `all`, ties at their midpoint. */
function percentileOf(value: number, all: readonly number[]): number {
  const below = all.filter((v) => v < value).length
  const equal = all.filter((v) => v === value).length
  return (100 * (below + equal / 2)) / all.length
}

const volatilityWord = (pct: number): Volatility => (pct < 30 ? 'low' : pct < 65 ? 'medium' : pct < 90 ? 'high' : 'very high')

const median = (values: readonly number[]): number | null => {
  if (values.length === 0) return null
  const s = [...values].sort((a, b) => a - b)
  const mid = Math.floor(s.length / 2)
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2
}

/** Weights summing to 1, none above `cap`: the excess is spread over the others until none is over. */
function capped(weights: readonly number[], cap: number): number[] {
  const out = [...weights]
  const fixed = new Set<number>()
  for (;;) {
    const free = out.map((_, i) => i).filter((i) => !fixed.has(i))
    const left = 1 - fixed.size * cap
    const freeTotal = free.reduce((s, i) => s + weights[i], 0)
    for (const i of free) out[i] = (weights[i] / freeTotal) * left
    const over = free.filter((i) => out[i] > cap + 1e-12)
    if (over.length === 0) return out
    for (const i of over) {
      fixed.add(i)
      out[i] = cap
    }
  }
}

/** The stocks to show, in order: qualifying ones first, then positive forecasts to fill five. */
function choose(input: InvestInput) {
  const ranked = input.candidates.flatMap((c) => {
    if (input.held.has(c.symbol) || c.jump5d !== 0) return []
    const cost = roundTripCost(c.market, c.dollarVolume20, input.usdFxFeePct)
    const qualifying = best(c.rows, (r) => r.pBeat >= P_MIN && r.q50 > cost)
    const pick = qualifying ?? best(c.rows, (r) => r.q50 > 0)
    return pick ? [{ candidate: c, cost, row: pick.row, ratio: pick.ratio, qualifies: qualifying !== null }] : []
  })
  ranked.sort(
    (a, b) => Number(b.qualifies) - Number(a.qualifies) || b.ratio - a.ratio || a.candidate.symbol.localeCompare(b.candidate.symbol),
  )
  const limit = Math.min(STOCKS, Math.max(1, Math.trunc(input.stocks ?? STOCKS)))
  const perSector = new Map<string, number>()
  const chosen: typeof ranked = []
  for (const r of ranked) {
    if (chosen.length === limit) break
    const group = r.candidate.sector ?? `unlabelled:${r.candidate.symbol}`
    if ((perSector.get(group) ?? 0) >= PER_SECTOR) continue
    perSector.set(group, (perSector.get(group) ?? 0) + 1)
    chosen.push(r)
  }
  return chosen
}

/** Whole-dollar amounts summing exactly to the rounded parts' total; the difference goes to the largest. */
function wholeDollars(parts: readonly number[], total: number): number[] {
  const rounded = parts.map((p) => Math.round(p))
  const diff = total - rounded.reduce((s, x) => s + x, 0)
  if (diff !== 0 && rounded.length > 0) {
    const largest = rounded.indexOf(Math.max(...rounded))
    rounded[largest] += diff
  }
  return rounded
}

export function allocate(input: InvestInput): Allocation {
  const cryptoRaw = (input.amount * input.cryptoPct) / 100
  const stockMoney = input.amount - cryptoRaw
  const chosen = stockMoney > 0 ? choose(input) : []
  const evenSplit = chosen.length === 2 // one stock takes it all; three or more can hold the cap

  const fallbackVol = median(chosen.map((r) => r.candidate.vol60).filter((v): v is number => v !== null && v > 0))
  const weights = chosen.map((r) => {
    const v = r.candidate.vol60 !== null && r.candidate.vol60 > 0 ? r.candidate.vol60 : fallbackVol
    return v ? 1 / v : 1
  })
  const shares = chosen.length < 3
    ? chosen.map(() => 1 / chosen.length)
    : capped(
        weights.map((w) => w / weights.reduce((s, x) => s + x, 0)),
        MAX_SHARE,
      )

  // every line in whole dollars; the parts (stocks, crypto, uninvested) add up to the amount exactly
  const uninvestedRaw = chosen.length === 0 ? stockMoney : 0
  const lines = wholeDollars([...shares.map((s) => s * stockMoney), cryptoRaw, uninvestedRaw], input.amount)
  const cryptoAmount = lines[chosen.length]
  const uninvested = lines[chosen.length + 1]

  const allVols = input.candidates.map((c) => c.vol60).filter((v): v is number => v !== null)
  const stocks = chosen.map((r, i): StockLine => {
    const c = r.candidate
    return {
      ...r.row,
      symbol: c.symbol,
      name: c.name,
      market: c.market,
      sector: c.sector,
      amount: lines[i],
      shares: c.priceCad ? lines[i] / c.priceCad : null,
      qualifies: r.qualifies,
      cost: r.cost,
      vol60: c.vol60,
      price: c.price,
      currency: c.currency,
      atrPct: c.atrPct,
      dollarVolume20: c.dollarVolume20,
      volatility: c.vol60 !== null && allVols.length > 0 ? volatilityWord(percentileOf(c.vol60, allVols)) : null,
    }
  })

  return {
    stocks,
    crypto: {
      symbol: 'BTC',
      amount: cryptoAmount,
      priceCad: input.btcPriceCad,
      units: input.btcPriceCad ? cryptoAmount / input.btcPriceCad : null,
    },
    uninvested,
    notValidated: stocks.some((l) => !l.qualifies),
    evenSplit,
  }
}
