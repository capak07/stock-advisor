import type { Metadata } from 'next'
import Link from 'next/link'
import { ResultsCard } from '@/components/portfolio/ResultsCard'
import { TradeList } from '@/components/portfolio/TradeList'
import { ownerClient } from '@/lib/auth'
import { loadPortfolio } from '@/lib/data/portfolio'
import { loadSettings } from '@/lib/data/settings'
import { todayInToronto } from '@/lib/dates'
import { stockResults } from '@/lib/portfolio/results'
import { tradeList } from '@/lib/portfolio/trade-list'

export const metadata: Metadata = { title: 'History' }

/**
 * History (owner request 2026-11-23): Results by stock, before and after tax, then every trade with Edit and Delete.
 * Both moved here from My Portfolio, which keeps the Buy and Sell buttons.
 */
export default async function HistoryPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const [data, settings] = await Promise.all([loadPortfolio(supabase), loadSettings(supabase)])
  const today = todayInToronto()

  return (
    <main className="page">
      <div className="page-head enter">
        <div>
          <div className="label">Every trade · results in CAD</div>
          <h1 style={{ marginTop: 6 }}>History</h1>
        </div>
      </div>
      {data.trades.length === 0 ? (
        <section className="card card-pad enter">
          <p className="sub" style={{ margin: 0 }}>
            No trades yet. Add your first buy on <Link href="/portfolio">My Portfolio</Link>.
          </p>
        </section>
      ) : (
        <div className="portfolio-col">
          <ResultsCard results={stockResults(data.trades, data.prices, data.fx)} taxPct={settings.marginal_tax_pct} />
          <TradeList lines={tradeList(data.trades, data.fx)} rates={[...data.fx.rates]} today={today} />
        </div>
      )}
    </main>
  )
}
