import 'server-only'
import { alertTitle, fmtLevel } from '../alert-form'
import { addDays, shortDay, todayInToronto } from '../dates'
import type { Quarter } from '../earnings'
import { isImportant, itemLabels } from '../filings'
import { buildFeed, type FeedItem } from '../monitor'
import { buildLedger } from '../portfolio/ledger'
import { assetKey, type AssetType } from '../portfolio/types'
import type { Supabase } from '../supabase/server'
import { fetchAll, must } from './fetch'
import { loadFx, loadTrades } from './portfolio'
import { lastTwoPublishedRuns } from './runs'
import { loadWatchlist } from './watchlist'

const HOUR_MS = 3_600_000
const DAY_MS = 24 * HOUR_MS
const FALLBACK_HOURS = 48
const EARNINGS_DAYS = 14
/** A filing or insider trade stored since the last run shows only if filed within this many days, so
 * the first fetch for a newly held or watched stock doesn't fill the feed with months-old filings. */
const FEED_FILED_DAYS = 14
const DETAIL_DAYS = 90

const num = (value: unknown): number | null => {
  if (value === null || value === undefined) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

const grouped = (value: number): string => value.toLocaleString('en-CA', { maximumFractionDigits: 4 })
const dollars = (value: number): string => `${value < 0 ? '-' : ''}$${Math.abs(value).toFixed(2)}`

export interface InsiderTrade {
  tradeDate: string
  filedAt: string
  owner: string
  role: string
  code: 'P' | 'S'
  shares: number
  price: number | null
  value: number | null
  planned: boolean
}

/** "Jane Doe (CFO) bought 1,000 shares at $12.34" */
export const insiderTitle = (t: Pick<InsiderTrade, 'owner' | 'role' | 'code' | 'shares' | 'price'>): string =>
  `${t.owner}${t.role ? ` (${t.role})` : ''} ${t.code === 'P' ? 'bought' : 'sold'} ${grouped(t.shares)} shares${
    t.price === null ? '' : ` at ${dollars(t.price)}`
  }`

/** The cut-off for "new": the start of the previous published run, else 48 hours ago. */
export async function feedSince(supabase: Supabase, now: Date): Promise<string> {
  const runs = await lastTwoPublishedRuns(supabase)
  return runs.length >= 2 ? runs[1].started_at : new Date(now.getTime() - FALLBACK_HOURS * HOUR_MS).toISOString()
}

/** What arrived on held and watched stocks and coins since the previous published run (filings and
 * insider trades: stored since then and filed in the last 14 days). */
export async function loadMonitorFeed(supabase: Supabase): Promise<FeedItem[]> {
  const now = new Date()
  const [trades, fx, watch, since] = await Promise.all([
    loadTrades(supabase),
    loadFx(supabase),
    loadWatchlist(supabase),
    feedSince(supabase, now),
  ])
  const keys = new Set<string>()
  for (const p of buildLedger(trades, fx).positions) keys.add(assetKey(p.assetType, p.symbol))
  for (const w of watch) keys.add(assetKey(w.assetType, w.symbol))
  const symbolsOf = (type: AssetType): string[] => {
    const prefix = assetKey(type, '')
    return [...keys].filter((k) => k.startsWith(prefix)).map((k) => k.slice(prefix.length))
  }
  const stocks = symbolsOf('stock')
  const all = [...stocks, ...symbolsOf('crypto')]
  const opts = { since, now: now.toISOString() }
  // hit alerts show for any symbol, held or watched or not, until dismissed
  const alertRows = must(
    await supabase
      .from('price_alerts')
      .select('id, symbol, asset_type, direction, level, hit_at, hit_price')
      .not('hit_at', 'is', null)
      .is('dismissed_at', null)
      .order('hit_at', { ascending: false }),
  ) as { id: number; symbol: string; asset_type: AssetType; direction: 'above' | 'below'; level: unknown; hit_at: string; hit_price: unknown }[]
  const alerts = alertRows.map(
    (r): FeedItem => {
      const hit = num(r.hit_price)
      return {
        kind: 'alert',
        assetType: r.asset_type,
        alertId: r.id,
        symbol: r.symbol,
        at: r.hit_at,
        title: alertTitle(r.direction, Number(r.level)),
        detail: hit === null ? undefined : fmtLevel(hit),
      }
    },
  )
  if (all.length === 0) return buildFeed({ news: [], filings: [], insiders: [], earnings: [], alerts }, opts)

  const horizon = new Date(now.getTime() + EARNINGS_DAYS * DAY_MS).toISOString()
  // Filings and insider trades are "new" when the pipeline stored them after `since`, not when they were
  // filed: Form 4s are fetched once a day and a failed SEC fetch is caught up later.
  const filedFloor = new Date(now.getTime() - FEED_FILED_DAYS * DAY_MS).toISOString()
  const [newsRows, filingRows, insiderRows, earningsRows] = await Promise.all([
    fetchAll((from, to) =>
      supabase
        .from('news_items')
        .select('id, symbol, asset_type, published_at, outlet, url, title')
        .in('symbol', all)
        .gte('published_at', since)
        .order('published_at', { ascending: false })
        .order('id', { ascending: false })
        .range(from, to),
    ),
    stocks.length
      ? fetchAll((from, to) =>
          supabase
            .from('filings')
            .select('accession, symbol, form, filed_at, items, url, added_at')
            .in('symbol', stocks)
            .gte('added_at', since)
            .gte('filed_at', filedFloor)
            .order('filed_at', { ascending: false })
            .order('accession')
            .range(from, to),
        )
      : [],
    stocks.length
      ? fetchAll((from, to) =>
          supabase
            .from('insider_trades')
            .select('accession, line, symbol, filed_at, owner, role, code, shares, price, planned, added_at')
            .in('symbol', stocks)
            .gte('added_at', since)
            .gte('filed_at', filedFloor)
            .order('filed_at', { ascending: false })
            .order('accession')
            .order('line')
            .range(from, to),
        )
      : [],
    stocks.length
      ? must(
          await supabase
            .from('earnings_reports')
            .select('symbol, report_date, report_at, eps_estimate')
            .in('symbol', stocks)
            .gte('report_at', now.toISOString())
            .lte('report_at', horizon)
            .order('report_at'),
        )
      : [],
  ])

  const news = (newsRows as { symbol: string; asset_type: AssetType; published_at: string; outlet: string; url: string; title: string }[])
    .filter((r) => keys.has(assetKey(r.asset_type, r.symbol)))
    .map((r): FeedItem => ({ kind: 'news', assetType: r.asset_type, symbol: r.symbol, at: r.published_at, title: r.title, url: r.url, detail: r.outlet }))
  const filings = (filingRows as { symbol: string; form: string; filed_at: string; items: string[] | null; url: string; added_at: string }[]).map((r): FeedItem => {
    const labels = itemLabels(r.items ?? [])
    return {
      kind: 'filing',
      assetType: 'stock',
      symbol: r.symbol,
      at: r.filed_at,
      addedAt: r.added_at,
      title: labels.length ? `${r.form}: ${labels.join(', ')}` : r.form,
      url: r.url,
      important: isImportant(r.items ?? []),
    }
  })
  const insiders = (
    insiderRows as { symbol: string; filed_at: string; owner: string; role: string; code: 'P' | 'S'; shares: unknown; price: unknown; planned: boolean; added_at: string }[]
  ).map(
    (r): FeedItem => ({
      kind: 'insider',
      assetType: 'stock',
      symbol: r.symbol,
      at: r.filed_at,
      addedAt: r.added_at,
      title: insiderTitle({ owner: r.owner, role: r.role, code: r.code, shares: Number(r.shares), price: num(r.price) }),
      detail: r.planned ? '(10b5-1 plan)' : undefined,
    }),
  )
  const earnings = (earningsRows as { symbol: string; report_date: string; report_at: string; eps_estimate: unknown }[]).map((r): FeedItem => {
    const estimate = num(r.eps_estimate)
    return {
      kind: 'earnings',
      assetType: 'stock',
      symbol: r.symbol,
      at: r.report_at,
      title: 'Earnings report due',
      detail: estimate === null ? shortDay(r.report_date) : `${shortDay(r.report_date)} · EPS estimate ${dollars(estimate)}`,
    }
  })
  return buildFeed({ news, filings, insiders, earnings, alerts }, opts)
}

export interface EarningsReport {
  reportDate: string
  reportAt: string
  epsEstimate: number | null
  epsActual: number | null
  surprisePct: number | null
}

export interface FilingRow {
  accession: string
  form: string
  filedAt: string
  items: string[]
  url: string
}

export interface PriceAlert {
  id: number
  direction: 'above' | 'below'
  level: number
  note: string | null
  createdAt: string
  hitAt: string | null
  hitPrice: number | null
  dismissedAt: string | null
}

export interface HoldingData {
  /** Newest first, up to ten so the newest six each find their year-ago quarter. */
  quarters: Quarter[]
  /** Period ends of quarters derived from a 10-K (Q4 = year minus nine months). */
  derived: string[]
  latestFiling: { form: string; filed: string } | null
  /** The next report (if any) first, then the last four reports, newest first. */
  earnings: EarningsReport[]
  filings: FilingRow[]
  insiders: InsiderTrade[]
}

type QuarterRow = {
  period_end: string
  fiscal_period: string | null
  revenue: unknown
  gross_profit: unknown
  operating_income: unknown
  net_income: unknown
  eps_diluted: unknown
  form: string
  filed: string
  derived: boolean
}
type EarningsRow = { report_date: string; report_at: string; eps_estimate: unknown; eps_actual: unknown; surprise_pct: unknown }

const toReport = (r: EarningsRow): EarningsReport => ({
  reportDate: r.report_date,
  reportAt: r.report_at,
  epsEstimate: num(r.eps_estimate),
  epsActual: num(r.eps_actual),
  surprisePct: num(r.surprise_pct),
})

/**
 * What the ticker page shows for one stock: quarterly numbers, filings and insider trades (US stocks
 * only: `us`), earnings dates (US and TSX) and the owner's price alerts.
 */
export async function loadHoldingData(supabase: Supabase, symbol: string, { us }: { us: boolean }): Promise<HoldingData> {
  const nowIso = new Date().toISOString()
  const since = addDays(todayInToronto(), -DETAIL_DAYS)
  const reports = () =>
    supabase.from('earnings_reports').select('report_date, report_at, eps_estimate, eps_actual, surprise_pct').eq('symbol', symbol)
  const [quarterRows, filingRows, insiderRows, upcoming, past] = await Promise.all([
    us
      ? supabase
          .from('financial_quarters')
          .select('period_end, fiscal_period, revenue, gross_profit, operating_income, net_income, eps_diluted, form, filed, derived')
          .eq('symbol', symbol)
          .order('period_end', { ascending: false })
          .limit(10)
      : null,
    us
      ? supabase
          .from('filings')
          .select('accession, form, filed_at, items, url')
          .eq('symbol', symbol)
          .gte('filed_at', since)
          .order('filed_at', { ascending: false })
          .order('accession')
      : null,
    us
      ? fetchAll((from, to) =>
          supabase
            .from('insider_trades')
            .select('filed_at, trade_date, owner, role, code, shares, price, value, planned')
            .eq('symbol', symbol)
            .gte('trade_date', since)
            .order('trade_date', { ascending: false })
            .order('accession')
            .order('line')
            .range(from, to),
        )
      : [],
    reports().gte('report_at', nowIso).order('report_at').limit(1),
    reports().lt('report_at', nowIso).order('report_at', { ascending: false }).limit(4),
  ])

  const qrows = (quarterRows ? must(quarterRows) : []) as QuarterRow[]
  return {
    quarters: qrows.map((r) => ({
      periodEnd: r.period_end,
      fiscalPeriod: r.fiscal_period,
      revenue: num(r.revenue),
      grossProfit: num(r.gross_profit),
      operatingIncome: num(r.operating_income),
      netIncome: num(r.net_income),
      epsDiluted: num(r.eps_diluted),
    })),
    derived: qrows.filter((r) => r.derived).map((r) => r.period_end),
    latestFiling: qrows[0] ? { form: qrows[0].form, filed: qrows[0].filed } : null,
    earnings: [...(must(upcoming) as EarningsRow[]), ...(must(past) as EarningsRow[])].map(toReport),
    filings: ((filingRows ? must(filingRows) : []) as { accession: string; form: string; filed_at: string; items: string[] | null; url: string }[]).map(
      (r) => ({ accession: r.accession, form: r.form, filedAt: r.filed_at, items: r.items ?? [], url: r.url }),
    ),
    insiders: (
      insiderRows as {
        filed_at: string
        trade_date: string
        owner: string
        role: string
        code: 'P' | 'S'
        shares: unknown
        price: unknown
        value: unknown
        planned: boolean
      }[]
    ).map((r) => ({
      tradeDate: r.trade_date,
      filedAt: r.filed_at,
      owner: r.owner,
      role: r.role,
      code: r.code,
      shares: Number(r.shares),
      price: num(r.price),
      value: num(r.value),
      planned: r.planned,
    })),
  }
}

/** The owner's alerts on one asset (stock or coin), newest first. */
export async function loadAlerts(supabase: Supabase, symbol: string, assetType: AssetType): Promise<PriceAlert[]> {
  const rows = must(
    await supabase
      .from('price_alerts')
      .select('id, direction, level, note, created_at, hit_at, hit_price, dismissed_at')
      .eq('symbol', symbol)
      .eq('asset_type', assetType)
      .order('id', { ascending: false }),
  ) as {
    id: number
    direction: 'above' | 'below'
    level: unknown
    note: string | null
    created_at: string
    hit_at: string | null
    hit_price: unknown
    dismissed_at: string | null
  }[]
  return rows.map((r) => ({
    id: r.id,
    direction: r.direction,
    level: Number(r.level),
    note: r.note,
    createdAt: r.created_at,
    hitAt: r.hit_at,
    hitPrice: num(r.hit_price),
    dismissedAt: r.dismissed_at,
  }))
}
