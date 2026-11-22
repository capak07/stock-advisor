import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { ForecastCard, ForecastProvider } from '@/components/ticker/ForecastCard'
import { NewsCard, type HeadlineView, type NewsKpi } from '@/components/ticker/NewsCard'
import { AlertsCard } from '@/components/ticker/AlertsCard'
import { BackButton } from '@/components/ticker/BackButton'
import { planBenchmark } from '@/components/portfolio/ExitPlan'
import { EarningsCard } from '@/components/ticker/EarningsCard'
import { FilingsCard } from '@/components/ticker/FilingsCard'
import { InsidersCard } from '@/components/ticker/InsidersCard'
import { OutlookCard, PhoneOutlook } from '@/components/ticker/OutlookCard'
import { PositionCard } from '@/components/ticker/PositionCard'
import { PriceChart } from '@/components/ticker/PriceCard'
import { RememberVisit } from '@/components/ticker/RememberVisit'
import { TickerActions } from '@/components/ticker/TickerActions'
import { WatchToggle } from '@/components/ticker/WatchToggle'
import { ownerClient } from '@/lib/auth'
import { loadAlerts, loadHoldingData } from '@/lib/data/monitor'
import { loadSettings } from '@/lib/data/settings'
import { loadSourceHealth } from '@/lib/data/sources'
import { loadLowRanks } from '@/lib/data/low-rank'
import { loadHeldAction, loadTicker, resolveAssetType } from '@/lib/data/ticker'
import { shortDay, timeOrDate } from '@/lib/dates'
import { fmtMoney, fmtPct, fmtPrice } from '@/lib/format'
import { outlookFor } from '@/lib/outlook'
import { assetCurrency } from '@/lib/portfolio/exit-plan'
import type { AssetType } from '@/lib/portfolio/types'
import { runWhen } from '@/lib/runs'
import { answered, covers, coverageName, type Coverage } from '@/lib/sources'
import { isValidSymbol, normalizeSymbol } from '@/lib/symbols'
import { alertPrefill, fmtScore, lastMove, priceSeries, safeLink, tone } from '@/lib/ticker'

