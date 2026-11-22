import { Info } from 'lucide-react'
import type { Metadata } from 'next'
import { OrderDisclaimer } from '@/components/OrderGuide'
import { AddWatch, WatchList, type WatchRow } from '@/components/watchlist/Watchlist'
import { ownerClient } from '@/lib/auth'
import { loadCloses, loadFx, loadPortfolio } from '@/lib/data/portfolio'
import { loadNames } from '@/lib/data/symbols'
import { loadLowRanks } from '@/lib/data/low-rank'
import { loadWatchOutlooks } from '@/lib/data/watch-outlook'
import { loadVerdicts, loadWatchlist } from '@/lib/data/watchlist'
import { addDays, todayInToronto } from '@/lib/dates'
import { fmtPrice } from '@/lib/format'
import { verdictGuide } from '@/lib/guidance'
import { outlookFor } from '@/lib/outlook'
import { portfolioView } from '@/lib/portfolio/view'
import { assetKey } from '@/lib/portfolio/types'
import { runTime } from '@/lib/runs'
import type { Supabase } from '@/lib/supabase/server'
import { marketOf } from '@/lib/symbols'
import { verdictHorizon, verdictWhy } from '@/lib/verdicts'

export const metadata: Metadata = { title: 'Watchlist' }

/** The portfolio's CAD value, which sizes a Buy like a pick; null when nothing is held. */
async function portfolioValue(supabase: Supabase): Promise<number | null> {
  const data = await loadPortfolio(supabase)
  const { totals } = portfolioView(
    {
      trades: data.trades,
      prices: data.prices,
      fx: data.fx,
      names: data.names,
      sectors: data.sectors,
      actions: [],
      guideline: { roundTrips: data.settings.tfsa_round_trips_warn, shortHoldShare: data.settings.tfsa_short_hold_share_warn },
    },
    todayInToronto(),
  )
  return totals.valueCad > 0 ? totals.valueCad : null
}

/** Watchlist (spec §9): add listed US and TSX stocks and coins from the search, or remove them, each with the latest run's verdict. */
export default async function WatchlistPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const items = await loadWatchlist(supabase)
  const [names, prices, fx, latest, lowRanks] = await Promise.all([
    loadNames(supabase, items.filter((i) => i.assetType === 'stock').map((i) => i.symbol)),
    // Watched symbols get a close every run, so two weeks back always reaches the latest one.
    loadCloses(supabase, items, addDays(todayInToronto(), -14)),
    loadFx(supabase),
    loadVerdicts(supabase),
    loadLowRanks(supabase, items.filter((i) => i.assetType === 'stock').map((i) => i.symbol)),
  ])
  const rate = fx.latest()?.usdCad ?? null
  const withVerdicts = latest !== null && latest.verdicts.size > 0
  const buys = latest !== null && [...latest.verdicts.values()].some((v) => v.verdict === 'buy')
  const [portfolioCad, outlooks] = await Promise.all([
    buys ? portfolioValue(supabase) : null,
    // the run the verdicts come from, so the chance and the verdict agree
    latest ? loadWatchOutlooks(supabase, latest.run.id, items) : new Map<string, never>(),
  ])
  const orders = { now: new Date(), usdCad: rate }

  const rows: WatchRow[] = items.map((item) => {
    const key = assetKey(item.assetType, item.symbol)
    const close = prices.latest(key)
    const previous = close ? prices.on(key, addDays(close.day, -1)) : null
    let price: string | null = null
    if (close && item.assetType === 'stock') price = fmtPrice(close.close, close.currency)
    // Coinbase closes are in USD; coins are shown in CAD like their holdings.
    else if (close && rate !== null) price = fmtPrice(close.currency === 'USD' ? close.close * rate : close.close, 'CAD')
    const market = item.assetType === 'crypto' ? null : marketOf(item.symbol)
    const v = latest?.verdicts.get(key) ?? null
    // held at the run: My Portfolio's action, so the two pages never disagree
    const held = latest?.held.get(key) ?? null
    // a held row shows My Portfolio's action; one added since the run waits for its first verdict
    const forecast = held || !v ? undefined : outlooks.get(key)
    // at the horizon the verdict was judged at, so an Avoid's chance is the one that made it an Avoid
    const at = forecast && v ? outlookFor(forecast.horizons, verdictHorizon(v)) : null
    return {
      symbol: item.symbol,
      assetType: item.assetType,
      name: names.get(item.symbol) ?? null,
      type: market ?? 'Crypto',
      price,
      move: close && previous && previous.close > 0 ? (close.close / previous.close - 1) * 100 : null,
      verdict: v?.verdict ?? null,
      held: held && { group: held.group, label: held.label },
      why: held ? held.why : v ? verdictWhy({ ...v, market }, 'long') : null,
      guide: !held && v && item.assetType === 'stock' ? verdictGuide(item.symbol, v, portfolioCad, orders) : null,
      lowRank: item.assetType === 'stock' ? (lowRanks.get(item.symbol) ?? null) : null,
      outlook: forecast && at ? { benchmark: forecast.benchmark, ...at } : null,
    }
  })

  return (
    <main className="page">
      <div className="page-head enter">
        <div style={{ minWidth: 0 }}>
          <h1>Watchlist</h1>
          <p className="sub">Any listed US or TSX stock, or one of the 300 biggest coins Coinbase trades. Watched symbols are priced first and get a verdict every run.</p>
        </div>
      </div>
      <section className="card card-pad enter" aria-labelledby="add-h">
        <h2 id="add-h" style={{ marginBottom: 12 }}>
          Add a symbol
        </h2>
        <AddWatch watched={items.map((i) => assetKey(i.assetType, i.symbol))} />
      </section>
      <section className="card card-pad enter" aria-labelledby="list-h">
        <div className="section-head">
          <h2 id="list-h">
            Watching <span className="count">{rows.length}</span>
          </h2>
          {withVerdicts && <span className="sub">verdicts from the {runTime(latest.run)} run</span>}
        </div>
        {!withVerdicts && (
          <div className="banner info" style={{ marginBottom: 12 }}>
            <Info />
            <div>Verdicts appear once the model runs. Until then, watched symbols are still priced first and collected.</div>
          </div>
        )}
        <WatchList rows={rows} withVerdicts={withVerdicts} />
        {rows.some((r) => r.guide !== null) && <OrderDisclaimer style={{ marginTop: 12 }} />}
      </section>
    </main>
  )
}
