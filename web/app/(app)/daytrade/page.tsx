import { Info } from 'lucide-react'
import type { Metadata } from 'next'
import { AutoRefresh } from '@/components/daytrade/AutoRefresh'
import { SignalCard } from '@/components/daytrade/SignalCard'
import { loadLowRanks } from '@/lib/data/low-rank'
import { SignalTable } from '@/components/daytrade/SignalTable'
import { TrackRecord } from '@/components/daytrade/TrackRecord'
import { ownerClient } from '@/lib/auth'
import { loadDaytrade } from '@/lib/data/daytrade'
import {
  COSTS_TITLE,
  NOTES,
  NOTE_COSTS,
  NOTE_RULES,
  SKILL_SUB,
  SKILL_TITLE,
  hasRun,
  isFresh,
  isLive,
  noTradeLine,
  nyTime,
  skillEmptyLine,
  skillSignals,
  statusLine,
} from '@/lib/daytrade'
import { longDay } from '@/lib/dates'

export const metadata: Metadata = { title: 'Day trade' }

const NOTE_BLOCKS = [
  ['Costs', NOTE_COSTS],
  ['Rules', NOTE_RULES],
  ['Limits', NOTES],
] as const

/**
 * Day trade (spec §7.3, daytrade_1.html): today's opening-range breakouts on US and TSX stocks, as the
 * pipeline finds, replays, ranks and tracks them every 5 minutes (9:50 AM to 3:30 PM ET). The top 3
 * after the owner's costs side by side (ranked by track record), the skill's top 3 (the strongest
 * breakouts, frozen as found, before costs) in smaller cards, every signal in a collapsed table, then
 * the track record beside the notes. Display only: nothing here places an order or links to a broker.
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
  const lowRanks = await loadLowRanks(supabase, [...skill, ...top].filter((s) => s.market === 'US').map((s) => s.symbol))
  // a day that has run a cycle says so when nothing made a top 3
  const ran = hasRun(day)
  const live = isLive(day, now)

  return (
    <main className="page">
      <div className="page-head enter">
        <div style={{ minWidth: 0 }}>
          <div className="label">{longDay(today)} · New York time</div>
          <h1 style={{ marginTop: 6 }}>Day trade</h1>
          <p className="sub">Opening-range breakouts on US and TSX stocks, checked every 5 minutes from 9:50 AM to 3:30 PM.</p>
          <p className="dt-status">
            <span className={`dot ${day?.status === 'failed' ? 'failed' : day?.status === 'scanning' ? 'ok' : 'skipped'}`} />
            <span data-testid="daytrade-status">{statusLine(day, now)}</span>
          </p>
        </div>
        {live && (
          <span className="pill" data-testid="daytrade-live">
            <span className="dot ok live" />
            Live · updates every minute
          </span>
        )}
      </div>
      <section className="dt-stack enter" aria-labelledby="dt-top-h">
        <div className="section-head">
          <h2 id="dt-top-h">{COSTS_TITLE}</h2>
          <span className="label">ranked by track record, net of costs</span>
        </div>
        {ran && top.length === 0 && (
          <div className="banner info">
            <Info />
            <div>{noTradeLine(signals.length)}</div>
          </div>
        )}
        {top.length > 0 && (
          <div className="dt-cards">
            {top.map((s) => (
              <SignalCard
                key={s.id}
                signal={s}
                fresh={isFresh(s.triggerAt, now)}
                maxLossCad={data.maxLossCad}
                usdCad={data.usdCad}
                lowRank={s.market === 'US' ? (lowRanks.get(s.symbol) ?? null) : null}
              />
            ))}
          </div>
        )}
      </section>
      <section className="dt-stack enter" aria-labelledby="dt-skill-h">
        <div className="section-head">
          <h2 id="dt-skill-h">{SKILL_TITLE}</h2>
        </div>
        <p className="sub dt-skill-sub">{SKILL_SUB}</p>
        {skill.length === 0 ? (
          ran && (
            <div className="banner info">
              <Info />
              <div>{skillEmptyLine(signals.length)}</div>
            </div>
          )
        ) : (
          <div className="dt-cards">
            {skill.map((s) => (
              <SignalCard
                key={s.id}
                signal={s}
                list="skill"
                fresh={isFresh(s.triggerAt, now)}
                maxLossCad={data.maxLossCad}
                usdCad={data.usdCad}
                lowRank={lowRanks.get(s.symbol) ?? null}
              />
            ))}
          </div>
        )}
      </section>
      {signals.length > 0 && <SignalTable signals={signals} />}
      <div className="dt-two enter">
        <TrackRecord record={data.record} />
        <section className="card card-pad" aria-labelledby="dt-notes-h">
          <div className="section-head" style={{ marginBottom: 4 }}>
            <h2 id="dt-notes-h">Notes: costs, rules, limits</h2>
          </div>
          {NOTE_BLOCKS.map(([title, notes]) => (
            <div className="dt-note-block" key={title}>
              <div className="label">{title}</div>
              <ul className="dt-notes">
                {notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      </div>
      {live && <AutoRefresh />}
    </main>
  )
}
