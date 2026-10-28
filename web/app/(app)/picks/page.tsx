import { Sparkles } from 'lucide-react'
import type { Metadata } from 'next'
import Link from 'next/link'
import { BoughtButton, PickBuyDrawer } from '@/components/picks/BoughtButton'
import { MarketPicks } from '@/components/picks/MarketPicks'
import { PicksTabs } from '@/components/picks/PicksTabs'
import { ownerClient } from '@/lib/auth'
import { loadPicks } from '@/lib/data/picks'
import { loadPortfolio } from '@/lib/data/portfolio'
import { todayInToronto } from '@/lib/dates'
import { portfolioView } from '@/lib/portfolio/view'
import { KIND_LABEL, runTime } from '@/lib/runs'

export const metadata: Metadata = { title: "Today's Picks" }

/** Today's Picks (spec §9): each market's Swing and Position picks from the latest published run. */
export default async function PicksPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const [{ run, markets, verdicts }, data] = await Promise.all([loadPicks(supabase), loadPortfolio(supabase)])

  if (!run) {
    return (
      <main className="page">
        <div className="enter">
          <h1>Today&apos;s Picks</h1>
          <p className="sub">At most 10 Swing and 10 Position picks per market, 3 per sector</p>
        </div>
        <div className="card enter">
          <div className="empty">
            <Sparkles />
            <strong>No picks yet</strong>
            <span style={{ maxWidth: 460 }}>
              Picks appear once the model runs. Until then nothing here is a suggestion to buy. Your holdings are on My
              Portfolio.
            </span>
            <Link className="btn btn-secondary btn-sm" href="/" style={{ marginTop: 6 }}>
              Go to My Portfolio
            </Link>
          </div>
        </div>
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
  const panel = (market: 'US' | 'TSX') => {
    const picks = markets.find((m) => m.market === market)!
    return (
      <MarketPicks
        market={picks}
        verdicts={verdicts}
        portfolioCad={portfolioCad}
        usdFxFeePct={data.settings.usd_fx_fee_pct}
        actionFor={(p) => <BoughtButton pick={{ id: p.id, symbol: p.symbol, entry: p.entry }} />}
      />
    )
  }

  return (
    <main className="page">
      <PickBuyDrawer rates={[...data.fx.rates]} today={todayInToronto()}>
        <PicksTabs
          head={
            <div>
              <h1>Today&apos;s Picks</h1>
              <p className="sub">
                From the {runTime(run)} {KIND_LABEL[run.kind].toLowerCase()} run · at most 10 Swing and 10 Position picks
                per market, 3 per sector
              </p>
            </div>
          }
          panels={{ US: panel('US'), TSX: panel('TSX') }}
        />
      </PickBuyDrawer>
    </main>
  )
}
