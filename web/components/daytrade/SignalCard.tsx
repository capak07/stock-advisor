import { Newspaper, Scale, TriangleAlert } from 'lucide-react'
import { LowRankChip } from '@/components/LowRankChip'
import { More } from '@/components/More'
import { LevelTiles } from '@/components/daytrade/LevelTiles'
import { StatusChip } from '@/components/daytrade/StatusChip'
import { shortDay } from '@/lib/dates'
import {
  LATE_LINE,
  LATE_SHARES,
  answerOf,
  costLine,
  etClock,
  fmtR,
  historyLine,
  nyTime,
  oddsLine,
  outcomeLine,
  priceOf,
  rTone,
  rangeLine,
  sharesLine,
  statusChip,
  strengthLine,
  type Signal,
} from '@/lib/daytrade'
import { safeLink } from '@/lib/ticker'

/** "11:10 AM" on the signal's day, "Nov 9, 4:05 PM" before it (New York time). */
const headlineTime = (iso: string, day: string) => {
  const d = nyTime(iso).day
  return d === day ? etClock(iso) : `${shortDay(d)}, ${etClock(iso)}`
}

const DASH = '—'
const rOf = (r: number | null) => (r === null ? DASH : fmtR(r))
const toneClass = (r: number | null) => rTone(r) ?? ''

/** Place, symbol, market, the low-rank flag, the name and the status chip. */
function Head({ s, place, chip, lowRank }: { s: Signal; place: number | null; chip: ReturnType<typeof statusChip>; lowRank: number | null }) {
  return (
    <div className="dt-head">
      <span className="dt-who">
        <span className="rank">{place}</span>
        <span className="dt-who-t">
          <span>
            <span className="sym">{s.symbol}</span>{' '}
            <span className="chip" data-market={s.market}>
              {s.market}
            </span>
            {lowRank !== null && (
              <>
                {' '}
                <LowRankChip scored={lowRank} />
              </>
            )}
          </span>
          {s.name && <span className="name">{s.name}</span>}
        </span>
      </span>
      <StatusChip label={chip.label} tone={chip.tone} />
    </div>
  )
}

/** The verdict line: the replays line (the app has no worded day-trade verdict). */
const Verdict = ({ s }: { s: Signal }) => (
  <div className="dt-verdict">
    <Scale aria-hidden />
    <span>{oddsLine(s.replay)}</span>
  </div>
)

/**
 * One of today's top 3 (the skill's, or the after-costs one). The full card leads with its answer (owner
 * request 2026-11-25): the result after costs and the exit, or the R so far and the last price; then the late
 * warning, entry / target / stop tiles and shares sized to the max loss. Under Details: the signal's volume, the
 * cost in R and the net history and replay R, the replays, the opening range and flat-by time, the breakout's
 * strength (a skill card), the rule's history, the cost, the full outcome line and the top headline. Both
 * lists use this one card (owner request 2026-11-25). Display only: nothing here places an order.
 */
export function SignalCard({
  signal: s,
  list = 'costs',
  fresh,
  maxLossCad,
  usdCad,
  lowRank = null,
}: {
  signal: Signal
  /** Which top 3 the card is in: its place and extra lines follow it. */
  list?: 'skill' | 'costs'
  fresh: boolean
  maxLossCad: number
  usdCad: number | null
  /** Low model rank in the latest run: how many US stocks it ranked; null when not flagged. */
  lowRank?: number | null
}) {
  const skill = list === 'skill'
  const place = skill ? s.skillRank : s.rank
  const chip = statusChip(s, fresh)
  const head = <Head s={s} place={place} chip={chip} lowRank={lowRank} />
  const late = s.status === 'open' && !fresh
  const risk = Number((s.entry - s.stop).toFixed(4))
  const top = s.headlines[0]
  const link = top ? safeLink(top.url) : null
  const answer = answerOf(s)
  return (
    <article className="card pick dt-card" data-testid="daytrade-card" aria-label={`${s.symbol} signal`}>
      {head}
      <div className="answer" data-testid="daytrade-answer">
        <b className={`answer-big num ${answer.tone ?? ''}`.trim()}>{answer.big}</b>
        {answer.note && <span className="answer-note">{answer.note}</span>}
      </div>
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
      <LevelTiles entry={s.entry} target={s.target} stop={s.stop} market={s.market} entryNote={etClock(s.triggerAt)} />
      <p className="dt-line sub">
        {sharesLine(maxLossCad, risk, s.market, usdCad)}
        {late && <> {LATE_SHARES}</>}
      </p>
      <More testId="daytrade-details">
        <p className="dt-line">
          Entry signal {etClock(s.triggerAt)} at <b className="num">{priceOf(s.entry, s.market)}</b>{' '}
          <span className="sub">· volume {s.volumeX.toFixed(1)}× the opening range</span>
        </p>
        <div className="dt-facts">
          <div>
            <span className="label">Cost</span>
            <b className="num">{s.costR.toFixed(2)}R</b>
          </div>
          <div>
            <span className="label">History, net</span>
            <b className={`num ${toneClass(s.netHistoryR)}`}>{rOf(s.netHistoryR)}</b>
          </div>
          <div>
            <span className="label">Replays, net</span>
            <b className={`num ${toneClass(s.netReplayR)}`}>{rOf(s.netReplayR)}</b>
          </div>
        </div>
        <Verdict s={s} />
        <div className="dt-fine num">{rangeLine(s)}</div>
        <ul className="dt-lines">
          {skill && <li>{strengthLine(s)}</li>}
          <li>{historyLine(s.symbol, s.history)}</li>
          <li>{costLine(s.costPct, s.costR)}</li>
          {!late && <li className="dt-outcome">{outcomeLine(s)}</li>}
        </ul>
        {top && (
          <div className="dt-news">
            <Newspaper aria-hidden />
            <span>
              {link ? (
                <a href={link} target="_blank" rel="noopener noreferrer">
                  {top.title}
                </a>
              ) : (
                top.title
              )}{' '}
              <span className="sub">
                · {top.outlet} {headlineTime(top.published_at, s.day)}
              </span>
            </span>
          </div>
        )}
      </More>
    </article>
  )
}
