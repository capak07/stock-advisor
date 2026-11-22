import type { Metadata } from 'next'
import { MonitorCard } from '@/components/portfolio/MonitorCard'
import { AttentionCard } from '@/components/today/AttentionCard'
import { DaytradeTop } from '@/components/today/DaytradeTop'
import { PicksStatus } from '@/components/today/PicksStatus'
import { PortfolioSummary } from '@/components/today/PortfolioSummary'
import { ownerClient } from '@/lib/auth'
import { loadHoldingActions } from '@/lib/data/actions'
import { loadBestChances } from '@/lib/data/best-chance'
import { loadDaytrade } from '@/lib/data/daytrade'
import { loadMonitorFeed } from '@/lib/data/monitor'
import { loadPicks } from '@/lib/data/picks'
import { loadPortfolio, portfolioViewOf } from '@/lib/data/portfolio'
import { shortDay, todayInToronto } from '@/lib/dates'
import { nyTime } from '@/lib/daytrade'
import { runWhen } from '@/lib/runs'
import { bestChanceLine, needsAttention, todayLine } from '@/lib/today'

export const metadata: Metadata = { title: 'Today' }

/**
 * Today, the home page (spec §7.1): the date and market state, the portfolio at a glance, what needs
 * attention, the news on the owner's stocks, the day trade top 3 after costs and the picks' status.
 * Phone: one column in that order. Desktop: the summary full width, then two columns.
 */
export default async function TodayPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const now = new Date().toISOString()
  // the Day trade page's day, data and live logic
  const [data, latest, feed, daytrade, picks] = await Promise.all([
    loadPortfolio(supabase),
    loadHoldingActions(supabase),
    loadMonitorFeed(supabase),
    loadDaytrade(supabase, nyTime(now).day),
    loadPicks(supabase),
  ])
  const view = portfolioViewOf(data, latest?.actions ?? [], todayInToronto())
  const attention = needsAttention(view.holdings)
  const top = daytrade.signals.filter((s) => s.rank !== null)
  const picked = picks.markets.some((m) => m.swing.length + m.position.length > 0)
  // the best chance only shows when nothing was picked
  const bestChance = picks.run && !picked ? bestChanceLine(await loadBestChances(supabase, picks.run.id)) : null

  return (
    <main className="page">
      <div className="page-head enter">
        <div>
          <div className="label" data-testid="today-line">
            {todayLine(daytrade.day, now)}
          </div>
          <h1 style={{ marginTop: 6 }}>Today</h1>
          <p className="sub">{picks.run ? `Last run ${runWhen(picks.run)}` : 'No run yet'}</p>
        </div>
      </div>
      <PortfolioSummary totals={view.totals} periods={view.periods} accounts={view.accounts} holdings={view.holdings.length} />
      <div className="today-grid">
        <div className="today-col">
          <AttentionCard
            items={attention.items}
            onHold={attention.onHold}
            warnings={view.warnings}
            asOf={latest ? `as of ${shortDay(latest.day)}` : null}
          />
          <MonitorCard items={feed} limit={3} />
        </div>
        <div className="today-col">
          <DaytradeTop day={daytrade.day} top={top} signals={daytrade.signals.length} now={now} />
          <PicksStatus run={picks.run} markets={picks.markets} bestChance={bestChance} />
        </div>
      </div>
    </main>
  )
}
