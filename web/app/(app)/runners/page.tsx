import { Info } from 'lucide-react'
import type { Metadata } from 'next'
import Link from 'next/link'
import { BacktestCard } from '@/components/runners/BacktestCard'
import { RunnerCard } from '@/components/runners/RunnerCard'
import { RunnersRecord } from '@/components/runners/RunnersRecord'
import { ownerClient } from '@/lib/auth'
import { loadRunners } from '@/lib/data/runners'
import { addDays, shortDay } from '@/lib/dates'
import { fmtR, nyTime, priceOf, rTone } from '@/lib/daytrade'
import { NOTES, PAPER, TESTED, checkView, gate, rSoFar } from '@/lib/runners'
import { tickerHref } from '@/lib/ticker'

export const metadata: Metadata = { title: 'Runners' }

const DASH = '—'
const usd = (value: number | null) => (value === null ? DASH : priceOf(value, 'US'))

const weekdayOf = (day: string) => new Date(`${day}T12:00:00Z`).toLocaleDateString('en-CA', { weekday: 'long', timeZone: 'UTC' })

/** The latest weekday before `day` (the web has no holiday calendar). */
function weekdayBefore(day: string): string {
  let d = addDays(day, -1)
  while (['Saturday', 'Sunday'].includes(weekdayOf(d))) d = addDays(d, -1)
  return d
}

/**
 * Runners: US stocks under $5 whose huge-volume up day ("ignition") the pre-open run found yesterday,
 * planned as swing trades from today's open; the open ones with their R so far; the paper record after
 * costs; the weekly backtest; and the standing notes. Rule matches, not recommendations. Display only:
 * nothing here places an order or links to a broker. When this morning's check has not run or failed, it
 * says so and the cards are the last signals stored.
 */
export default async function RunnersPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const today = nyTime(new Date().toISOString()).day
  const data = await loadRunners(supabase)
  const { passed, reasons } = gate(data.version, data.backtest, data.closed, today)
  const signalDay = data.today[0]?.signalDay ?? weekdayBefore(today)
  const check = checkView(data.lastCheck, today)

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
          {check.current && <span className="label">enter at the open</span>}
        </div>
        {data.today.length === 0 ? (
          <div className="banner info">
            <Info />
            <div>{check.empty}</div>
          </div>
        ) : (
          <div className="dt-cards">
            {data.today.map((r) => (
              <RunnerCard key={r.id} runner={r} maxLossCad={data.maxLossCad} usdCad={data.usdCad} paper={!passed} />
            ))}
          </div>
        )}
      </section>
      <section className="card card-pad enter" aria-labelledby="rn-open-h">
        <div className="section-head" style={{ marginBottom: 4 }}>
          <h2 id="rn-open-h">Open runners</h2>
          <span className="label">as of the last close</span>
        </div>
        {data.open.length === 0 ? (
          <p className="sub" style={{ margin: 0 }}>
            No open runners.
          </p>
        ) : (
          <div className="dt-scroll">
            <table className="data-table dt-table" aria-labelledby="rn-open-h">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th className="r">R so far</th>
                  <th className="r">Entry</th>
                  <th className="r">Stop</th>
                  <th className="r">Target</th>
                  <th>Hold by</th>
                </tr>
              </thead>
              <tbody>
                {data.open.map((r) => {
                  const now = rSoFar(r)
                  return (
                    <tr key={r.id}>
                      <td>
                        <Link className="sym" href={tickerHref(r.symbol, 'stock')}>
                          {r.symbol}
                        </Link>
                      </td>
                      <td className={`r num ${rTone(now) ?? ''}`}>{now === null ? DASH : fmtR(now)}</td>
                      <td className="r num">{usd(r.entry)}</td>
                      <td className="r num">{usd(r.stop)}</td>
                      <td className="r num">{usd(r.target)}</td>
                      <td className="num">{shortDay(r.holdBy)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
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
