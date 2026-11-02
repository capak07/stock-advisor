/**
 * The short "why" beside a watchlist verdict (spec §6.5), on Today's Picks and the Watchlist.
 * A Buy's details are its pick's (style, horizon_days, exit_by, rank when picked); its P(beat)
 * is in the first reason, "P(beat SPY) 0.64 over 10 trading days" (pipeline recommend/verdicts.py).
 */

import { holdText } from './advice'
import { ACTION_LABELS, actionGroup, cardReason, type HoldingAction, holdText as holdingHoldText } from './portfolio/actions'
import { assetKey } from './portfolio/types'

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
    const note = form === 'long' && v.reasons.length > 2 ? ` · ${v.reasons.slice(2).join('; ')}` : ''
    return `${style} · hold ${holdText(horizon, exitBy)} · ${p} to beat ${odds[1]}${extra}${note}`
  }
  const off = v.market && d.market_picks_enabled === false ? ` · picks off for ${v.market} this run` : ''
  return `${v.reasons.join('; ')}${off}`
}

/** What a held symbol's call reads from a run's `holding_actions`. */
export type HeldActionLike = Pick<
  HoldingAction,
  'account' | 'symbol' | 'assetType' | 'action' | 'review' | 'reasons' | 'horizonDays' | 'exitBy'
>

/** My Portfolio's group: a Hold or Add with a review flag is Review there. */
export type HeldGroup = 'sell' | 'trim' | 'review' | 'add' | 'hold'

/** A held symbol's call on the Watchlist and the Picks sidebar: My Portfolio's action, not a buy verdict. */
export interface HeldCall {
  group: HeldGroup
  label: string
  why: string
}

const URGENCY: readonly HeldGroup[] = ['sell', 'trim', 'review', 'add', 'hold']

/**
 * Each held symbol's call by asset key, so a watched symbol you hold says what My Portfolio says.
 * Held in several accounts, it takes the most urgent action (Sell, Trim, Review, Add, Hold) and says
 * when the other accounts' actions differ.
 */
export function heldCalls(actions: readonly HeldActionLike[]): Map<string, HeldCall> {
  const found = new Map<string, { call: HeldCall; groups: Set<HeldGroup> }>()
  for (const a of actions) {
    const group: HeldGroup = actionGroup(a) ?? 'hold'
    const call = {
      group,
      label: group === 'review' ? 'Review' : ACTION_LABELS[a.action],
      why: group === 'hold' ? holdingHoldText(a) : cardReason(a),
    }
    const key = assetKey(a.assetType, a.symbol)
    const seen = found.get(key)
    if (!seen) found.set(key, { call, groups: new Set([group]) })
    else {
      seen.groups.add(group)
      if (URGENCY.indexOf(group) < URGENCY.indexOf(seen.call.group)) seen.call = call
    }
  }
  return new Map(
    [...found].map(([key, { call, groups }]) => [
      key,
      { ...call, why: `You hold it · ${call.why}${groups.size > 1 ? ' · other accounts differ, see Portfolio' : ''}` },
    ]),
  )
}
