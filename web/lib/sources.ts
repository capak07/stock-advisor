/** How the Source health and Ticker pages describe the pipeline's sources (spec §9, Plan 5c). */

import type { AssetType, Market } from './portfolio/types'

export type SourceStatus = 'ok' | 'partial' | 'stale' | 'failed' | 'skipped'
export type Category = 'prices' | 'fundamentals' | 'options' | 'macro' | 'news' | 'social' | 'catalysts' | 'onchain'

/** A collector in the pipeline's registry, as each run writes it to `sources`. */
export interface Source {
  name: string
  category: Category
  core: boolean
  cadence: 'per_run' | 'daily' | 'weekly'
  assetTypes: AssetType[]
  /** The stock markets it covers; empty for a coin-only source. */
  markets: Market[]
}

/** One `source_health` row: a source's result in a run or a daily check. */
export interface Health {
  source: string
  status: SourceStatus
  latencyMs: number
  records: number
  error: string | null
  /** Failures in a row; the pipeline skips a source for the rest of the day after 3. */
  failures: number
  attemptedAt: string
}

export const CATEGORY_LABELS: Record<Category, string> = {
  prices: 'Prices',
  fundamentals: 'Fundamentals',
  options: 'Options',
  macro: 'Macro',
  news: 'News',
  social: 'Social',
  catalysts: 'Catalysts',
  onchain: 'On-chain',
}

/** The pipeline's circuit breaker opens after this many failures in a row (runner.py). */
export const BREAKER_THRESHOLD = 3

/** A source answered when it returned fresh records, all of them or some; a stale one served old values. */
export const answered = (status: SourceStatus | undefined): boolean => status === 'ok' || status === 'partial'

export interface Coverage {
  assetType: AssetType
  /** Null for a coin. */
  market: Market | null
}

export const covers = (source: Source, asset: Coverage): boolean =>
  source.assetTypes.includes(asset.assetType) && (asset.market === null || source.markets.includes(asset.market))

/** "US stocks", "TSX stocks", "coins" */
export const coverageName = (asset: Coverage): string => (asset.market === null ? 'coins' : `${asset.market} stocks`)

export interface SourceRow extends Source {
  /** Its result in the latest run; null when that run didn't call it. */
  run: Health | null
  /** Its newest daily check. */
  check: Health | null
  /** When it last answered, in a run or a check. */
  lastOk: string | null
  problem: boolean
}

/**
 * Every registered source with its result in the latest run, its newest daily check and its last
 * good answer. A source with anything but "ok" in either is a problem. Problems come first, then
 * core sources, then by name.
 */
export function sourceRows(
  sources: readonly Source[],
  run: readonly Health[],
  checks: readonly Health[],
  lastOk: ReadonlyMap<string, string>,
): SourceRow[] {
  const inRun = new Map(run.map((h) => [h.source, h]))
  const newestCheck = new Map<string, Health>()
  for (const h of checks) {
    const seen = newestCheck.get(h.source)
    if (!seen || h.attemptedAt > seen.attemptedAt) newestCheck.set(h.source, h)
  }
  return sources
    .map((s) => {
      const r = inRun.get(s.name) ?? null
      const check = newestCheck.get(s.name) ?? null
      return {
        ...s,
        run: r,
        check,
        lastOk: lastOk.get(s.name) ?? null,
        problem: r?.status !== 'ok' || (check !== null && check.status !== 'ok'),
      }
    })
    .sort(
      (a, b) =>
        Number(b.problem) - Number(a.problem) || Number(b.core) - Number(a.core) || (a.name < b.name ? -1 : 1),
    )
}

export interface Tally extends Record<SourceStatus, number> {
  total: number
  /** Sources without a result. */
  missing: number
}

export function tally(rows: readonly SourceRow[], pick: (row: SourceRow) => Health | null): Tally {
  const counts: Tally = { total: rows.length, ok: 0, partial: 0, stale: 0, failed: 0, skipped: 0, missing: 0 }
  for (const row of rows) {
    const h = pick(row)
    if (h) counts[h.status] += 1
    else counts.missing += 1
  }
  return counts
}

/**
 * Why the run's headlines have no sentiment, from its summary's `news.sentiment` (Plan 2f): null
 * when FinBERT scored them, or for a run from before news was collected.
 */
export function sentimentNotice(summary: Record<string, unknown>): string | null {
  const news = summary.news as { sentiment?: unknown } | undefined
  const status = typeof news?.sentiment === 'string' ? news.sentiment : null
  if (status === null || status === 'finbert') return null
  if (status === 'unavailable') return "FinBERT couldn't be loaded (is the nlp extra installed?), so this run's headlines have no sentiment."
  if (status === 'skipped: run budget') return "The run ran out of time before scoring, so this run's headlines have no sentiment."
  if (status === 'no items') return 'No news source returned a headline in this run.'
  if (status === 'not run') return 'The run has no news sources, so it collected no headlines.'
  return `Scoring headlines failed (${status.replace(/^failed: /, '')}), so this run's headlines have no sentiment.`
}

/** "from cache" when the source made no request, then "262 ms", "1.4 s", "7 min 10 s". */
export function fmtLatency(ms: number): string {
  if (ms === 0) return 'from cache'
  if (ms < 1000) return `${ms} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  const s = Math.round(ms / 1000)
  return `${Math.floor(s / 60)} min ${s % 60} s`
}

/** "3.4 MB", "14 MB", "1.25 GB" (decimal units, as Supabase's 500 MB limit). */
export function fmtSize(bytes: number): string {
  const mb = bytes / 1e6
  if (mb >= 1000) return `${(mb / 1000).toFixed(2)} GB`
  return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`
}
