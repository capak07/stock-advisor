import { P_MIN, roundTripCost, type Candidate, type ForecastRow } from './allocate'

/** How many stocks each hold shows. */
export const WATCH_PER_HOLD = 5

/** The stock model's horizons (trading days), shortest first, as hold lengths. */
const WATCH_HOLDS: readonly { label: string; horizons: readonly number[] }[] = [
  { label: '~1 week', horizons: [5] },
  { label: '~2 weeks', horizons: [10] },
  { label: '~1 month', horizons: [20, 21] },
  { label: '~3 months', horizons: [63] },
  { label: '~6 months', horizons: [126] },
]

export interface WatchLine extends ForecastRow {
  symbol: string
  name: string | null
  market: Candidate['market']
  /** Whether the middle forecast is above the cost of buying and selling it. */
  coversCosts: boolean
  /** Whether it meets the picks' rule: the chance bar and the costs. */
  passes: boolean
}

export interface WatchGroup {
  label: string
  lines: WatchLine[]
}

/** The middle forecast against the width of its range, as the picks rank it; a range of no width ranks last. */
const ratio = (r: ForecastRow): number => {
  const width = r.q90 - r.q10
  return width > 0 ? r.q50 / width : Number.NEGATIVE_INFINITY
}

const better = (a: ForecastRow, b: ForecastRow): number => b.pBeat - a.pBeat || ratio(b) - ratio(a)

/**
 * The Invest page's watch list (owner request 2026-11-23): the model's best-ranked stocks, grouped by how long to hold,
 * for research only. Each stock shows once, under the hold it is rated best at; a group ranks by the chance of beating
 * the benchmark, then by the middle forecast against the range's width. Stocks already held and stocks with an
 * earnings-size jump in the last 5 days are left out, as the picks leave them out.
 */
export function watchList(candidates: readonly Candidate[], held: ReadonlySet<string>, usdFxFeePct: number): WatchGroup[] {
  const groups = WATCH_HOLDS.map((hold) => ({ ...hold, lines: [] as WatchLine[] }))
  for (const c of candidates) {
    if (c.assetType !== 'stock' || c.market === null || held.has(c.symbol) || c.jump5d !== 0) continue
    const best = [...c.rows].sort(better)[0]
    const group = best && groups.find((g) => g.horizons.includes(best.horizonDays))
    if (!group) continue
    const coversCosts = best.q50 > roundTripCost(c.market, c.dollarVolume20, usdFxFeePct)
    group.lines.push({ ...best, symbol: c.symbol, name: c.name, market: c.market, coversCosts, passes: coversCosts && best.pBeat >= P_MIN })
  }
  return groups
    .map(({ label, lines }) => ({
      label,
      lines: lines.sort((a, b) => better(a, b) || a.symbol.localeCompare(b.symbol)).slice(0, WATCH_PER_HOLD),
    }))
    .filter((g) => g.lines.length > 0)
}
