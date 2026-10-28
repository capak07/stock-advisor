import { shortDay } from '../dates'
import type { Account, AssetType } from './types'

export type ActionKind = 'sell' | 'trim' | 'add' | 'hold'
export type RiskLevel = 'low' | 'medium' | 'high' | 'very_high'

export const ACTION_LABELS: Record<ActionKind, string> = { sell: 'Sell', trim: 'Trim', add: 'Add', hold: 'Hold' }
export const RISK_LEVELS: readonly RiskLevel[] = ['low', 'medium', 'high', 'very_high']
export const RISK_LABELS: Record<RiskLevel, string> = { low: 'Low', medium: 'Medium', high: 'High', very_high: 'Very high' }

/** One holding's action from a run (`holding_actions`, spec §7.3). */
export interface HoldingAction {
  account: Account
  symbol: string
  assetType: AssetType
  action: ActionKind
  review: boolean
  /** The first is the headline sentence; Review reasons come last. */
  reasons: string[]
  warnings: string[]
  /** In the asset's own currency: USD for US stocks and coins, CAD for TSX. */
  trailingStop: number | null
  /** The likely range over the horizon, as fractions (0.031 is +3.1%). Coins have none. */
  q10: number | null
  q50: number | null
  q90: number | null
  horizonDays: number | null
  exitBy: string | null
  riskLevel: RiskLevel | null
  /** The close the action was decided on, in the asset's own currency (coins: Coinbase USD). */
  refPrice: number | null
  /** For order guidance (lib/orders.ts): the 14-day daily range as a fraction, and 20-day dollar volume. */
  atrPct: number | null
  dollarVolume20: number | null
  /** The trailing stop of the previous published run with actions, to say when to raise the stop order. */
  previousStop: number | null
}

/** The Actions card's groups, in the order they show. */
export type ActionGroup = 'sell' | 'trim' | 'review' | 'add'
const GROUP_ORDER: readonly ActionGroup[] = ['sell', 'trim', 'review', 'add']

/** A Hold or Add with a review flag is a Review card; a Sell or Trim keeps its own group. */
export const actionGroup = (a: HoldingAction): ActionGroup | null =>
  a.action === 'sell' || a.action === 'trim' ? a.action : a.review ? 'review' : a.action === 'add' ? 'add' : null

/** Cards in Sell → Trim → Review → Add order, by symbol within a group; the plain Holds apart. */
export function actionGroups(actions: readonly HoldingAction[]): { cards: HoldingAction[]; hold: HoldingAction[] } {
  const bySymbol = (a: HoldingAction, b: HoldingAction) => a.symbol.localeCompare(b.symbol) || a.account.localeCompare(b.account)
  const rank = (a: HoldingAction) => GROUP_ORDER.indexOf(actionGroup(a) as ActionGroup)
  return {
    cards: actions.filter((a) => actionGroup(a) !== null).sort((a, b) => rank(a) - rank(b) || bySymbol(a, b)),
    hold: actions.filter((a) => actionGroup(a) === null).sort(bySymbol),
  }
}

/** The pipeline's reasons are lowercase fragments; a card shows one as a sentence. */
const sentence = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1)

/**
 * The sentence on an action card. A Review card gives its review reasons, which follow the
 * headline; the other cards give the headline.
 */
export function cardReason(a: HoldingAction): string {
  const review = actionGroup(a) === 'review' ? a.reasons.slice(1).join('; ') : ''
  return sentence(review || (a.reasons[0] ?? ''))
}

/** A plain Hold's line: how long to hold and when to exit, or its reason without a horizon (coins). */
export const holdText = (a: HoldingAction): string =>
  a.horizonDays !== null && a.exitBy !== null
    ? `hold ~${a.horizonDays} days · exit by ${shortDay(a.exitBy)}`
    : sentence(a.reasons[0] ?? '')
