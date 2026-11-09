import type { Metadata } from 'next'
import { OrderDisclaimer } from '@/components/OrderGuide'
import { ActionsCard, BreakdownCard, HoldingsCard, WarningsCard, type HoldingGuides } from '@/components/portfolio/Cards'
import { TradeButtons } from '@/components/portfolio/TradeForms'
import { TradeList } from '@/components/portfolio/TradeList'
import { MonitorCard } from '@/components/portfolio/MonitorCard'
import { ValueCard } from '@/components/portfolio/ValueCard'
import { ownerClient } from '@/lib/auth'
import { loadHoldingActions } from '@/lib/data/actions'
import { loadMonitorFeed } from '@/lib/data/monitor'
import { loadPortfolio } from '@/lib/data/portfolio'
import { todayInToronto } from '@/lib/dates'
import { holdingGuides } from '@/lib/guidance'
import { assetKey } from '@/lib/portfolio/types'
import { tradeList } from '@/lib/portfolio/trade-list'
import { portfolioView } from '@/lib/portfolio/view'

export const metadata: Metadata = { title: 'My Portfolio' }

/** My Portfolio, the home page (spec §9): values, returns, the latest run's actions, warnings. */
export default async function PortfolioPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const [data, latest, feed] = await Promise.all([loadPortfolio(supabase), loadHoldingActions(supabase), loadMonitorFeed(supabase)])
  const today = todayInToronto()
  const view = portfolioView(
    {
      trades: data.trades,
      prices: data.prices,
      fx: data.fx,
      names: data.names,
      sectors: data.sectors,
      actions: latest?.actions ?? [],
      guideline: {
        roundTrips: data.settings.tfsa_round_trips_warn,
        shortHoldShare: data.settings.tfsa_short_hold_share_warn,
      },
    },
    today,
  )
  const orders = { now: new Date(), usdCad: view.fx?.usdCad ?? null }
  const qtyOf = new Map(view.sellable.map((s) => [s.key, s.qty]))
  const guides: HoldingGuides = new Map(
    view.holdings.flatMap((h) => {
      const qty = qtyOf.get(h.key)
      if (h.action === null || qty === undefined) return []
      const latest = data.prices.latest(assetKey(h.action.assetType, h.action.symbol)) // live after a Refresh
      return [[h.key, holdingGuides(h.action, { qty, valueCad: h.valueCad, portfolioCad: view.totals.valueCad, latest }, orders)]]
    }),
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
        <div className="grid gap-4">
          <ActionsCard holdings={view.holdings} asOf={latest?.day ?? null} guides={guides} />
          <MonitorCard items={feed} />
        </div>
        <aside className="grid gap-4">
          <WarningsCard warnings={view.warnings} />
          <BreakdownCard byRisk={view.byRisk} byMarket={view.byMarket} byAccount={view.byAccount} />
        </aside>
      </section>
      <HoldingsCard holdings={view.holdings} accounts={view.accounts.length} guides={guides} />
      {[...guides.values()].some((g) => (g.order?.steps.length ?? 0) + (g.stop?.steps.length ?? 0) > 0) && <OrderDisclaimer />}
      {data.trades.length > 0 && (
        <TradeList lines={tradeList(data.trades, data.fx)} rates={[...data.fx.rates]} today={today} />
      )}
    </main>
  )
}
