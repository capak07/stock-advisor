import { Info } from 'lucide-react'
import type { Metadata } from 'next'
import { AutoRefresh } from '@/components/daytrade/AutoRefresh'
import { SignalCard } from '@/components/daytrade/SignalCard'
import { SignalTable } from '@/components/daytrade/SignalTable'
import { TrackRecord } from '@/components/daytrade/TrackRecord'
import { ownerClient } from '@/lib/auth'
import { loadDaytrade } from '@/lib/data/daytrade'
import {
  COSTS_TITLE,
  NOTES,
  NO_SIGNALS,
  SKILL_SUB,
  SKILL_TITLE,
  isFresh,
  isLive,
  noTradeLine,
  nyTime,
  skillSignals,
  statusLine,
} from '@/lib/daytrade'
import { longDay } from '@/lib/dates'

export const metadata: Metadata = { title: 'Day trade' }

/**
 * Day trade: today's opening-range breakouts on US and TSX stocks, as the pipeline finds, replays,
 * ranks and tracks them every 5 minutes (9:50 AM to 3:30 PM ET). Two top 3s: the skill's (the
 * strongest breakouts, frozen as found, before costs) and the one ranked by track record after the
 * owner's costs, each with its track record. Display only: nothing here places an order or links to a broker.
 */
export default async function DaytradePage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const now = new Date().toISOString()
  const today = nyTime(now).day
  const data = await loadDaytrade(supabase, today)
  const { day, signals } = data
  const skill = skillSignals(signals)
  const top = signals.filter((s) => s.rank !== null)
  // a day that has run a cycle says so when nothing made the top 3
  const ran = day !== null && (day.status === 'scanning' || day.status === 'done' || (day.status === 'failed' && day.lastUpdate !== null))

  return (
    <main className="page">
      <div className="enter">
        <h1>Day trade</h1>
        <p className="sub">
          Opening-range breakouts on US and TSX stocks, checked every 5 minutes from 9:50 AM to 3:30 PM. Times are New
          York&apos;s.
        </p>
        <p className="dt-status" style={{ marginTop: 10 }}>
          <span className={`dot ${day?.status === 'failed' ? 'failed' : day?.status === 'scanning' ? 'ok' : 'skipped'}`} />
          <span>
            <span className="sub">{longDay(today)} · </span>
            <span data-testid="daytrade-status">{statusLine(day, now)}</span>
          </span>
        </p>
      </div>
      <section className="card card-pad enter" aria-labelledby="dt-skill-h">
        <div className="section-head" style={{ marginBottom: 6 }}>
          <h2 id="dt-skill-h">{SKILL_TITLE}</h2>
        </div>
        <p className="sub" style={{ margin: 0 }}>
          {SKILL_SUB}
        </p>
        {skill.length === 0 ? (
          <div className="banner info" style={{ marginTop: 12 }}>
            <Info />
            <div>{NO_SIGNALS}</div>
          </div>
        ) : (
          <div className="pick-grid" style={{ marginTop: 12 }}>
            {skill.map((s) => (
              <SignalCard
                key={s.id}
                signal={s}
                list="skill"
                fresh={isFresh(s.triggerAt, now)}
                maxLossCad={data.maxLossCad}
                usdCad={data.usdCad}
              />
            ))}
          </div>
        )}
      </section>
      <section className="card card-pad enter" aria-labelledby="dt-top-h">
        <div className="section-head" style={{ marginBottom: 6 }}>
          <h2 id="dt-top-h">{COSTS_TITLE}</h2>
        </div>
        {ran && top.length === 0 && (
          <div className="banner info" style={{ marginTop: 12 }}>
            <Info />
            <div>{noTradeLine(signals.length)}</div>
          </div>
        )}
        {top.length > 0 && (
          <div className="pick-grid" style={{ marginTop: 12 }}>
            {top.map((s) => (
              <SignalCard key={s.id} signal={s} fresh={isFresh(s.triggerAt, now)} maxLossCad={data.maxLossCad} usdCad={data.usdCad} />
            ))}
          </div>
        )}
      </section>
      {signals.length > 0 && <SignalTable signals={signals} />}
      <TrackRecord record={data.record} />
      <section className="card card-pad enter" aria-label="Notes">
        <ul className="dt-notes">
          {NOTES.map((note) => (
            <li key={note} className="sub">
              {note}
            </li>
          ))}
        </ul>
      </section>
      {isLive(day, now) && <AutoRefresh />}
    </main>
  )
}
