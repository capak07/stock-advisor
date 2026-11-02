/**
 * Words for a forecast's explanation (Plan 4b, decisions 2 to 5): each model feature's label and
 * how its value reads, the factor bars, the hold and the round-trip cost. Feature names and scales
 * follow pipeline/src/advisor/model/features.py and fundamentals.py.
 */

import { shortDay } from './dates'
import { fmtPct } from './format'

export type Formatter = 'pct' | 'signedPct' | 'number' | 'ratio' | 'percentile' | 'smallPct' | 'dollars' | 'flag'

/** `{benchmark}` in a label is replaced by the stock's benchmark (SPY or XIU.TO). */
export const FACTORS: Record<string, { label: string; format: Formatter }> = {
  // price
  ret_5: { label: 'Return over 5 days', format: 'signedPct' },
  ret_21: { label: 'Return over 21 days', format: 'signedPct' },
  ret_63: { label: 'Return over 63 days', format: 'signedPct' },
  ret_126: { label: 'Return over 126 days', format: 'signedPct' },
  mom_12_1: { label: '12-month momentum, skipping the last month', format: 'signedPct' },
  rsi_14: { label: '14-day RSI', format: 'number' },
  atr_14_pct: { label: 'Average daily range, 14 days', format: 'pct' },
  vol_20: { label: '20-day volatility, annualised', format: 'pct' },
  vol_60: { label: '60-day volatility, annualised', format: 'pct' },
  dist_52w_high: { label: 'Distance from the 52-week high', format: 'signedPct' },
  dist_52w_low: { label: 'Distance from the 52-week low', format: 'signedPct' },
  volume_z: { label: 'Volume against its usual level', format: 'number' },
  gap: { label: 'Overnight gap', format: 'signedPct' },
  jump_5d: { label: 'Unconfirmed price jump in the last 5 days', format: 'flag' },
  log_adv20: { label: 'Average daily dollar volume, 20 days', format: 'dollars' },
  // relative strength
  ex_bench_21: { label: 'Return vs {benchmark} over 21 days', format: 'signedPct' },
  ex_bench_63: { label: 'Return vs {benchmark} over 63 days', format: 'signedPct' },
  ex_sector_21: { label: 'Return vs its sector over 21 days', format: 'signedPct' },
  ex_sector_63: { label: 'Return vs its sector over 63 days', format: 'signedPct' },
  sector_rank_63: { label: "Sector's 63-day rank", format: 'percentile' },
  // sector and liquidity
  sector_mom_12_1: { label: "Its sector's 12-month momentum, skipping the last month", format: 'signedPct' },
  sector_dist_52w_high: { label: "Its sector's distance from the 52-week high", format: 'signedPct' },
  amihud_20: { label: 'Price move per $1M traded, 20-day average', format: 'smallPct' },
  // fundamentals
  rev_growth: { label: 'Revenue growth, year over year', format: 'signedPct' },
  gross_margin: { label: 'Gross margin', format: 'pct' },
  op_margin: { label: 'Operating margin', format: 'pct' },
  gross_margin_trend: { label: 'Gross margin change over a year', format: 'signedPct' },
  op_margin_trend: { label: 'Operating margin change over a year', format: 'signedPct' },
  eps_growth: { label: 'Earnings per share growth, year over year', format: 'signedPct' },
  earnings_yield: { label: 'Earnings yield', format: 'pct' },
  sales_yield: { label: 'Sales yield', format: 'pct' },
  fcf_yield: { label: 'Free-cash-flow yield', format: 'pct' },
  debt_to_equity: { label: 'Debt to equity', format: 'ratio' },
  log_mcap: { label: 'Market value', format: 'dollars' },
}

const ordinal = (n: number): string => {
  const tens = n % 100
  if (tens >= 11 && tens <= 13) return `${n}th`
  return `${n}${({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'}`
}

const compactDollars = (value: number): string =>
  `$${value.toLocaleString('en-CA', { notation: 'compact', maximumFractionDigits: 1 })}`

