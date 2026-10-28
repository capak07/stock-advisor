/**
 * The short "why" beside a watchlist verdict (spec §6.5), on Today's Picks and the Watchlist.
 * A Buy's details are its pick's (style, horizon_days, exit_by, rank when picked); its P(beat)
 * is in the first reason, "P(beat SPY) 0.64 over 10 trading days" (pipeline recommend/verdicts.py).
 */

import { holdText } from './advice'

export type Verdict = 'buy' | 'hold' | 'avoid'

export interface VerdictLike {
  verdict: Verdict
  market: 'US' | 'TSX' | null
  reasons: readonly string[]
  details: Record<string, unknown>
}

export const VERDICT_LABEL: Record<Verdict, string> = { buy: 'Buy', hold: 'Hold', avoid: 'Avoid' }

const P_BEAT = /^P\(beat (\S+)\) (\d*\.?\d+)/

const int = (value: unknown): number | null => (typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : null)

/**
 * Long, for the Watchlist: "Swing · hold ~10 trading days · exit by Oct 30 · 64% to beat SPY · also today's #1 US pick".
 * Short, for the picks sidebar: "Swing · ~10 trading days · exit by Oct 30 · 64%".
 * A Hold or Avoid gives its reasons, and says when its market's picks are off this run.
 */
export function verdictWhy(v: VerdictLike, form: 'long' | 'short'): string {
  const d = v.details
  const horizon = int(d.horizon_days) ?? int(d.horizon)
  const style = d.style === 'swing' ? 'Swing' : d.style === 'position' ? 'Position' : null
  const exitBy = typeof d.exit_by === 'string' ? d.exit_by : null
  const odds = P_BEAT.exec(v.reasons[0] ?? '')
  if (v.verdict === 'buy' && style && horizon && exitBy && odds) {
    const p = `${Math.round(Number(odds[2]) * 100)}%`
    if (form === 'short') return `${style} · ${holdText(horizon, exitBy)} · ${p}`
    const rank = int(d.rank)
    const extra = rank !== null && v.market ? ` · also today's #${rank} ${v.market} pick` : d.held === true ? ' · you hold it' : ''
    return `${style} · hold ${holdText(horizon, exitBy)} · ${p} to beat ${odds[1]}${extra}`
  }
  const off = v.market && d.market_picks_enabled === false ? ` · picks off for ${v.market} this run` : ''
  return `${v.reasons.join('; ')}${off}`
}
