import 'server-only'
import { addDays } from '../dates'
import type { Candidate, ForecastRow } from '../invest/allocate'
import { minEdgeOf, topNOf } from '../invest/policy'
import { stopRulesOf, type StopRules } from '../orders'
import { buildLedger } from '../portfolio/ledger'
import { assetKey, type Market } from '../portfolio/types'
import type { Run } from '../runs'
import { marketOf } from '../symbols'
import type { Supabase } from '../supabase/server'
import { withQuotes } from '../quotes'
import { fetchAll, must } from './fetch'
import { loadCloses, loadFx, loadTrades } from './portfolio'
import { liveQuotes } from './quotes'
import { runById } from './runs'
import { loadSettings } from './settings'
import { loadNames, loadSectors } from './symbols'

/** Closes this many days before the run's day, so a holiday still finds the last one. */
const PRICE_LOOKBACK_DAYS = 10

/** What the Invest page splits an amount over: the newest published run's forecasts and prices. */
export interface InvestData {
  run: Run
  stocks: Candidate[]
  /** Coins this run scored. A run scores a coin when it is held or watched. */
  coins: Candidate[]
  heldStocks: Set<string>
  heldCoins: Set<string>
  usdFxFeePct: number
  cryptoFeePct: number
  /** Each market's stop rule for a bracket's stop loss: its active model's tuned one, else today's. */
  stopRules: Partial<Record<Market, StopRules>>
  /** Each market's accepted `top_n`, or null when that model still picks by P. */
  topN: Partial<Record<Market, number | null>>
  /** Each market's accepted `min_edge` (0 when none). */
  minEdge: Partial<Record<Market, number>>
}

const num = (value: unknown): number | null => {
  const n = typeof value === 'string' ? Number(value) : value
  return typeof n === 'number' && Number.isFinite(n) ? n : null
}

interface Prediction {
  symbol: string
  horizon_days: number
  q10: number
  q50: number
  q90: number
  p_beat: number
  benchmark: string
}

interface StockFeature {
  symbol: string
  vol_60: unknown
  log_adv20: unknown
  jump_5d: unknown
  atr_14_pct: unknown
}

interface CoinFeature extends StockFeature {
  price_cad: unknown
  volume_24h_cad: unknown
  unconfirmed_price: unknown
}

