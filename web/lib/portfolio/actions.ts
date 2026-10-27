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
