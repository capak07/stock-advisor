import { ArrowLeft, Info } from 'lucide-react'
import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { ForecastCard, ForecastProvider } from '@/components/ticker/ForecastCard'
import { NewsCard, type HeadlineView, type NewsKpi } from '@/components/ticker/NewsCard'
import { PriceCard } from '@/components/ticker/PriceCard'
import { WatchToggle } from '@/components/ticker/WatchToggle'
import { ownerClient } from '@/lib/auth'
import { loadSettings } from '@/lib/data/settings'
import { loadSourceHealth } from '@/lib/data/sources'
import { loadTicker, resolveAssetType } from '@/lib/data/ticker'
import { shortDay, timeOrDate } from '@/lib/dates'
import { fmtMoney, fmtPct, fmtPrice, fmtQty } from '@/lib/format'
import { ACCOUNT_LABELS } from '@/lib/portfolio/types'
import type { AssetType } from '@/lib/portfolio/types'
import { runWhen } from '@/lib/runs'
import { answered, covers, coverageName, type Coverage } from '@/lib/sources'
import { isValidSymbol, normalizeSymbol } from '@/lib/symbols'
import { fmtScore, lastMove, priceSeries, safeLink, tone } from '@/lib/ticker'

interface Props {
  params: Promise<{ symbol: string }>
  searchParams: Promise<{ asset?: string | string[] }>
}

const symbolOf = (raw: string): string | null => {
  try {
    return normalizeSymbol(decodeURIComponent(raw))
  } catch {
    return null // a malformed %-escape
  }
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  return { title: symbolOf((await params).symbol) ?? 'Ticker' }
}

const signedScore = (value: number | null): NewsKpi['value'] => (value === null ? '—' : fmtScore(value))
const scoreTone = (value: number | null): NewsKpi['tone'] => (value === null || value === 0 ? '' : value > 0 ? 'gain' : 'loss')

/**
 * Ticker detail (spec §9): the price history with the latest run's forecast cone, the owner's
 * position, the forecast's factors, catalysts and past picks, the last two days of news, and which
 * sources cover the asset.
 */
