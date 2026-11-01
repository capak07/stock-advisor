/**
 * The Invest page's split of an amount (docs/superpowers/specs/2026-10-27-invest-page-design.md):
 * up to five names of one kind, stocks or coins, ranked by the picks' own rule and weighted by
 * 1 / volatility. The qualify, ratio and cost rules mirror pipeline/src/advisor/recommend/picks.py
 * and advisor.model.backtest.round_trip_cost; keep them the same.
 */

import type { Market } from '../portfolio/types'

export const P_MIN = 0.58
export const STOCKS = 5
export const PER_SECTOR = 2
export const MAX_SHARE = 0.4
/**
 * How long the owner wants to hold (owner decision 2026-10-28): each choice ranks stocks only on the
 * forecast horizons it names, so the hold time shown is the one asked for. The model forecasts 5,
 * 10, 20, 21, 63 and 126 trading days, and only its usable ones.
 */
export const HOLDS = [
  { value: 'any', label: 'Any', horizons: null },
  { value: '21', label: '~1 month', horizons: [20, 21] },
  { value: '63', label: '~3 months', horizons: [63] },
  { value: '126', label: '~6 months', horizons: [126] },
] as const satisfies readonly { value: string; label: string; horizons: readonly number[] | null }[]

/** A coin's horizons are calendar days (the crypto model forecasts 7, 14 and 30). */
export const CRYPTO_HOLDS = [
  { value: 'any', label: 'Any', horizons: null },
  { value: '7', label: '~1 week', horizons: [7] },
  { value: '14', label: '~2 weeks', horizons: [14] },
  { value: '30', label: '~1 month', horizons: [30] },
] as const satisfies readonly { value: string; label: string; horizons: readonly number[] | null }[]

export type Hold = (typeof HOLDS)[number]['value'] | (typeof CRYPTO_HOLDS)[number]['value']

const LARGE_DOLLAR_VOLUME = 10_000_000
const SPREAD_LARGE = 0.001
const SPREAD_SMALL = 0.003

/** One forecast horizon, as `predictions` stores it: fractions of excess return. */
export interface ForecastRow {
  horizonDays: number
  q10: number
  q50: number
  q90: number
  pBeat: number
  benchmark: string
}

/** A stock or coin the run forecast, with what ranking and sizing read. */
export interface Candidate {
  symbol: string
  name: string | null
  assetType: 'stock' | 'crypto'
  /** Null for a coin. */
  market: Market | null
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
  /** How many names to split over, 1 to STOCKS (default STOCKS); 1 puts it all in the top-ranked one. */
  stocks?: number
  /** The forecast horizons to rank on (a HOLDS or CRYPTO_HOLDS entry's); null or absent for any. */
  horizons?: readonly number[] | null
  usdFxFeePct: number
  /** The crypto fee, in percent, added both ways. Used only for coins. */
  cryptoFeePct: number
  candidates: Candidate[]
  /** Names already held: they get holding actions on My Portfolio instead. */
  held: ReadonlySet<string>
}

export type Volatility = 'low' | 'medium' | 'high' | 'very high'

export interface StockLine extends ForecastRow {
  symbol: string
  name: string | null
  assetType: 'stock' | 'crypto'
  market: Market | null
  sector: string | null
  /** Whole dollars. */
  amount: number
  /** Approximate shares, or coin units, at the latest CAD price; null without a price. */
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
  /** Money no name is shown for: none was expected to beat its benchmark. */
  uninvested: number
  /** At least one name shown doesn't pass the bar. */
  notValidated: boolean
  /** Two names, so the 40% cap couldn't hold and the money is split evenly. */
  evenSplit: boolean
}

/** Buy-and-sell cost: the spread, plus a fee both ways for a US stock or a coin. */
export function roundTripCost(market: Market | 'crypto', dollarVolume20: number | null, feePct: number): number {
  const spread = dollarVolume20 !== null && dollarVolume20 >= LARGE_DOLLAR_VOLUME ? SPREAD_LARGE : SPREAD_SMALL
  return market === 'TSX' ? spread : spread + (2 * feePct) / 100
}

const ratio = (r: ForecastRow): number | null => {
  const width = r.q90 - r.q10
  return width > 0 ? r.q50 / width : null
}

/** The best-ratio horizon the hold allows. Null when this hold names horizons the rows don't have. */
export function forecastForHold(rows: readonly ForecastRow[], horizons: readonly number[] | null): ForecastRow | null {
  const allowed = horizons ? rows.filter((r) => horizons.includes(r.horizonDays)) : rows
  return best(allowed, () => true)?.row ?? null
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
    const venue = c.assetType === 'crypto' ? 'crypto' : c.market
    if (venue === null) return []
    const cost = roundTripCost(venue, c.dollarVolume20, c.assetType === 'crypto' ? input.cryptoFeePct : input.usdFxFeePct)
    const allowed = input.horizons
    const rows = allowed ? c.rows.filter((r) => allowed.includes(r.horizonDays)) : c.rows
    const qualifying = best(rows, (r) => r.pBeat >= P_MIN && r.q50 > cost)
    const pick = qualifying ?? best(rows, (r) => r.q50 > 0)
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

/**
 * Whole-dollar amounts that never go below zero and add up to the whole dollars of `total`: each
 * part rounds down, then the dollars left go one each to the parts with the largest fractions (the
 * earlier part on a tie). The last part is the uninvested line, which also takes the cents.
 */
function wholeDollars(parts: readonly number[], total: number): number[] {
  const EPS = 1e-9 // 333.9999999 from a float split is 334
  const floors = parts.map((p) => Math.floor(p + EPS))
  let left = Math.floor(total + EPS) - floors.reduce((s, x) => s + x, 0)
  const byFraction = parts.map((p, i) => i).sort((a, b) => (parts[b] - floors[b]) - (parts[a] - floors[a]) || a - b)
  for (const i of byFraction) {
    if (left <= 0) break
    floors[i] += 1
    left -= 1
  }
  if (floors.length > 0) floors[floors.length - 1] += total - Math.floor(total + EPS) // the cents
  return floors
}

export function allocate(input: InvestInput): Allocation {
  const chosen = choose(input)
  const evenSplit = chosen.length === 2 // one name takes it all; three or more can hold the cap

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

  // every line in whole dollars; the parts add up to the amount exactly
  const uninvestedRaw = chosen.length === 0 ? input.amount : 0
  const lines = wholeDollars([...shares.map((s) => s * input.amount), uninvestedRaw], input.amount)
  const uninvested = lines[chosen.length]

  const allVols = input.candidates.map((c) => c.vol60).filter((v): v is number => v !== null)
  const stocks = chosen.map((r, i): StockLine => {
    const c = r.candidate
    return {
      ...r.row,
      symbol: c.symbol,
      name: c.name,
      assetType: c.assetType,
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
    uninvested,
    notValidated: stocks.some((l) => !l.qualifies),
    evenSplit,
  }
}
