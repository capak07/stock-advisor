import 'server-only'
import type { ActionKind, HoldingAction, RiskLevel } from '../portfolio/actions'
import type { Account, AssetType } from '../portfolio/types'
import type { Supabase } from '../supabase/server'
import { fetchAll, must } from './fetch'

interface ActionRow {
  account: Account
  symbol: string
  asset_type: AssetType
  action: ActionKind
  review: boolean
  reasons: string[]
  warnings: string[]
  trailing_stop: string | number | null
  q10: number | null
  q50: number | null
  q90: number | null
  horizon_days: number | null
  exit_by: string | null
  risk_level: RiskLevel | null
}

const COLUMNS =
  'account, symbol, asset_type, action, review, reasons, warnings, trailing_stop, q10, q50, q90, horizon_days, exit_by, risk_level'

const toAction = (r: ActionRow): HoldingAction => ({
  account: r.account,
  symbol: r.symbol,
  assetType: r.asset_type,
  action: r.action,
  review: r.review,
  reasons: r.reasons,
  warnings: r.warnings,
  trailingStop: r.trailing_stop === null ? null : Number(r.trailing_stop),
  q10: r.q10,
  q50: r.q50,
  q90: r.q90,
  horizonDays: r.horizon_days,
  exitBy: r.exit_by,
  riskLevel: r.risk_level,
})

/** The holding actions of the newest published run that has any, with that run's day; null before the first. */
export async function loadHoldingActions(
  supabase: Supabase,
): Promise<{ runId: number; day: string; actions: HoldingAction[] } | null> {
  const newest = must(
    await supabase
      .from('holding_actions')
      .select('run_id, runs!inner(published, et_date)')
      .eq('runs.published', true)
      .order('run_id', { ascending: false })
      .limit(1),
  ) as unknown as { run_id: number; runs: { et_date: string } }[] // one run per row: an object, not a list
  if (newest.length === 0) return null
  const runId = newest[0].run_id
  const day = newest[0].runs.et_date
  const rows = (await fetchAll((from, to) =>
    supabase
      .from('holding_actions')
      .select(COLUMNS)
      .eq('run_id', runId)
      .order('account')
      .order('symbol')
      .order('asset_type')
      .range(from, to),
  )) as ActionRow[]
  return { runId, day, actions: rows.map(toAction) }
}
