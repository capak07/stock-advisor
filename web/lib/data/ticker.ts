import 'server-only'
import { addDays, todayInToronto } from '../dates'
import { buildLedger } from '../portfolio/ledger'
import type { FxRates } from '../portfolio/lookup'
import type { AssetType, Close, Currency, Market, Position } from '../portfolio/types'
import type { Run } from '../runs'
import { isValidSymbol, marketOf } from '../symbols'
import type { Supabase } from '../supabase/server'
import { fetchAll, must } from './fetch'
import type { Catalyst, Factor, Style } from './picks'
import { loadFx, loadTrades, type AssetRef } from './portfolio'
import { lastPublishedRun } from './runs'
import { isListedStock } from './symbols'

/** A year of trading days and the close before it, with room for holidays. */
const HISTORY_DAYS = 400
/** The news stage reads two days of feeds (spec §4.2). */
const NEWS_HOURS = 48
const MAX_HEADLINES = 200

export interface Headline {
  id: number
  publishedAt: string
  outlet: string
  url: string
  title: string
  sentiment: number | null
}

/** The news features the latest published run computed for this asset (Plan 2f). */
export interface NewsStats {
  stories: number
  outlets: number
  sentiment: number | null
  trend: number | null
}

/** One usable horizon of the latest published run's forecast: excess-return quantiles and P(beat). */
export interface ForecastHorizon {
  horizon: number
  q10: number
  q50: number
  q90: number
  pBeat: number
}

/** An earlier pick of this stock, with its graded outcome once Plan 4c's grading has one. */
export interface PastPick {
  id: number
  day: string
  style: Style
  horizon: number
  /** P(beat) at the pick's horizon in the run that picked it; null if that row is gone. */
  pBeat: number | null
  exitBy: string
  status: 'open' | 'exited_early' | 'graded'
  outcome: { ret: number; benchRet: number; excess: number; beat: boolean; hitStop: boolean; exitReason: string } | null
}

export interface TickerForecast {
  benchmark: string
  /** Ascending; empty when the latest run didn't forecast this stock (only past picks to show). */
  horizons: ForecastHorizon[]
  /** Stage 8's explanation at the stock's representative horizon (`features_live.features.advice`). */
  advice: { horizon: number; topFactors: Factor[]; catalysts: Catalyst[]; cost: number | null } | null
  /** The last 10 picks of this stock across published runs, newest first. */
  pastPicks: PastPick[]
}

export interface TickerData {
  name: string | null
  /** Null for a coin. */
  market: Market | null
  exchange: string | null
  closes: Close[]
  fx: FxRates
  /** The last 48 hours' headlines, newest first. */
  headlines: Headline[]
  news: { stats: NewsStats; run: Run } | null
  watched: boolean
  /** In the active stock lists or the stored coin list, so it can be watched. */
  watchable: boolean
  positions: Position[]
  /** Null for a coin, or a stock with neither a forecast nor past picks. */
  forecast: TickerForecast | null
}

/**
 * The asset a symbol in the address means when the link doesn't say: a symbol only one asset type
 * allows, else a listed stock, else a coin the pipeline prices, else a stock.
 */
export async function resolveAssetType(supabase: Supabase, symbol: string): Promise<AssetType | null> {
  const stock = isValidSymbol(symbol, 'stock')
  const coin = isValidSymbol(symbol, 'crypto')
  if (!stock || !coin) return stock ? 'stock' : coin ? 'crypto' : null
  if (await isListedStock(supabase, symbol)) return 'stock'
  const priced = must(
    await supabase.from('daily_closes').select('symbol').eq('asset_type', 'crypto').eq('symbol', symbol).limit(1),
  ) as unknown[]
  return priced.length > 0 ? 'crypto' : 'stock'
}

const toNumber = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null)

/** Everything the Ticker page shows for one asset. */
export async function loadTicker(supabase: Supabase, ref: AssetRef): Promise<TickerData> {
  const since = addDays(todayInToronto(), -HISTORY_DAYS)
  const newsSince = new Date(Date.now() - NEWS_HOURS * 3_600_000).toISOString()
  const [info, closes, fx, headlines, run, watch, trades] = await Promise.all([
    supabase.from('symbols').select('name, market, exchange, active').eq('asset_type', ref.assetType).eq('symbol', ref.symbol).limit(1),
    fetchAll((from, to) =>
      supabase
        .from('daily_closes')
        .select('day, close, currency')
        .eq('asset_type', ref.assetType)
        .eq('symbol', ref.symbol)
        .gte('day', since)
        .order('day')
        .range(from, to),
    ),
    loadFx(supabase),
    supabase
      .from('news_items')
      .select('id, published_at, outlet, url, title, sentiment')
      .eq('asset_type', ref.assetType)
      .eq('symbol', ref.symbol)
      .gte('published_at', newsSince)
      .order('published_at', { ascending: false })
      .order('id', { ascending: false })
      .limit(MAX_HEADLINES),
    lastPublishedRun(supabase),
    supabase.from('watchlist').select('symbol').eq('asset_type', ref.assetType).eq('symbol', ref.symbol).limit(1),
    loadTrades(supabase, ref),
  ])

  const features = run
    ? (must(
        await supabase
          .from('features_live')
          .select('features')
          .eq('run_id', run.id)
          .eq('asset_type', ref.assetType)
          .eq('symbol', ref.symbol)
          .limit(1),
      ) as { features: Record<string, unknown> }[])
    : []
  const f = features[0]?.features
  const forecast = ref.assetType === 'stock' ? await loadForecast(supabase, ref.symbol, run, f) : null
  const stories = toNumber(f?.news_stories_48h)
  const listed = (must(info) as { name: string; market: Market | null; exchange: string; active: boolean }[])[0]
  // A coin's row only says it's in the coin list; its name and exchange aren't shown.
  const stock = ref.assetType === 'stock' ? listed : undefined

  return {
    name: stock?.name ?? null,
    market: ref.assetType === 'crypto' ? null : (stock?.market ?? marketOf(ref.symbol)),
    exchange: stock?.exchange ?? null,
    closes: (closes as { day: string; close: string | number; currency: Currency }[]).map((c) => ({
      day: c.day,
      close: Number(c.close),
      currency: c.currency,
    })),
    fx,
    headlines: (
      must(headlines) as {
        id: number
        published_at: string
        outlet: string
        url: string
        title: string
        sentiment: number | null
      }[]
    ).map((h) => ({ id: h.id, publishedAt: h.published_at, outlet: h.outlet, url: h.url, title: h.title, sentiment: h.sentiment })),
    news:
      run && stories !== null
        ? {
            run,
            stats: {
              stories,
              outlets: toNumber(f?.news_outlets_48h) ?? 0,
              sentiment: toNumber(f?.news_sentiment_mean),
              trend: toNumber(f?.news_sentiment_trend),
            },
          }
        : null,
    watched: (must(watch) as unknown[]).length > 0,
    watchable: listed?.active === true,
    positions: buildLedger(trades, fx).positions,
    forecast,
  }
}

