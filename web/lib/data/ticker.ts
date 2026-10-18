import 'server-only'
import { addDays, todayInToronto } from '../dates'
import { buildLedger } from '../portfolio/ledger'
import type { FxRates } from '../portfolio/lookup'
import type { AssetType, Close, Currency, Market, Position } from '../portfolio/types'
import type { Run } from '../runs'
import { isValidSymbol, marketOf } from '../symbols'
import type { Supabase } from '../supabase/server'
import { fetchAll, must } from './fetch'
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
  positions: Position[]
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
    ref.assetType === 'stock'
      ? supabase.from('symbols').select('name, market, exchange').eq('asset_type', 'stock').eq('symbol', ref.symbol).limit(1)
      : null,
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
  const stories = toNumber(f?.news_stories_48h)
  const listed = info ? (must(info) as { name: string; market: Market; exchange: string }[])[0] : undefined

  return {
    name: listed?.name ?? null,
    market: ref.assetType === 'crypto' ? null : (listed?.market ?? marketOf(ref.symbol)),
    exchange: listed?.exchange ?? null,
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
    positions: buildLedger(trades, fx).positions,
  }
}
