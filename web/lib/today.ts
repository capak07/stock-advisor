/**
 * Today's pure parts (spec §7.1): what needs the owner's attention, the header's date and market
 * state, and the best chance of beating the market in the latest run.
 */
import { isLive, type DayRow } from './daytrade'
import { P_MIN } from './invest/allocate'
import { actionGroup, type ActionGroup } from './portfolio/actions'
import type { HoldingRow } from './portfolio/view'

/** The picks' bar: a pick needs P(beat) at least this (the Invest page mirrors the same rule). */
export const PICK_P_FLOOR = P_MIN

const ORDER: readonly ActionGroup[] = ['sell', 'trim', 'review', 'add']

/**
 * The holdings whose latest action is Sell, Trim, Review (a Hold or Add flagged for review) or Add,
 * in that order and by symbol within a group; `onHold` counts the plain Holds. A holding without an
 * action (bought after the run) is in neither.
 */
export function needsAttention(holdings: readonly HoldingRow[]): { items: HoldingRow[]; onHold: number } {
  const rank = (h: HoldingRow) => (h.action === null ? -1 : ORDER.indexOf(actionGroup(h.action) as ActionGroup))
  const items = holdings
    .filter((h) => h.action !== null && actionGroup(h.action) !== null)
    .sort((a, b) => rank(a) - rank(b) || a.symbol.localeCompare(b.symbol) || a.account.localeCompare(b.account))
  const onHold = holdings.filter((h) => h.action !== null && actionGroup(h.action) === null).length
  return { items, onHold }
}

const NY_DAY = new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'short', day: 'numeric', timeZone: 'America/New_York' })

/**
 * "Saturday, Nov 21 · markets closed": New York's date, and "market open" only while today's
 * day-trade session row exists and is live. The day-trade job decides, so a holiday reads closed.
 */
export function todayLine(day: DayRow | null, now: string): string {
  const open = day !== null && isLive(day, now)
  return `${NY_DAY.format(new Date(now))} · ${open ? 'market open' : 'markets closed'}`
}

/** The best P(beat) among a run's stock predictions against one market's benchmark. */
export type BestChance = { benchmark: 'SPY' | 'XIU.TO'; pBeat: number }

const MARKET_OF: Record<BestChance['benchmark'], string> = { SPY: 'US', 'XIU.TO': 'TSX' }

/** "US 52.7% vs SPY · TSX 55.1% vs XIU.TO", US first; null when the run has none. */
export function bestChanceLine(chances: readonly BestChance[]): string | null {
  if (chances.length === 0) return null
  return [...chances]
    .sort((a, b) => (a.benchmark === 'SPY' ? 0 : 1) - (b.benchmark === 'SPY' ? 0 : 1))
    .map((c) => `${MARKET_OF[c.benchmark]} ${(c.pBeat * 100).toFixed(1)}% vs ${c.benchmark}`)
    .join(' · ')
}
