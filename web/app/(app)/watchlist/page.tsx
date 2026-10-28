import { Info } from 'lucide-react'
import type { Metadata } from 'next'
import { OrderDisclaimer } from '@/components/OrderGuide'
import { AddWatch, WatchList, type WatchRow } from '@/components/watchlist/Watchlist'
import { ownerClient } from '@/lib/auth'
import { loadCloses, loadFx, loadPortfolio } from '@/lib/data/portfolio'
import { loadNames } from '@/lib/data/symbols'
import { loadVerdicts, loadWatchlist } from '@/lib/data/watchlist'
import { addDays, todayInToronto } from '@/lib/dates'
import { fmtPrice } from '@/lib/format'
import { verdictGuide } from '@/lib/guidance'
import { portfolioView } from '@/lib/portfolio/view'
import { assetKey } from '@/lib/portfolio/types'
import { runTime } from '@/lib/runs'
import type { Supabase } from '@/lib/supabase/server'
import { marketOf } from '@/lib/symbols'
import { verdictWhy } from '@/lib/verdicts'

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
  const [names, prices, fx, latest] = await Promise.all([
    loadNames(supabase, items.filter((i) => i.assetType === 'stock').map((i) => i.symbol)),
    // Watched symbols get a close every run, so two weeks back always reaches the latest one.
    loadCloses(supabase, items, addDays(todayInToronto(), -14)),
    loadFx(supabase),
    loadVerdicts(supabase),
  ])
  const rate = fx.latest()?.usdCad ?? null
  const withVerdicts = latest !== null && latest.verdicts.size > 0
  const buys = latest !== null && [...latest.verdicts.values()].some((v) => v.verdict === 'buy')
  const portfolioCad = buys ? await portfolioValue(supabase) : null
  const orders = { now: new Date(), usdCad: rate }

  const rows: WatchRow[] = items.map((item) => {
    const close = prices.latest(assetKey(item.assetType, item.symbol))
    let price: string | null = null
    if (close && item.assetType === 'stock') price = fmtPrice(close.close, close.currency)
    // Coinbase closes are in USD; coins are shown in CAD like their holdings.
    else if (close && rate !== null) price = fmtPrice(close.currency === 'USD' ? close.close * rate : close.close, 'CAD')
    const market = item.assetType === 'crypto' ? null : marketOf(item.symbol)
    const v = latest?.verdicts.get(assetKey(item.assetType, item.symbol)) ?? null
    return {
      symbol: item.symbol,
      assetType: item.assetType,
      name: names.get(item.symbol) ?? null,
      type: market ?? 'Crypto',
      price,
      verdict: v?.verdict ?? null,
      why: v ? verdictWhy({ ...v, market }, 'long') : null,
      guide: v && item.assetType === 'stock' ? verdictGuide(item.symbol, v, portfolioCad, orders) : null,
    }
  })

  return (
    <main className="page">
      <div className="enter">
        <h1>Watchlist</h1>
        <p className="sub">Any listed US or TSX stock, or one of the 300 biggest coins Coinbase trades. Watched symbols are priced first and get a verdict every run.</p>
      </div>
      <section className="card card-pad enter" aria-labelledby="add-h">
        <h2 id="add-h" style={{ marginBottom: 12 }}>
          Add a symbol
        </h2>
        <AddWatch watched={items.map((i) => assetKey(i.assetType, i.symbol))} />
      </section>
      <section className="card card-pad enter" aria-labelledby="list-h">
        <div className="section-head">
          <h2 id="list-h">Watching {rows.length}</h2>
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