const horizonsOf = (predictions: readonly Prediction[]): Map<string, ForecastRow[]> => {
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
  return rows
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

  const [predictions, features, coinPredictions, coinFeatures, settings, trades, fx, models] = await Promise.all([
    fetchAll((from, to) =>
      supabase
        .from('predictions')
        .select('symbol, horizon_days, q10, q50, q90, p_beat, benchmark')
        .eq('run_id', run.id)
        .eq('asset_type', 'stock')
        .order('symbol')
        .order('horizon_days')
        .range(from, to),
    ) as Promise<Prediction[]>,
    fetchAll((from, to) =>
      supabase
        .from('features_live')
        .select('symbol, vol_60:features->vol_60, log_adv20:features->log_adv20, jump_5d:features->jump_5d, atr_14_pct:features->atr_14_pct')
        .eq('run_id', run.id)
        .eq('asset_type', 'stock')
        .order('symbol')
        .range(from, to),
    ) as Promise<StockFeature[]>,
    fetchAll((from, to) =>
      supabase
        .from('predictions')
        .select('symbol, horizon_days, q10, q50, q90, p_beat, benchmark')
        .eq('run_id', run.id)
        .eq('asset_type', 'crypto')
        .order('symbol')
        .order('horizon_days')
        .range(from, to),
    ) as Promise<Prediction[]>,
    fetchAll((from, to) =>
      supabase
        .from('features_live')
        .select(
          'symbol, vol_60:features->vol_60, log_adv20:features->log_adv20, jump_5d:features->jump_5d, atr_14_pct:features->atr_14_pct, price_cad:features->price_cad, volume_24h_cad:features->volume_24h_cad, unconfirmed_price:features->unconfirmed_price',
        )
        .eq('run_id', run.id)
        .eq('asset_type', 'crypto')
        .order('symbol')
        .range(from, to),
    ) as Promise<CoinFeature[]>,
    loadSettings(supabase),
    loadTrades(supabase),
    loadFx(supabase),
    supabase
      .from('models')
      .select('kind, metrics')
      .eq('active', true)
      .in('kind', ['stock_us', 'stock_tsx'])
      .then((answer) => must(answer) as { kind: 'stock_us' | 'stock_tsx'; metrics: unknown }[]),
  ])

  const stockRows = horizonsOf(predictions)
  const coinRows = horizonsOf(coinPredictions)
  const symbols = [...stockRows.keys()]
  const coinSymbols = [...coinRows.keys()]
  const byFeature = new Map(features.map((f) => [f.symbol, f]))
  const byCoin = new Map(coinFeatures.map((f) => [f.symbol, f]))
  const since = addDays(run.et_date, -PRICE_LOOKBACK_DAYS)
  const [names, sectors, coinNames, stored, live] = await Promise.all([
    loadNames(supabase, symbols),
    loadSectors(supabase, symbols),
    coinSymbols.length === 0
      ? Promise.resolve([] as { symbol: string; name: string }[])
      : supabase
          .from('symbols')
          .select('symbol, name')
          .eq('asset_type', 'crypto')
          .in('symbol', coinSymbols)
          .then((answer) => must(answer) as { symbol: string; name: string }[]),
    loadCloses(
      supabase,
      [
        ...symbols.map((symbol) => ({ symbol, assetType: 'stock' as const })),
        ...coinSymbols.map((symbol) => ({ symbol, assetType: 'crypto' as const })),
      ],
      since,
    ),
    liveQuotes(),
  ])
  const prices = withQuotes(stored, live) // a Refresh's live prices count the shares (lib/quotes.ts)
  const coinName = new Map(coinNames.map((r) => [r.symbol, r.name]))

  const stocks = symbols.map((symbol): Candidate => {
    const f = byFeature.get(symbol)
    const logAdv = num(f?.log_adv20)
    const close = prices.latest(assetKey('stock', symbol))
    return {
      symbol,
      name: names.get(symbol) ?? null,
      assetType: 'stock',
      market: marketOf(symbol),
      sector: sectors.get(symbol) ?? null,
      rows: stockRows.get(symbol) ?? [],
      vol60: num(f?.vol_60),
      dollarVolume20: logAdv === null ? null : Math.expm1(logAdv), // the pipeline stores log1p(ADV)
      jump5d: num(f?.jump_5d),
      priceCad: close ? fx.toCad(close) : null,
      price: close ? close.close : null,
      currency: close ? close.currency : marketOf(symbol) === 'US' ? 'USD' : 'CAD',
      atrPct: num(f?.atr_14_pct),
    }
  })

  const coins = coinSymbols.map((symbol): Candidate => {
    const f = byCoin.get(symbol)
    const logAdv = num(f?.log_adv20)
    const close = prices.latest(assetKey('crypto', symbol))
    const liveCad = live?.quotes[assetKey('crypto', symbol)]?.price ?? null // live coin quotes are CAD
    const priceCad = liveCad ?? num(f?.price_cad) ?? (close ? fx.toCad(close) : null)
    const jump = num(f?.jump_5d)
    const unconfirmed = f?.unconfirmed_price === true
    return {
      symbol,
      name: coinName.get(symbol) ?? null,
      assetType: 'crypto',
      market: null,
      sector: null,
      rows: coinRows.get(symbol) ?? [],
      vol60: num(f?.vol_60),
      dollarVolume20: logAdv !== null ? Math.expm1(logAdv) : num(f?.volume_24h_cad),
      // no stored jump counts as none; an unconfirmed latest print is the coin's jump
      jump5d: jump ?? (unconfirmed ? 1 : 0),
      priceCad,
      price: priceCad, // a coin trades in CAD
      currency: 'CAD',
      atrPct: num(f?.atr_14_pct),
    }
  })

  const positions = buildLedger(trades, fx).positions
  return {
    run,
    stocks,
    coins,
    heldStocks: new Set(positions.filter((p) => p.assetType === 'stock').map((p) => p.symbol)),
    heldCoins: new Set(positions.filter((p) => p.assetType === 'crypto').map((p) => p.symbol)),
    usdFxFeePct: Number(settings.usd_fx_fee_pct),
    cryptoFeePct: Number(settings.crypto_fee_pct),
    stopRules: Object.fromEntries(models.map((m) => [m.kind === 'stock_us' ? 'US' : 'TSX', stopRulesOf(m.metrics)])),
    topN: Object.fromEntries(models.map((m) => [m.kind === 'stock_us' ? 'US' : 'TSX', topNOf(m.metrics)])),
    minEdge: Object.fromEntries(models.map((m) => [m.kind === 'stock_us' ? 'US' : 'TSX', minEdgeOf(m.metrics)])),
  }
}
