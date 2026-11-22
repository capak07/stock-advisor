import type { Metadata } from 'next'
import { OrderDisclaimer } from '@/components/OrderGuide'
import { ActionsCard, BreakdownCard, HoldingsCard, WarningsCard, type HoldingGuides } from '@/components/portfolio/Cards'
import { TradeButtons } from '@/components/portfolio/TradeForms'
import { TradeList } from '@/components/portfolio/TradeList'
import { ValueCard } from '@/components/portfolio/ValueCard'
import { ownerClient } from '@/lib/auth'
import { loadHoldingActions } from '@/lib/data/actions'
import { loadLowRanks } from '@/lib/data/low-rank'
import { loadPortfolio, portfolioViewOf } from '@/lib/data/portfolio'
import { todayInToronto } from '@/lib/dates'
import { holdingGuides } from '@/lib/guidance'
import { assetKey } from '@/lib/portfolio/types'
import { tradeList } from '@/lib/portfolio/trade-list'

export const metadata: Metadata = { title: 'My Portfolio' }

/**
 * My Portfolio (spec §7.2): the value hero, then the holdings, the latest run's actions and the trades beside the
 * breakdown and warnings. The news is on Today.
 */
export default async function PortfolioPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const [data, latest] = await Promise.all([loadPortfolio(supabase), loadHoldingActions(supabase)])
  const today = todayInToronto()
  const view = portfolioViewOf(data, latest?.actions ?? [], today)
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
  const lowRanks = await loadLowRanks(
    supabase,
    view.holdings.flatMap((h) => (h.action?.assetType === 'stock' ? [h.action.symbol] : [])),
  )
  const accounts = view.accounts.length === 0 ? 'No accounts yet' : `${view.accounts.join(' and ')} accounts`
  const rate = view.fx ? ` (${view.fx.usdCad.toFixed(4)})` : ''

  return (
    <main className="page">
      <div className="page-head enter">
        <div>
          <div className="label">
            {accounts} · values in CAD at the latest Bank of Canada rate{rate}
          </div>
          <h1 style={{ marginTop: 6 }}>My Portfolio</h1>
        </div>
        <TradeButtons sellable={view.sellable} rates={[...data.fx.rates]} today={today} existing={data.trades} />
      </div>
      <ValueCard totals={view.totals} periods={view.periods} firstBuy={view.firstBuy} />
      <section className="portfolio-grid">
        <div className="portfolio-col">
          <HoldingsCard holdings={view.holdings} accounts={view.accounts.length} guides={guides} qtys={qtyOf} asOf={latest?.day ?? null} today={today} />
          <ActionsCard holdings={view.holdings} asOf={latest?.day ?? null} guides={guides} lowRanks={lowRanks} />
          {[...guides.values()].some((g) => (g.order?.steps.length ?? 0) + (g.stop?.steps.length ?? 0) > 0) && <OrderDisclaimer />}
          {data.trades.length > 0 && (
            <TradeList lines={tradeList(data.trades, data.fx)} rates={[...data.fx.rates]} today={today} />
          )}
        </div>
        <aside className="portfolio-col">
          <BreakdownCard byRisk={view.byRisk} byMarket={view.byMarket} byAccount={view.byAccount} />
          <WarningsCard warnings={view.warnings} />
        </aside>
      </section>
    </main>
  )
}