/** A percentage to two significant figures, never in exponent notation: 0.0002 -> "0.020%". */
function smallPct(value: number): string {
  const pct = value * 100
  const text = pct.toPrecision(2)
  if (!text.includes('e')) return `${text}%`
  return `${pct.toFixed(Math.min(100, Math.max(0, 1 - Math.floor(Math.log10(Math.abs(pct))))))}%`
}

function formatValue(feature: string, format: Formatter, value: number): string {
  switch (format) {
    case 'pct':
      return `${(value * 100).toFixed(1)}%`
    case 'smallPct':
      return smallPct(value)
    case 'signedPct':
      return fmtPct(value * 100)
    case 'number':
      return value.toFixed(1)
    case 'ratio':
      return `${value.toFixed(2)}×`
    case 'percentile':
      return `${ordinal(Math.round(value * 100))} percentile`
    case 'dollars':
      // log_adv20 is log1p(dollar volume); log_mcap is log(market value)
      return compactDollars(feature === 'log_adv20' ? Math.expm1(value) : Math.exp(value))
    case 'flag':
      return value ? 'yes' : 'no'
  }
}

/** "Return vs SPY over 63 days +9.8%"; the label alone without a value; an unknown feature's own name. */
export function describeFactor(feature: string, value: number | undefined, benchmark: string): string {
  const known = FACTORS[feature]
  if (!known) return feature
  const label = known.label.replace('{benchmark}', benchmark)
  return value === undefined || !Number.isFinite(value) ? label : `${label} ${formatValue(feature, known.format, value)}`
}

/** Each factor's direction, and its bar width in percent: |contribution| over the largest, at most 50. */
export function factorBars(factors: readonly { feature: string; contribution: number }[]): { feature: string; up: boolean; width: number }[] {
  const largest = Math.max(0, ...factors.map((f) => Math.abs(f.contribution)))
  return factors.map((f) => ({
    feature: f.feature,
    up: f.contribution >= 0,
    width: largest > 0 ? (Math.abs(f.contribution) / largest) * 50 : 0,
  }))
}

const HOLD_WORDS: Record<number, string> = { 63: '~3 months', 126: '~6 months' }

/** "~10 trading days · exit by Oct 30", "~3 months · exit by Jan 19" */
export const holdText = (horizon: number, exitBy: string): string =>
  `${HOLD_WORDS[horizon] ?? `~${horizon} trading days`} · exit by ${shortDay(exitBy)}`

/** "3.1% round trip · USD conversion 1.5% each way + spread"; a TSX stock pays only the spread. */
export const costText = (market: 'US' | 'TSX', cost: number, usdFxFeePct: number): string =>
  `${(cost * 100).toFixed(1)}% round trip · ${market === 'US' ? `USD conversion ${usdFxFeePct}% each way + spread` : 'spread'}`

export const tfsaNote = (style: 'swing' | 'position'): string =>
  style === 'swing' ? 'Adds 1 to your TFSA round-trip count' : 'A long hold keeps TFSA trades low'

/** A catalyst as stage 8 stores it: an event inside the hold, or an 8-K from the last 3 days. */
export interface CatalystEvent {
  type: string
  date: string
  exact?: boolean
  items?: string[]
}

/** "Earnings Oct 28, inside the hold", "Phase 2/3 trial completion around Nov 3, inside the hold", "8-K Oct 15" */
export function catalystText(c: CatalystEvent): string {
  const day = shortDay(c.date)
  if (c.type === 'earnings') return `Earnings ${day}, inside the hold`
  if (c.type === 'trial_completion') return `Phase 2/3 trial completion ${c.exact === false ? 'around ' : ''}${day}, inside the hold`
  return `${c.type} ${day}`
}

export const catalystsLine = (catalysts: readonly CatalystEvent[]): string =>
  catalysts.length === 0 ? 'No catalysts inside the hold' : catalysts.map(catalystText).join(' · ')
