import 'server-only'
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
const DETAIL_DAYS = 90

const num = (value: unknown): number | null => {
  if (value === null || value === undefined) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

const grouped = (value: number): string => value.toLocaleString('en-CA', { maximumFractionDigits: 4 })
const dollars = (value: number): string => `$${value.toFixed(2)}`

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

/** What arrived on held and watched stocks and coins since the previous published run. */
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
  if (all.length === 0) return buildFeed({ news: [], filings: [], insiders: [], earnings: [], alerts: [] }, opts)

  const horizon = new Date(now.getTime() + EARNINGS_DAYS * DAY_MS).toISOString()
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
            .select('accession, symbol, form, filed_at, items, url')
            .in('symbol', stocks)
            .gte('filed_at', since)
            .order('filed_at', { ascending: false })
            .order('accession')
            .range(from, to),
        )
      : [],
    stocks.length
      ? fetchAll((from, to) =>
          supabase
            .from('insider_trades')
            .select('accession, line, symbol, filed_at, owner, role, code, shares, price, planned')
            .in('symbol', stocks)
            .gte('filed_at', since)
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
    .map((r): FeedItem => ({ kind: 'news', symbol: r.symbol, at: r.published_at, title: r.title, url: r.url, detail: r.outlet }))
  const filings = (filingRows as { symbol: string; filed_at: string; items: string[] | null; url: string }[]).map((r): FeedItem => {
    const labels = itemLabels(r.items ?? [])
    return {
      kind: 'filing',
      symbol: r.symbol,
      at: r.filed_at,
      title: labels.length ? `8-K: ${labels.join(', ')}` : '8-K',
      url: r.url,
      important: isImportant(r.items ?? []),
    }
  })
  const insiders = (
    insiderRows as { symbol: string; filed_at: string; owner: string; role: string; code: 'P' | 'S'; shares: unknown; price: unknown; planned: boolean }[]
  ).map(
    (r): FeedItem => ({
      kind: 'insider',
      symbol: r.symbol,
      at: r.filed_at,
      title: insiderTitle({ owner: r.owner, role: r.role, code: r.code, shares: Number(r.shares), price: num(r.price) }),
      detail: r.planned ? '(10b5-1 plan)' : undefined,
    }),
  )
  const earnings = (earningsRows as { symbol: string; report_date: string; report_at: string; eps_estimate: unknown }[]).map((r): FeedItem => {
    const estimate = num(r.eps_estimate)
    return {
      kind: 'earnings',
      symbol: r.symbol,
      at: r.report_at,
      title: 'Earnings report due',
      detail: estimate === null ? shortDay(r.report_date) : `${shortDay(r.report_date)} · EPS estimate ${dollars(estimate)}`,
    }
  })
  return buildFeed({ news, filings, insiders, earnings, alerts: [] }, opts)
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
  alerts: PriceAlert[]
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
  const [quarterRows, filingRows, insiderRows, upcoming, past, alertRows] = await Promise.all([
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
      ? supabase
          .from('insider_trades')
          .select('filed_at, trade_date, owner, role, code, shares, price, value, planned')
          .eq('symbol', symbol)
          .gte('trade_date', since)
          .order('trade_date', { ascending: false })
          .order('accession')
          .order('line')
      : null,
    reports().gte('report_at', nowIso).order('report_at').limit(1),
    reports().lt('report_at', nowIso).order('report_at', { ascending: false }).limit(4),
    supabase
      .from('price_alerts')
      .select('id, direction, level, note, created_at, hit_at, hit_price, dismissed_at')
      .eq('symbol', symbol)
      .order('id', { ascending: false }),
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
      (insiderRows ? must(insiderRows) : []) as {
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
    alerts: (
      must(alertRows) as {
        id: number
        direction: 'above' | 'below'
        level: unknown
        note: string | null
        created_at: string
        hit_at: string | null
        hit_price: unknown
        dismissed_at: string | null
      }[]
    ).map((r) => ({
      id: r.id,
      direction: r.direction,
      level: Number(r.level),
      note: r.note,
      createdAt: r.created_at,
      hitAt: r.hit_at,
      hitPrice: num(r.hit_price),
      dismissedAt: r.dismissed_at,
    })),
  }
}
