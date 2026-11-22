import type { Metadata } from 'next'
import { BoughtButton, PickBuyDrawer } from '@/components/picks/BoughtButton'
import { OrderDisclaimer } from '@/components/OrderGuide'
import { MarketPicks, PicksEmpty, pickCount } from '@/components/picks/MarketPicks'
import { PicksTabs } from '@/components/picks/PicksTabs'
import { ExitEarlyCard, VerdictList } from '@/components/picks/VerdictList'
import { ownerClient } from '@/lib/auth'
import { loadBestChances } from '@/lib/data/best-chance'
import { loadPicks } from '@/lib/data/picks'
import { loadPortfolio } from '@/lib/data/portfolio'
import { todayInToronto } from '@/lib/dates'
import { pickGuide } from '@/lib/guidance'
import type { Market } from '@/lib/portfolio/types'
import { portfolioView } from '@/lib/portfolio/view'
import { KIND_LABEL, runTime } from '@/lib/runs'

export const metadata: Metadata = { title: "Today's Picks" }

/**
 * Today's Picks (spec §7.4, mockup picks_2.html): each market's Swing and Position picks from the
 * latest published run under a US | TSX control; when neither market picked anything, one empty
 * state with the run's best chance against the 58% bar; before any run, "No run yet".
 */
export default async function PicksPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const [{ run, markets, verdicts }, data] = await Promise.all([loadPicks(supabase), loadPortfolio(supabase)])
  const total = markets.reduce((sum, m) => sum + pickCount(m), 0)
  const chances = run && total === 0 ? await loadBestChances(supabase, run.id) : []

  const head = (
    <div className="page-head enter">
      <div style={{ minWidth: 0 }}>
        {run && <div className="label">From the {runTime(run)} {KIND_LABEL[run.kind].toLowerCase()} run</div>}
        <h1 style={{ marginTop: run ? 6 : 0 }}>Today&apos;s Picks</h1>
        <p className="sub">At most 10 Swing and 10 Position picks per market, 3 per sector.</p>
      </div>
    </div>
  )

  // a run's exit-early advice is never behind a tab: each market's card, always on screen
  const exits = markets.map((m) => <ExitEarlyCard key={m.market} market={m.market} exits={m.exitedEarly} />)

  if (!run || total === 0) {
    return (
      <main className="page">
        {head}
        <PicksEmpty run={run} chances={chances} markets={markets} />
        {exits}
      </main>
    )
  }

  const { totals } = portfolioView(
    {
      trades: data.trades,
      prices: data.prices,
      fx: data.fx,
      names: data.names,
      sectors: data.sectors,
      actions: [],
      guideline: {
        roundTrips: data.settings.tfsa_round_trips_warn,
        shortHoldShare: data.settings.tfsa_short_hold_share_warn,
      },
    },
    todayInToronto(),
  )
  const portfolioCad = totals.valueCad > 0 ? totals.valueCad : null
  const orders = { now: new Date(), usdCad: data.fx.latest()?.usdCad ?? null }
  const byMarket = (market: Market) => markets.find((m) => m.market === market)!
  const panel = (market: Market) => (
    <MarketPicks
      market={byMarket(market)}
      portfolioCad={portfolioCad}
      usdFxFeePct={data.settings.usd_fx_fee_pct}
      guideFor={(p) => pickGuide(p, portfolioCad, orders)}
      actionFor={(p) => <BoughtButton pick={{ id: p.id, symbol: p.symbol, entry: p.entry }} />}
    />
  )
  const guided = markets.some((m) => m.enabled && [...m.swing, ...m.position].some((p) => pickGuide(p, portfolioCad, orders) !== null))

  return (
    <main className="page">
      <PickBuyDrawer rates={[...data.fx.rates]} today={todayInToronto()}>
        {head}
        {exits}
        <PicksTabs
          counts={{ US: pickCount(byMarket('US')), TSX: pickCount(byMarket('TSX')) }}
          panels={{ US: panel('US'), TSX: panel('TSX') }}
        />
        {guided && <OrderDisclaimer />}
        <VerdictList verdicts={verdicts} />
        <p className="muted small picks-foot-note">
          No chance of beating the market is shown on a pick: the backtest says how its picks did. Not financial advice.
        </p>
      </PickBuyDrawer>
    </main>
  )
}
