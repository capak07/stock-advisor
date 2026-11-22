/**
 * A forecast's outlook in words (spec §7.6, §7.7): the horizon to show, and the verdict as plain
 * words, so a weak forecast reads "No clear edge" with its chance as a number, never as a call.
 */

import type { ForecastHorizon } from './data/ticker'

/** The horizon closest to `target` (21 days by default); a tie goes to the shorter. Null without horizons. */
export function nearestHorizon(horizons: readonly number[], target = 21): number | null {
  let best: number | null = null
  for (const h of horizons) {
    if (best === null) best = h
    else {
      const d = Math.abs(h - target)
      const bestD = Math.abs(best - target)
      if (d < bestD || (d === bestD && h < best)) best = h
    }
  }
  return best
}

/** The forecast at `horizon` (a verdict's), else at the horizon closest to 21 days; null without rows. */
export function outlookFor(rows: readonly ForecastHorizon[], horizon: number | null): ForecastHorizon | null {
  const exact = horizon === null ? undefined : rows.find((r) => r.horizon === horizon)
  if (exact) return exact
  const nearest = nearestHorizon(rows.map((r) => r.horizon))
  return rows.find((r) => r.horizon === nearest) ?? null
}

/** A verdict in words: Buy, Avoid, or "No clear edge" for a Hold or no verdict at all. */
export function edgeWords(verdict: 'buy' | 'hold' | 'avoid' | null): string {
  if (verdict === 'buy') return 'Buy'
  if (verdict === 'avoid') return 'Avoid'
  return 'No clear edge'
}