/** A stock's forecast, explanation and past picks (Plan 4b, the Ticker page's Forecast card). */
async function loadForecast(
  supabase: Supabase,
  symbol: string,
  run: Run | null,
  features: Record<string, unknown> | undefined,
): Promise<TickerForecast | null> {
  const [current, picked] = await Promise.all([
    run
      ? supabase
          .from('predictions')
          .select('horizon_days, q10, q50, q90, p_beat, benchmark')
          .eq('run_id', run.id)
          .eq('asset_type', 'stock')
          .eq('symbol', symbol)
          .order('horizon_days')
      : null,
    supabase
      .from('picks')
      .select('id, run_id, style, horizon_days, exit_by, status, runs!inner(et_date, published), pick_outcomes(ret, bench_ret, excess, beat, hit_stop, exit_reason)')
      .eq('symbol', symbol)
      .eq('asset_type', 'stock')
      .eq('runs.published', true)
      .order('id', { ascending: false })
      .limit(10),
  ])
  const rows = (current ? must(current) : []) as {
    horizon_days: number
    q10: number
    q50: number
    q90: number
    p_beat: number
    benchmark: string
  }[]
  // supabase-js types embedded rows as lists; many-to-one and one-to-one embeds arrive as one object
  const pastRows = must(picked) as unknown as {
    id: number
    run_id: number
    style: Style
    horizon_days: number
    exit_by: string
    status: PastPick['status']
    runs: { et_date: string }
    pick_outcomes: { ret: number; bench_ret: number; excess: number; beat: boolean; hit_stop: boolean; exit_reason: string } | null
  }[]
  if (rows.length === 0 && pastRows.length === 0) return null

  const runIds = [...new Set(pastRows.map((p) => p.run_id))]
  const thenRows = (
    runIds.length === 0
      ? []
      : must(
          await supabase
            .from('predictions')
            .select('run_id, horizon_days, p_beat')
            .eq('symbol', symbol)
            .eq('asset_type', 'stock')
            .in('run_id', runIds),
        )
  ) as { run_id: number; horizon_days: number; p_beat: number }[]
  const pThen = new Map(thenRows.map((r) => [`${r.run_id}:${r.horizon_days}`, Number(r.p_beat)]))

  const advice = (features?.advice ?? null) as {
    horizon?: number
    top_factors?: { feature: string; contribution: number }[]
    catalysts?: Catalyst[]
    round_trip_cost?: number
  } | null
  const value = (feature: string) => toNumber(features?.[feature]) ?? undefined

  return {
    benchmark: rows[0]?.benchmark ?? (symbol.endsWith('.TO') ? 'XIU.TO' : 'SPY'),
    horizons: rows.map((r) => ({
      horizon: r.horizon_days,
      q10: Number(r.q10),
      q50: Number(r.q50),
      q90: Number(r.q90),
      pBeat: Number(r.p_beat),
    })),
    advice:
      advice && typeof advice.horizon === 'number'
        ? {
            horizon: advice.horizon,
            topFactors: (advice.top_factors ?? []).map((t) => ({
              feature: t.feature,
              contribution: Number(t.contribution),
              value: value(t.feature),
            })),
            catalysts: advice.catalysts ?? [],
            cost: toNumber(advice.round_trip_cost),
          }
        : null,
    pastPicks: pastRows.map((p) => ({
      id: p.id,
      day: p.runs.et_date,
      style: p.style,
      horizon: p.horizon_days,
      pBeat: pThen.get(`${p.run_id}:${p.horizon_days}`) ?? null,
      exitBy: p.exit_by,
      status: p.status,
      outcome: p.pick_outcomes
        ? {
            ret: Number(p.pick_outcomes.ret),
            benchRet: Number(p.pick_outcomes.bench_ret),
            excess: Number(p.pick_outcomes.excess),
            beat: p.pick_outcomes.beat,
            hitStop: p.pick_outcomes.hit_stop,
            exitReason: p.pick_outcomes.exit_reason,
          }
        : null,
    })),
  }
}
