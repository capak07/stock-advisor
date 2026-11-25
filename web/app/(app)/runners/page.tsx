import { Info } from 'lucide-react'
import type { Metadata } from 'next'
import { BacktestCard } from '@/components/runners/BacktestCard'
import { FinishedRunners } from '@/components/runners/FinishedRunners'
import { OpenRunnerCard } from '@/components/runners/OpenRunnerCard'
import { RunnerCard } from '@/components/runners/RunnerCard'
import { RunnersRecord } from '@/components/runners/RunnersRecord'
import { ownerClient } from '@/lib/auth'
import { loadRunners } from '@/lib/data/runners'
import { addDays } from '@/lib/dates'
import { nyTime } from '@/lib/daytrade'
import { NOTES, PAPER, TESTED, checkView, gate } from '@/lib/runners'
import { fetchRunnerQuotes, liveRunners } from '@/lib/runners-live'

export const metadata: Metadata = { title: 'Runners' }

const weekdayOf = (day: string) => new Date(`${day}T12:00:00Z`).toLocaleDateString('en-CA', { weekday: 'long', timeZone: 'UTC' })

/** The latest weekday before `day` (the web has no holiday calendar). */
function weekdayBefore(day: string): string {
  let d = addDays(day, -1)
  while (['Saturday', 'Sunday'].includes(weekdayOf(d))) d = addDays(d, -1)
  return d
}

/**
 * Runners: US stocks under $5 whose huge-volume up day ("ignition") the pre-open run found yesterday,
 * planned as swing trades from today's open; the open ones as 100-share paper positions in US$ with their R so far;
 * the finished paper trades in US$; the paper record after costs; the weekly backtest; and the standing notes. Rule matches, not recommendations. Display only:
 * nothing here places an order or links to a broker. When this morning's check has not run or failed, it
 * says so and the cards are the last signals stored. Between the checks, the signal and open cards add Yahoo's
 * prices (lib/runners-live): the paper trade bought at the open and what it is worth now or at the close.
 */
export default async function RunnersPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const today = nyTime(new Date().toISOString()).day
  const data = await loadRunners(supabase)
  const { passed, reasons } = gate(data.version, data.backtest, data.closed, today)
  const signalDay = data.today[0]?.signalDay ?? weekdayBefore(today)
  const check = checkView(data.lastCheck, today)
  const shown = [...data.today, ...data.open]
  const live = liveRunners(shown, await fetchRunnerQuotes(shown.map((r) => r.symbol)), data.rules)
  const boughtToday = data.today.some((r) => ['open', 'exited'].includes(live.get(r.id)?.kind ?? ''))
  const openLive = data.open.some((r) => live.has(r.id))

  return (
    <main className="page">
      <div className="page-head enter">
        <div style={{ minWidth: 0 }}>
          <div className="label">Under $5 · swing trades · signals from {weekdayOf(signalDay)}&apos;s close</div>
          <h1 style={{ marginTop: 6 }}>Runners</h1>
          <p className="dt-status">
            <span className="pill" data-testid="runners-gate">
              <span className={`dot ${passed ? 'validated' : 'paper'}`} />
              {passed ? TESTED : PAPER}
            </span>
          </p>
          {!passed && (
            <ul className="dt-notes" data-testid="runners-gate-reasons">
              {reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
          {check.lines.map((line) => (
            <p key={line.text} className="dt-status">
              <span className={`dot ${line.failed ? 'failed' : 'skipped'}`} />
              <span>{line.text}</span>
            </p>
          ))}
        </div>
      </div>
      <section className="dt-stack enter" aria-labelledby="rn-today-h">
        <div className="section-head">
          <h2 id="rn-today-h">{check.current ? "Today's signals" : 'Last signals'}</h2>
          {check.current && <span className="label">{boughtToday ? 'bought at the open' : 'enter at the open'}</span>}
        </div>
        {data.today.length === 0 ? (
          <div className="banner info">
            <Info />
            <div>{check.empty}</div>
          </div>
        ) : (
          <div className="dt-cards">
            {data.today.map((r) => (
              <RunnerCard
                key={r.id}
                runner={r}
                maxLossCad={data.maxLossCad}
                usdCad={data.usdCad}
                paper={!passed}
                live={live.get(r.id) ?? null}
              />
            ))}
          </div>
        )}
      </section>
      <section className="dt-stack enter" aria-labelledby="rn-open-h">
        <div className="section-head">
          <h2 id="rn-open-h">Open runners</h2>
          <span className="label">{openLive ? 'latest prices from Yahoo' : 'as of the last close'}</span>
        </div>
        {data.open.length === 0 ? (
          <div className="banner info">
            <Info />
            <div>No open runners.</div>
          </div>
        ) : (
          <div className="dt-cards">
            {data.open.map((r) => (
              <OpenRunnerCard key={r.id} runner={r} live={live.get(r.id) ?? null} />
            ))}
          </div>
        )}
      </section>
      <FinishedRunners closed={data.closed} version={data.version} />
      <div className="dt-two enter">
        <RunnersRecord closed={data.closed} version={data.version} today={today} />
        <BacktestCard backtest={data.backtest} />
      </div>
      <section className="card card-pad enter" aria-labelledby="rn-notes-h">
        <div className="section-head" style={{ marginBottom: 4 }}>
          <h2 id="rn-notes-h">Notes</h2>
        </div>
        <ul className="dt-notes">
          {NOTES.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </section>
    </main>
  )
}
