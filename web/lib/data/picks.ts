import 'server-only'
import { assetKey, type Market } from '../portfolio/types'
import type { Run } from '../runs'
import { marketOf } from '../symbols'
import type { Supabase } from '../supabase/server'
import type { HeldCall } from '../verdicts'
import { loadHeldCalls } from './actions'
import { fetchAll, must } from './fetch'
import { lastPublishedRun } from './runs'
import { loadNames, loadSectors } from './symbols'

export type Style = 'swing' | 'position'
const MARKETS: readonly Market[] = ['US', 'TSX']
const MODEL_KIND: Record<Market, string> = { US: 'stock_us', TSX: 'stock_tsx' }

/** One of a forecast's top factors: the model feature, its push on the median, and today's value. */
export interface Factor {
  feature: string
  contribution: number
  /** The stock's value of the feature this run; undefined when the run didn't store it. */
  value: number | undefined
}

/** A dated event inside a hold (earnings, a phase 2/3 trial completion) or a recent 8-K. */
export interface Catalyst {
  type: string
  date: string
  exact?: boolean
  items?: string[]
}

export interface PickView {
  id: number
  symbol: string
  name: string | null
  sector: string | null
  market: Market
  style: Style
  rank: number
  horizon: number
  /** From the run's `predictions` at the pick's horizon; null if that row is missing. */
  q10: number | null
  q50: number | null
  q90: number | null
  pBeat: number | null
  exitBy: string
  entry: number
  stop: number
  riskLevel: string
  maxPositionPct: number
  topFactors: Factor[]
  catalysts: Catalyst[]
  /** The round-trip cost the gate used (`features_live.features.advice.round_trip_cost`); null if not stored. */
  cost: number | null
  /** Set for a TSX pick: the forecast rests on price and sector, with no company filings. */
  basis: string | null
  benchmark: string
  /** For order guidance (lib/orders.ts): the 14-day daily range as a fraction, and 20-day dollar volume. */
  atrPct: number | null
  dollarVolume20: number | null
}

/** A pick the run told the owner to exit early (Plan 4c), with its graded outcome. */
export interface ExitView {
  id: number
  symbol: string
  style: Style
  horizon: number
  exitPrice: number
  ret: number
  /** "exit_early" when P fell to 0.42 or below; "stop" when its 3:15 price was at or under its stop. */
  reason: string
}

export interface MarketPicks {
  market: Market
  /** The active model's backtest gate (`metrics.picks_enabled`); false without a model. */
  enabled: boolean
  /** The gate's reason when disabled (`metrics.picks_reason`); null when the market has no active model. */
  reason: string | null
  swing: PickView[]
  position: PickView[]
  exitedEarly: ExitView[]
  /** Picks graded live so far, per style (spec §6.6's paper period). */
  graded: Record<Style, number>
}

export interface VerdictView {
  symbol: string
  assetType: 'stock' | 'crypto'
  market: Market | null
  verdict: 'buy' | 'hold' | 'avoid'
  reasons: string[]
  details: Record<string, unknown>
  /** Held at the run: My Portfolio's action, shown instead of the verdict. */
  held: HeldCall | null
}

const num = (value: unknown): number | undefined => {
  const n = typeof value === 'string' ? Number(value) : value
  return typeof n === 'number' && Number.isFinite(n) ? n : undefined
}