interface Props {
  params: Promise<{ symbol: string }>
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
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
 * The stock page (spec §7.7, ticker_2.html). Desktop: on the left the header card (symbol, name, price, today's
 * move, the price chart with the forecast range ahead), then the news, filings and the forecast's explanation;
 * on the right the Outlook, Your position (only when held), Earnings, and Watch / Alerts / Sources. A phone
 * stacks them header, Outlook, Your position, news, Earnings, actions; Alerts open in a sheet.
 */
export default async function TickerPage({ params, searchParams }: Props) {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const symbol = symbolOf((await params).symbol)
  const query = await searchParams
  const asked = query.asset
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
  // Filings, insider trades and quarterly numbers exist for US stocks only; earnings dates for US and TSX.
  const us = !coin && data.market === 'US'
  const lowRank = assetType === 'stock' ? (await loadLowRanks(supabase, [symbol])).get(symbol) : undefined
  const [holding, alerts, held] = await Promise.all([
    coin ? null : loadHoldingData(supabase, symbol, { us }),
    loadAlerts(supabase, symbol, assetType),
    data.positions.length > 0 ? loadHeldAction(supabase, symbol, assetType) : [],
  ])
  // an exit plan's "Alert me at" link prefills the alert form and opens its sheet; each bad value is ignored
  const prefill = alertPrefill(symbol, assetType, query)
  const series = priceSeries(data.closes, assetType, data.fx)
  const move = lastMove(series)
  // A coin is crypto priced in CAD; a stock names its exchange (NYSE, Nasdaq, TSX) and its currency.
  const name = coin ? null : (data.name ?? 'Not in the stock lists')
  const place = coin ? 'Crypto · priced in CAD' : `${data.exchange ?? data.market} · ${assetCurrency(assetType, symbol)}`
  // The Outlook opens at the horizon the verdict was judged at, else the one closest to 21 days (as on the Watchlist).
  const verdict = data.verdict
  const startAt = data.forecast ? (outlookFor(data.forecast.horizons, verdict?.horizon ?? null)?.horizon ?? null) : null

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
      {/* First in the phone Search sheet's recent list from now on (spec §6). */}
      <RememberVisit symbol={symbol} />
      <ForecastProvider forecast={data.forecast} initialHorizon={startAt}>
        <div className="ticker-grid">
          <div className="ticker-col t-left">
            <section className="card hero card-pad enter t-head" aria-label={`${symbol} price and forecast`}>
              <div className="t-top">
                <div className="t-id">
                  <BackButton />
                  <div style={{ minWidth: 0 }}>
                    <div className="t-name">
                      <h1 className="num ticker-symbol">{symbol}</h1>
                      {name && <span className="sub">{name}</span>}
                    </div>
                    <div className="label" style={{ marginTop: 7 }}>
                      {place}
                    </div>
                  </div>
                </div>
                {move && (
                  <div className="t-quote">
                    <div className="price-big" id="last-price" data-price={move.change !== null && move.change < 0 ? 'down' : 'up'}>
                      {fmtPrice(move.price, series.currency)}
                    </div>
                    {move.change !== null && move.pct !== null && (
                      <span className={`num t-move ${move.change < 0 ? 'loss' : 'gain'}`}>
                        {fmtMoney(move.change, { prefix: '', digits: 2, signed: true })} · {fmtPct(move.pct)}
                      </span>
                    )}
                    <span className="sub t-when">at the {shortDay(move.day)} close</span>
                  </div>
                )}
              </div>
              <PhoneOutlook verdict={verdict?.verdict ?? null} judgedAt={verdict?.horizon ?? null} coin={coin} />
              <PriceChart symbol={symbol} series={series} coin={coin} />
            </section>
            <NewsCard headlines={headlines} kpis={kpis} source={data.news ? runWhen(data.news.run) : null} />
            {holding && us && <FilingsCard filings={holding.filings} />}
            {holding && us && <InsidersCard trades={holding.insiders} />}
            {data.forecast && data.market && <ForecastCard usdFxFeePct={settings.usd_fx_fee_pct} market={data.market} />}
          </div>

          <div className="ticker-col t-right">
            <OutlookCard
              verdict={verdict?.verdict ?? null}
              judgedAt={verdict?.horizon ?? null}
              price={move?.price ?? null}
              currency={series.currency}
              coin={coin}
              lowRank={lowRank}
              emptyText={
                coin
                  ? `A forecast for ${symbol} appears here when you hold or watch it and a run has scored it.`
                  : `The forecast cone, its top factors, catalysts and past picks for ${symbol} appear here once the model runs.`
              }
            />
            {data.positions.length > 0 && (
              <PositionCard
                symbol={symbol}
                assetType={assetType}
                positions={data.positions}
                held={held}
                price={move?.price ?? null}
                currency={series.currency}
                usdCad={data.fx.latest()?.usdCad ?? null}
                benchmark={data.forecast?.benchmark ?? planBenchmark(assetType, symbol)}
              />
            )}
            {holding && (
              <EarningsCard
                quarters={holding.quarters}
                derived={holding.derived}
                latestFiling={holding.latestFiling}
                earnings={holding.earnings}
                now={new Date().toISOString()}
              />
            )}
            <TickerActions
              // Only listed stocks and coins can be watched; one watched before stays removable.
              watch={(data.watchable || data.watched) && <WatchToggle symbol={symbol} assetType={assetType} watched={data.watched} />}
              alerts={
                <AlertsCard
                  key={`${prefill.level}|${prefill.direction}|${prefill.note}`}
                  symbol={symbol}
                  assetType={assetType}
                  alerts={alerts}
                  initialLevel={prefill.level}
                  initialDirection={prefill.direction}
                  initialNote={prefill.note}
                />
              }
              summary={
                covering.length === 0
                  ? 'No sources are listed yet; the next run lists them.'
                  : health.run
                    ? `${answeredCount} of the ${covering.length} sources that cover ${coverageName(coverage)} answered in the ${runWhen(health.run)} run`
                    : 'No run has finished yet'
              }
            >
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
                </Link>{' '}
                has every source&apos;s errors and daily checks.
              </p>
            </TickerActions>
          </div>
        </div>
      </ForecastProvider>
    </main>
  )
}
