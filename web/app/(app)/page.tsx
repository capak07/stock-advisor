import type { Metadata } from 'next'
import { ActionsCard, BreakdownCard, HoldingsCard, WarningsCard } from '@/components/portfolio/Cards'
import { TradeButtons } from '@/components/portfolio/TradeForms'
import { TradeList } from '@/components/portfolio/TradeList'
import { ValueCard } from '@/components/portfolio/ValueCard'
import { ownerClient } from '@/lib/auth'
import { loadPortfolio } from '@/lib/data/portfolio'
import { todayInToronto } from '@/lib/dates'
import { tradeList } from '@/lib/portfolio/trade-list'
import { portfolioView } from '@/lib/portfolio/view'

export const metadata: Metadata = { title: 'My Portfolio' }

/** My Portfolio, the home page (spec §9), as it stands before the model: values, returns, warnings. */
export default async function PortfolioPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const data = await loadPortfolio(supabase)
  const today = todayInToronto()
  const view = portfolioView(
    {
      trades: data.trades,
      prices: data.prices,
      fx: data.fx,
      names: data.names,
      guideline: {
        roundTrips: data.settings.tfsa_round_trips_warn,
        shortHoldShare: data.settings.tfsa_short_hold_share_warn,
      },
    },
    today,
  )
  const accounts = view.accounts.length === 0 ? 'No accounts yet' : `${view.accounts.join(' and ')} accounts`
  const rate = view.fx ? ` (${view.fx.usdCad.toFixed(4)})` : ''

  return (
    <main className="page">
      <div className="section-head enter" style={{ marginBottom: 0 }}>
        <div>
          <h1>My Portfolio</h1>
          <p className="sub">
            {accounts} · values in CAD at the latest Bank of Canada rate{rate}
          </p>
        </div>
        <TradeButtons sellable={view.sellable} rates={[...data.fx.rates]} today={today} existing={data.trades} />
      </div>
      <ValueCard totals={view.totals} periods={view.periods} firstBuy={view.firstBuy} />
      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_330px]" style={{ alignItems: 'start' }}>
        <ActionsCard />
        <aside className="grid gap-4">
          <WarningsCard warnings={view.warnings} />
          <BreakdownCard byMarket={view.byMarket} byAccount={view.byAccount} />
        </aside>
      </section>
      <HoldingsCard holdings={view.holdings} accounts={view.accounts.length} />
      {data.trades.length > 0 && <TradeList lines={tradeList(data.trades, data.fx)} />}
    </main>
  )
}