export default async function TickerPage({ params, searchParams }: Props) {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const symbol = symbolOf((await params).symbol)
  const asked = (await searchParams).asset
  if (!symbol) notFound()
  const assetType: AssetType | null =
    asked === 'crypto' || asked === 'stock' ? asked : await resolveAssetType(supabase, symbol)
  if (!assetType || !isValidSymbol(symbol, assetType)) notFound()

  const [data, health, settings] = await Promise.all([
    loadTicker(supabase, { symbol, assetType }),
    loadSourceHealth(supabase),
    loadSettings(supabase),
  ])
  const coin = assetType === 'crypto'
  const series = priceSeries(data.closes, assetType, data.fx)
  const move = lastMove(series)
  // A TSX stock trades on the TSX; a US stock names its exchange (NYSE, Nasdaq…).
  const exchange = data.exchange === data.market ? null : data.exchange
  const about = coin ? ['Crypto', 'priced in CAD'] : [data.name ?? 'Not in the stock lists', data.market, exchange]

  const coverage: Coverage = { assetType, market: data.market }
  const covering = health.rows.filter((r) => covers(r, coverage))
  const answeredCount = covering.filter((r) => answered(r.run?.status)).length
  // Stock sources that skip this market: TSX stocks have no SEC filings or FINRA short data.
  const elsewhere = coin
    ? []
    : health.rows.filter((r) => r.assetTypes.includes('stock') && !covers(r, coverage)).map((r) => r.name).sort()

  const headlines: HeadlineView[] = data.headlines.map((h) => ({
    id: h.id,
    title: h.title,
    link: safeLink(h.url),
    outlet: h.outlet,
    when: timeOrDate(h.publishedAt),
    score: h.sentiment === null ? '—' : fmtScore(h.sentiment),
    tone: tone(h.sentiment),
  }))
  const kpis: NewsKpi[] | null = data.news && [
    { label: 'Stories', value: String(data.news.stats.stories), tone: '' },
    { label: 'Outlets', value: String(data.news.stats.outlets), tone: '' },
    { label: 'Sentiment', value: signedScore(data.news.stats.sentiment), tone: scoreTone(data.news.stats.sentiment) },
    { label: 'Trend', value: signedScore(data.news.stats.trend), tone: scoreTone(data.news.stats.trend) },
  ]

  return (
    <main className="page">
      <div className="enter">
        <Link href="/" className="sub inline-flex items-center gap-1">
          <ArrowLeft style={{ width: 14, height: 14 }} />
          My Portfolio
        </Link>
        <div className="flex flex-wrap items-end justify-between gap-4" style={{ marginTop: 10 }}>
          <div>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h1 className="num ticker-symbol">{symbol}</h1>
              <span className="sub">{about.filter(Boolean).join(' · ')}</span>
            </div>
            {move && (
              <div className="flex flex-wrap items-baseline gap-3" style={{ marginTop: 8 }}>
                <span className="price-big" id="last-price">
                  {fmtPrice(move.price, series.currency)}
                </span>
                {move.change !== null && move.pct !== null && (
                  <span className={`num ${move.change < 0 ? 'loss' : 'gain'}`}>
                    {fmtMoney(move.change, { prefix: '', digits: 2, signed: true })} · {fmtPct(move.pct)}
                  </span>
                )}
                <span className="sub">at the {shortDay(move.day)} close</span>
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {data.positions.map((p) => (
              <span key={p.account} className="badge">
                You hold {fmtQty(p.qty)} · {ACCOUNT_LABELS[p.account]}
              </span>
            ))}
            {/* Only listed stocks and coins can be watched; one watched before stays removable. */}
            {(data.watchable || data.watched) && <WatchToggle symbol={symbol} assetType={assetType} watched={data.watched} />}
          </div>
        </div>
      </div>

      <ForecastProvider forecast={data.forecast}>
        <PriceCard symbol={symbol} series={series} coin={coin} />

        <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]" style={{ alignItems: 'start' }}>
          <div className="grid gap-4">
            {data.forecast && data.market ? (
              <ForecastCard usdFxFeePct={settings.usd_fx_fee_pct} market={data.market} />
            ) : data.forecast ? null : (
              <section className="card card-pad enter" aria-labelledby="forecast-h">
                <h2 id="forecast-h" style={{ marginBottom: 10 }}>
                  Forecast
                </h2>
                <div className="banner info">
                  <Info />
                  <div>
                    {coin
                      ? `A forecast for ${symbol} appears here when you hold or watch it and a run has scored it.`
                      : `The forecast cone, its top factors, catalysts and past picks for ${symbol} appear here once the model runs.`}
                  </div>
                </div>
              </section>
            )}
            <section className="card card-pad enter" aria-labelledby="sources-h">
              <div className="section-head" style={{ marginBottom: 10 }}>
                <h2 id="sources-h">Sources</h2>
                <span className="sub">
                  {covering.length === 0
                    ? 'No sources are listed yet; the next run lists them.'
                    : health.run
                      ? `${answeredCount} of the ${covering.length} sources that cover ${coverageName(coverage)} answered in the ${runWhen(health.run)} run`
                      : 'No run has finished yet'}
                </span>
              </div>
              <div className="source-grid" id="ticker-sources">
                {covering.map((r) => (
                  <span key={r.name}>
                    <span className={`dot ${r.run?.status ?? 'skipped'}`} />
                    <span className="num">{r.name}</span>
                    {r.run?.status !== 'ok' && <span className="sub">{r.run?.status ?? 'not run'}</span>}
                  </span>
                ))}
              </div>
              {elsewhere.length > 0 && (
                <p className="sub" style={{ margin: '10px 0 0' }}>
                  Not available for {coverageName(coverage)}: {elsewhere.join(', ')}.
                </p>
              )}
              <p className="sub" style={{ margin: '10px 0 0' }}>
                <Link className="text-link" href="/sources">
                  Source health
                </Link> has every source&apos;s errors and daily checks.
              </p>
            </section>
          </div>
          <NewsCard headlines={headlines} kpis={kpis} source={data.news ? runWhen(data.news.run) : null} />
        </section>
      </ForecastProvider>
    </main>
  )
}
