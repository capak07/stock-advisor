import { Info } from 'lucide-react'
import type { Metadata } from 'next'
import { AddWatch, WatchList, type WatchRow } from '@/components/watchlist/Watchlist'
import { ownerClient } from '@/lib/auth'
import { loadCloses, loadFx } from '@/lib/data/portfolio'
import { loadNames } from '@/lib/data/symbols'
import { loadWatchlist } from '@/lib/data/watchlist'
import { addDays, todayInToronto } from '@/lib/dates'
import { fmtPrice } from '@/lib/format'
import { assetKey } from '@/lib/portfolio/types'
import { marketOf } from '@/lib/symbols'

export const metadata: Metadata = { title: 'Watchlist' }

/** Watchlist (spec §9): add listed US and TSX stocks and coins from the search, or remove them. Verdicts come with the model. */
export default async function WatchlistPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const items = await loadWatchlist(supabase)
  const [names, prices, fx] = await Promise.all([
    loadNames(supabase, items.filter((i) => i.assetType === 'stock').map((i) => i.symbol)),
    // Watched symbols get a close every run, so two weeks back always reaches the latest one.
    loadCloses(supabase, items, addDays(todayInToronto(), -14)),
    loadFx(supabase),
  ])
  const rate = fx.latest()?.usdCad ?? null

  const rows: WatchRow[] = items.map((item) => {
    const close = prices.latest(assetKey(item.assetType, item.symbol))
    let price: string | null = null
    if (close && item.assetType === 'stock') price = fmtPrice(close.close, close.currency)
    // Coinbase closes are in USD; coins are shown in CAD like their holdings.
    else if (close && rate !== null) price = fmtPrice(close.currency === 'USD' ? close.close * rate : close.close, 'CAD')
    return {
      symbol: item.symbol,
      assetType: item.assetType,
      name: names.get(item.symbol) ?? null,
      type: item.assetType === 'crypto' ? 'Crypto' : marketOf(item.symbol),
      price,
    }
  })

  return (
    <main className="page">
      <div className="enter">
        <h1>Watchlist</h1>
        <p className="sub">Any listed US or TSX stock, or one of the 300 biggest coins. Watched symbols are priced first and get a verdict every run.</p>
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
        </div>
        <div className="banner info" style={{ marginBottom: 12 }}>
          <Info />
          <div>Verdicts appear once the model runs. Until then, watched symbols are still priced first and collected.</div>
        </div>
        <WatchList rows={rows} />
      </section>
    </main>
  )
}