/** The latest published run's picks, gates, early exits and verdicts (Plan 4b, Today's Picks). */
export async function loadPicks(supabase: Supabase): Promise<{ run: Run | null; markets: MarketPicks[]; verdicts: VerdictView[] }> {
  const run = await lastPublishedRun(supabase)
  if (!run) return { run: null, markets: [], verdicts: [] }

  const [picks, models, verdictRows, exits, graded, held] = await Promise.all([
    supabase
      .from('picks')
      .select('id, symbol, market, style, horizon_days, exit_by, entry_ref_price, stop, risk_level, max_position_pct, rank, top_factors, catalysts')
      .eq('run_id', run.id)
      .order('rank'),
    supabase.from('models').select('kind, metrics').eq('active', true),
    supabase.from('watchlist_verdicts').select('symbol, asset_type, verdict, reasons, details').eq('run_id', run.id),
    // this run's early exits: their outcome was written by this run's grading
    supabase
      .from('pick_outcomes')
      .select('pick_id, exit_price, exit_reason, ret, picks!inner(symbol, market, style, horizon_days, status)')
      .eq('picks.status', 'exited_early')
      .gte('graded_at', run.started_at),
    // supabase-js types an embedded row as a list, but a many-to-one embed arrives as one object
    fetchAll((from, to) =>
      supabase.from('pick_outcomes').select('pick_id, picks!inner(market, style)').order('pick_id').range(from, to),
    ) as unknown as Promise<{ pick_id: number; picks: { market: Market; style: Style } }[]>,
    loadHeldCalls(supabase, run.id),
  ])

  const pickRows = must(picks) as {
    id: number
    symbol: string
    market: Market
    style: Style
    horizon_days: number
    exit_by: string
    entry_ref_price: string | number
    stop: string | number
    risk_level: string
    max_position_pct: number
    rank: number
    top_factors: { feature: string; contribution: number }[]
    catalysts: Catalyst[]
  }[]
  const symbols = [...new Set(pickRows.map((p) => p.symbol))]

  const [predictions, features, names, sectors] = await Promise.all([
    symbols.length === 0
      ? []
      : (must(
          await supabase
            .from('predictions')
            .select('symbol, horizon_days, q10, q50, q90, p_beat, benchmark')
            .eq('run_id', run.id)
            .in('symbol', symbols),
        ) as { symbol: string; horizon_days: number; q10: number; q50: number; q90: number; p_beat: number; benchmark: string }[]),
    symbols.length === 0
      ? []
      : (must(
          await supabase.from('features_live').select('symbol, features').eq('run_id', run.id).eq('asset_type', 'stock').in('symbol', symbols),
        ) as { symbol: string; features: Record<string, unknown> }[]),
    loadNames(supabase, symbols),
    loadSectors(supabase, symbols),
  ])
  const prediction = new Map(predictions.map((p) => [`${p.symbol}:${p.horizon_days}`, p]))
  const featuresOf = new Map(features.map((f) => [f.symbol, f.features]))

  const view = (p: (typeof pickRows)[number]): PickView => {
    const f = featuresOf.get(p.symbol) ?? {}
    const advice = (f.advice ?? {}) as { round_trip_cost?: unknown; basis?: unknown }
    const q = prediction.get(`${p.symbol}:${p.horizon_days}`)
    const adv = num(f.log_adv20)
    return {
      id: p.id,
      symbol: p.symbol,
      name: names.get(p.symbol) ?? null,
      sector: sectors.get(p.symbol) ?? null,
      market: p.market,
      style: p.style,
      rank: p.rank,
      horizon: p.horizon_days,
      q10: q ? Number(q.q10) : null,
      q50: q ? Number(q.q50) : null,
      q90: q ? Number(q.q90) : null,
      pBeat: q ? Number(q.p_beat) : null,
      exitBy: p.exit_by,
      entry: Number(p.entry_ref_price),
      stop: Number(p.stop),
      riskLevel: p.risk_level,
      maxPositionPct: Number(p.max_position_pct),
      topFactors: (p.top_factors ?? []).map((t) => ({ feature: t.feature, contribution: Number(t.contribution), value: num(f[t.feature]) })),
      catalysts: p.catalysts ?? [],
      cost: num(advice.round_trip_cost) ?? null,
      basis: typeof advice.basis === 'string' ? advice.basis : null,
      benchmark: q?.benchmark ?? (p.market === 'TSX' ? 'XIU.TO' : 'SPY'),
      atrPct: num(f.atr_14_pct) ?? null,
      dollarVolume20: adv === undefined ? null : Math.expm1(adv), // the pipeline stores log1p(ADV)
    }
  }

  const gates = new Map(
    (must(models) as { kind: string; metrics: Record<string, unknown> }[]).map((m) => [m.kind, m.metrics ?? {}]),
  )
  const exitRows = must(exits) as unknown as {
    pick_id: number
    exit_price: string | number
    exit_reason: string
    ret: number
    picks: { symbol: string; market: Market; style: Style; horizon_days: number }
  }[]

  const markets = MARKETS.map((market): MarketPicks => {
    const metrics = gates.get(MODEL_KIND[market])
    const enabled = metrics?.picks_enabled === true
    const ofMarket = pickRows.filter((p) => p.market === market).map(view)
    return {
      market,
      enabled,
      reason: metrics === undefined ? null : enabled ? null : String(metrics.picks_reason ?? 'the model has no backtest gate result'),
      swing: ofMarket.filter((p) => p.style === 'swing'),
      position: ofMarket.filter((p) => p.style === 'position'),
      exitedEarly: exitRows
        .filter((e) => e.picks.market === market)
        .map((e) => ({
          id: e.pick_id,
          symbol: e.picks.symbol,
          style: e.picks.style,
          horizon: e.picks.horizon_days,
          exitPrice: Number(e.exit_price),
          ret: Number(e.ret),
          reason: e.exit_reason,
        })),
      graded: {
        swing: graded.filter((g) => g.picks.market === market && g.picks.style === 'swing').length,
        position: graded.filter((g) => g.picks.market === market && g.picks.style === 'position').length,
      },
    }
  })

  const marketRank = (v: VerdictView) => (v.market === 'US' ? 0 : v.market === 'TSX' ? 1 : 2)
  const verdicts = (
    must(verdictRows) as { symbol: string; asset_type: 'stock' | 'crypto'; verdict: VerdictView['verdict']; reasons: string[]; details: Record<string, unknown> }[]
  )
    .map((v): VerdictView => ({
      symbol: v.symbol,
      assetType: v.asset_type,
      market: v.asset_type === 'stock' ? marketOf(v.symbol) : null,
      verdict: v.verdict,
      reasons: v.reasons ?? [],
      details: v.details ?? {},
      held: held.get(assetKey(v.asset_type, v.symbol)) ?? null,
    }))
    .sort((a, b) => marketRank(a) - marketRank(b) || a.symbol.localeCompare(b.symbol))

  return { run, markets, verdicts }
}
