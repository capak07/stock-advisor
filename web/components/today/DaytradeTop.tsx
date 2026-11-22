import { ChevronRight, Scale } from 'lucide-react'
import Link from 'next/link'
import { etClock, fmtR, isFresh, noTradeLine, oddsLine, priceOf, statusLine, type DayRow, type Signal } from '@/lib/daytrade'

/** The status chip: the same words as the Day trade page's cards, open ones with their signal time. */
function chipOf(s: Signal, now: string): { label: string; tone: string } {
  switch (s.status) {
    case 'open':
      return isFresh(s.triggerAt, now)
        ? { label: `Fresh · ${etClock(s.triggerAt)}`, tone: 'triggered' }
        : { label: `Late · ${etClock(s.triggerAt)}`, tone: 'waiting' }
    case 'target':
      return { label: 'Target hit', tone: 'target' }
    case 'stop':
      return { label: 'Stopped out', tone: 'stopped' }
    case 'flat':
      return { label: 'Flat at close', tone: 'neutral' }
  }
}

/**
 * Day trade · top 3 after costs (spec §7.1): the Day trade page's day and its after-costs top 3, each
 * with its status chip, the replays line its card shows and its net history R; the first one also
 * shows entry, target and stop. "No session today" when that page has no session (no row, or closed).
 */
export function DaytradeTop({
  day,
  top,
  signals,
  now,
}: {
  /** The Day trade page's row for `nyTime(now).day`. */
  day: DayRow | null
  /** Its after-costs top 3, in rank order. */
  top: Signal[]
  /** How many signals the day has, for the empty line. */
  signals: number
  now: string
}) {
  const session = day !== null && day.status !== 'closed'
  const ran = day !== null && (day.status === 'scanning' || day.status === 'done' || (day.status === 'failed' && day.lastUpdate !== null))
  return (
    <section className="card card-pad dt-today enter" aria-labelledby="dt-today-h">
      <div className="section-head">
        <h2 id="dt-today-h">Day trade · top 3 after costs</h2>
        <Link className="link" href="/daytrade">
          Open <ChevronRight style={{ width: 14, height: 14 }} aria-hidden />
        </Link>
      </div>
      {!session ? (
        <p className="sub" style={{ margin: 0, fontSize: 13 }}>
          No session today.
        </p>
      ) : top.length === 0 ? (
        <p className="sub" style={{ margin: 0, fontSize: 13 }}>
          {ran ? noTradeLine(signals) : statusLine(day, now)}
        </p>
      ) : (
        top.map((s, i) => {
          const chip = chipOf(s, now)
          return (
            <div className="trade" key={s.id} data-testid="today-trade">
              <div className="trade-top">
                <span className="trade-name">
                  <span className="rank">{s.rank}</span>
                  <span className="sym">{s.symbol}</span>
                  {s.name && <span className="name">{s.name}</span>}
                </span>
                <span className={`chip ${chip.tone}`}>{chip.label}</span>
              </div>
              {i === 0 && (
                <div className="levels">
                  <div className="stat">
                    <span className="label">Entry</span>
                    <b>{priceOf(s.entry, s.market)}</b>
                  </div>
                  <div className="stat">
                    <span className="label">Target</span>
                    <b className="gain">{priceOf(s.target, s.market)}</b>
                  </div>
                  <div className="stat">
                    <span className="label">Stop</span>
                    <b className="loss">{priceOf(s.stop, s.market)}</b>
                  </div>
                </div>
              )}
              <div className="trade-verdict">
                <Scale aria-hidden />
                <span>
                  {oddsLine(s.replay)}
                  {s.netHistoryR !== null && <> · history {fmtR(s.netHistoryR)} after costs</>}
                </span>
              </div>
            </div>
          )
        })
      )}
    </section>
  )
}
