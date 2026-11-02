import 'server-only'
import type { ActionKind, HoldingAction, RiskLevel } from '../portfolio/actions'
import type { Account, AssetType } from '../portfolio/types'
import type { Supabase } from '../supabase/server'
import { heldCalls, type HeldCall } from '../verdicts'
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
  ref_price: string | number | null
  max_position_pct: number | null
}

const COLUMNS =
  'account, symbol, asset_type, action, review, reasons, warnings, trailing_stop, q10, q50, q90, horizon_days, exit_by, risk_level, ref_price, max_position_pct'

const num = (value: unknown): number | null => {
  const n = typeof value === 'string' ? Number(value) : value
  return typeof n === 'number' && Number.isFinite(n) ? n : null
}
const keyOf = (r: { account: string; symbol: string; asset_type: string }) => `${r.account}:${r.asset_type}:${r.symbol}`

interface OrderData {
  features: Map<string, { atrPct: number | null; dollarVolume20: number | null }>
  previousStops: Map<string, number>
}

const toAction = (r: ActionRow, extra: OrderData): HoldingAction => ({
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
  refPrice: num(r.ref_price),
  atrPct: r.asset_type === 'stock' ? (extra.features.get(r.symbol)?.atrPct ?? null) : null,
  dollarVolume20: r.asset_type === 'stock' ? (extra.features.get(r.symbol)?.dollarVolume20 ?? null) : null,
  previousStop: extra.previousStops.get(keyOf(r)) ?? null,
  maxPositionPct: num(r.max_position_pct),
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
  const extra = await orderData(supabase, runId, rows)
  return { runId, day, actions: rows.map((r) => toAction(r, extra)) }
}

/** The run's stored range and volume of each held stock, and the previous published run's trailing stops. */
async function orderData(supabase: Supabase, runId: number, rows: readonly ActionRow[]): Promise<OrderData> {
  const stocks = [...new Set(rows.filter((r) => r.asset_type === 'stock').map((r) => r.symbol))]
  const [features, previous] = await Promise.all([
    stocks.length === 0
      ? []
      : (must(
          await supabase
            .from('features_live')
            .select('symbol, atr:features->atr_14_pct, adv:features->log_adv20')
            .eq('run_id', runId)
            .eq('asset_type', 'stock')
            .in('symbol', stocks),
        ) as { symbol: string; atr: unknown; adv: unknown }[]),
    supabase
      .from('holding_actions')
      .select('run_id, runs!inner(published)')
      .eq('runs.published', true)
      .lt('run_id', runId)
      .order('run_id', { ascending: false })
      .limit(1),
  ])
  const previousRun = (must(previous) as { run_id: number }[])[0]?.run_id
  const stops = previousRun
    ? (must(
        await supabase.from('holding_actions').select('account, symbol, asset_type, trailing_stop').eq('run_id', previousRun),
      ) as { account: string; symbol: string; asset_type: string; trailing_stop: string | number | null }[])
    : []
  return {
    features: new Map(
      features.map((f) => {
        const adv = num(f.adv)
        return [f.symbol, { atrPct: num(f.atr), dollarVolume20: adv === null ? null : Math.expm1(adv) }] // the pipeline stores log1p(ADV)
      }),
    ),
    previousStops: new Map(stops.flatMap((s) => (num(s.trailing_stop) === null ? [] : [[keyOf(s), num(s.trailing_stop)!]]))),
  }
}

/** What My Portfolio says of each symbol held at run `runId`, by asset key (lib/verdicts.ts `heldCalls`). */
export async function loadHeldCalls(supabase: Supabase, runId: number): Promise<Map<string, HeldCall>> {
  const rows = must(
    await supabase
      .from('holding_actions')
      .select('account, symbol, asset_type, action, review, reasons, horizon_days, exit_by')
      .eq('run_id', runId),
  ) as Pick<ActionRow, 'account' | 'symbol' | 'asset_type' | 'action' | 'review' | 'reasons' | 'horizon_days' | 'exit_by'>[]
  return heldCalls(
    rows.map((r) => ({
      account: r.account,
      symbol: r.symbol,
      assetType: r.asset_type,
      action: r.action,
      review: r.review,
      reasons: r.reasons ?? [],
      horizonDays: r.horizon_days,
      exitBy: r.exit_by,
    })),
  )
}
