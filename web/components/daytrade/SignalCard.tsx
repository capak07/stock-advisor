import { TriangleAlert } from 'lucide-react'
import { shortDay } from '@/lib/dates'
import {
  LATE_LINE,
  costLine,
  etClock,
  flatBy,
  historyLine,
  nyTime,
  oddsLine,
  outcomeLine,
  priceOf,
  sharesLine,
  type Signal,
} from '@/lib/daytrade'
import { safeLink } from '@/lib/ticker'

/** "11:10 AM" on the signal's day, "Nov 9, 4:05 PM" before it (New York time). */
const headlineTime = (iso: string, day: string) => {
  const d = nyTime(iso).day
  return d === day ? etClock(iso) : `${shortDay(d)}, ${etClock(iso)}`
}

const OUTCOME_CHIP: Record<Exclude<Signal['status'], 'open'>, { label: string; tone: string }> = {
  target: { label: 'Target hit', tone: 'buy' },
  stop: { label: 'Stopped out', tone: 'avoid' },
  flat: { label: 'Flat at close', tone: 'hold' },
}

/**
 * One of today's top 3: the signal, the plan (stop, target, flat by), the replays, the rule's
 * history, the cost in R, shares sized to the max loss, headlines and where it stands now.
 * Display only: nothing here places an order.
 */
export function SignalCard({
  signal: s,
  fresh,
  maxLossCad,
  usdCad,
}: {
  signal: Signal
  fresh: boolean
  maxLossCad: number
  usdCad: number | null
}) {
  const open = s.status === 'open'
  const late = open && !fresh
  const risk = Number((s.entry - s.stop).toFixed(4))
  const chip = s.status === 'open' ? (fresh ? { label: 'Fresh', tone: 'buy' } : { label: 'Late', tone: 'review' }) : OUTCOME_CHIP[s.status]
  return (
    <article className="card pick dt-card" data-testid="daytrade-card" aria-label={`${s.symbol} signal`}>
      <div className="pick-head">
        <div style={{ minWidth: 0 }}>
          <span className="pick-rank">#{s.rank}</span> <span className="sym" style={{ fontSize: 15 }}>{s.symbol}</span>{' '}
          <span className="chip" data-market={s.market}>
            {s.market}
          </span>
          {s.name && <div className="sub dt-name">{s.name}</div>}
        </div>
        <span className={`chip ${chip.tone}`}>{chip.label}</span>
      </div>
      <p className="dt-line">
        Entry signal {etClock(s.triggerAt)} at <b className="num">{priceOf(s.entry, s.market)}</b>{' '}
        <span className="sub">· volume {s.volumeX.toFixed(1)}× the opening range</span>
      </p>
      {late && (
        <div className="banner warn">
          <TriangleAlert />
          <div>
            <div>{LATE_LINE}</div>
            <div className="sub">
              {s.lastPrice !== null && s.lastAt !== null
                ? `Last price ${priceOf(s.lastPrice, s.market)} at ${etClock(s.lastAt)}`
                : 'No price since the signal yet.'}
            </div>
          </div>
        </div>
      )}
      <dl className="pick-facts">
        <div>
          <dt>Stop</dt>
          <dd className="num">{priceOf(s.stop, s.market)}</dd>
        </div>
        <div>
          <dt>Target</dt>
          <dd className="num">{priceOf(s.target, s.market)}</dd>
        </div>
        <div>
          <dt>Flat by</dt>
          <dd className="num">{flatBy(s.day, s.market)}</dd>
        </div>
        <div>
          <dt>Shares</dt>
          <dd>{sharesLine(maxLossCad, risk, s.market, usdCad)}</dd>
        </div>
      </dl>
      <ul className="dt-lines">
        <li>{oddsLine(s.replay)}</li>
        <li>{historyLine(s.symbol, s.history)}</li>
        <li>{costLine(s.costPct, s.costR)}</li>
        {!late && <li className="dt-outcome">{outcomeLine(s)}</li>}
      </ul>
      {s.headlines.length > 0 && (
        <ul className="dt-news">
          {s.headlines.slice(0, 3).map((h) => {
            const link = safeLink(h.url)
            return (
              <li key={`${h.url}-${h.title}`}>
                {link ? (
                  <a href={link} target="_blank" rel="noopener noreferrer">
                    {h.title}
                  </a>
                ) : (
                  h.title
                )}{' '}
                <span className="sub">
                  {h.outlet} · {headlineTime(h.published_at, s.day)}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </article>
  )
}
