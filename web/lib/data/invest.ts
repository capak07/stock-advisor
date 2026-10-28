import 'server-only'
import { addDays } from '../dates'
import type { Candidate, ForecastRow } from '../invest/allocate'
import { buildLedger } from '../portfolio/ledger'
import { assetKey } from '../portfolio/types'
import type { Run } from '../runs'
import { marketOf } from '../symbols'
import type { Supabase } from '../supabase/server'
import { fetchAll, must } from './fetch'
import { loadCloses, loadFx, loadTrades } from './portfolio'
import { runById } from './runs'
import { loadSettings } from './settings'
import { loadNames, loadSectors } from './symbols'

/** Closes this many days before the run's day, so a holiday still finds the last one. */
const PRICE_LOOKBACK_DAYS = 10

/** What the Invest page splits an amount over: the newest published run's forecasts and prices. */
export interface InvestData {
  run: Run
  candidates: Candidate[]
  /** Stocks the owner holds in any account. */
  held: Set<string>
  usdFxFeePct: number
  /** BTC's latest price in CAD, when the run or the stored closes have one. */
  btcPriceCad: number | null
}

const num = (value: unknown): number | null => {
  const n = typeof value === 'string' ? Number(value) : value
  return typeof n === 'number' && Number.isFinite(n) ? n : null
}

/** The forecasts, features and prices the Invest page reads (design: 2026-10-27-invest-page-design.md); null before any run forecast. */
export async function loadInvestData(supabase: Supabase): Promise<InvestData | null> {
  const newest = must(
    await supabase
      .from('predictions')
      .select('run_id, runs!inner(published)')
      .eq('runs.published', true)
      .order('run_id', { ascending: false })
      .limit(1),
  ) as { run_id: number }[]
  if (!newest[0]) return null
  const run = await runById(supabase, newest[0].run_id)
  if (!run) return null

  const [predictions, features, btc, settings, trades, fx] = await Promise.all([
    fetchAll((from, to) =>
      supabase
        .from('predictions')
        .select('symbol, horizon_days, q10, q50, q90, p_beat, benchmark')
        .eq('run_id', run.id)
        .eq('asset_type', 'stock')
        .order('symbol')
        .order('horizon_days')
        .range(from, to),
    ) as Promise<
      { symbol: string; horizon_days: number; q10: number; q50: number; q90: number; p_beat: number; benchmark: string }[]
    >,
    fetchAll((from, to) =>
      supabase
        .from('features_live')
        .select('symbol, vol_60:features->vol_60, log_adv20:features->log_adv20, jump_5d:features->jump_5d')
        .eq('run_id', run.id)
        .eq('asset_type', 'stock')
        .order('symbol')
        .range(from, to),
    ) as Promise<{ symbol: string; vol_60: unknown; log_adv20: unknown; jump_5d: unknown }[]>,
    supabase
      .from('features_live')
      .select('price_cad:features->price_cad')
      .eq('run_id', run.id)
      .eq('asset_type', 'crypto')
      .eq('symbol', 'BTC')
      .limit(1),
    loadSettings(supabase),
    loadTrades(supabase),
    loadFx(supabase),
  ])

  const rows = new Map<string, ForecastRow[]>()
  for (const p of predictions) {
    const list = rows.get(p.symbol) ?? []
    list.push({
      horizonDays: p.horizon_days,
      q10: Number(p.q10),
      q50: Number(p.q50),
      q90: Number(p.q90),
      pBeat: Number(p.p_beat),
      benchmark: p.benchmark,
    })
    rows.set(p.symbol, list)
  }
  const symbols = [...rows.keys()]
  const byFeature = new Map(features.map((f) => [f.symbol, f]))
  const since = addDays(run.et_date, -PRICE_LOOKBACK_DAYS)
  const [names, sectors, prices] = await Promise.all([
    loadNames(supabase, symbols),
    loadSectors(supabase, symbols),
    loadCloses(supabase, [...symbols.map((symbol) => ({ symbol, assetType: 'stock' as const })), { symbol: 'BTC', assetType: 'crypto' }], since),
  ])

  const candidates = symbols.map((symbol): Candidate => {
    const f = byFeature.get(symbol)
    const logAdv = num(f?.log_adv20)
    const close = prices.latest(assetKey('stock', symbol))
    return {
      symbol,
      name: names.get(symbol) ?? null,
      market: marketOf(symbol),
      sector: sectors.get(symbol) ?? null,
      rows: rows.get(symbol) ?? [],
      vol60: num(f?.vol_60),
      dollarVolume20: logAdv === null ? null : Math.expm1(logAdv), // the pipeline stores log1p(ADV)
      jump5d: num(f?.jump_5d),
      priceCad: close ? fx.toCad(close) : null,
    }
  })

  const btcQuote = num((must(btc) as { price_cad: unknown }[])[0]?.price_cad)
  const btcClose = prices.latest(assetKey('crypto', 'BTC'))
  const held = new Set(
    buildLedger(trades, fx)
      .positions.filter((p) => p.assetType === 'stock')
      .map((p) => p.symbol),
  )

  return {
    run,
    candidates,
    held,
    usdFxFeePct: Number(settings.usd_fx_fee_pct),
    btcPriceCad: btcQuote ?? (btcClose ? fx.toCad(btcClose) : null),
  }
}
