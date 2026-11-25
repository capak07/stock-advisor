import Link from 'next/link'
import { shortDay } from '@/lib/dates'
import { fmtR, priceOf, rTone } from '@/lib/daytrade'
import { fmtMove } from '@/lib/format'
import { PAPER_SHARES, paperValue, rSoFar, usdMoney, type Runner } from '@/lib/runners'
import { LIVE_NOTE, gainText, liveValue, type LiveRunner } from '@/lib/runners-live'
import { tickerHref } from '@/lib/ticker'

const DASH = '—'
const usd = (value: number) => priceOf(value, 'US')

/**
 * An open runner as a paper position: 100 shares bought at the entry, what they are worth at the last close,
 * the plan, and its R so far. With `live` (Yahoo's bars past the stored close) it shows the latest price or
 * close instead, or the stop or target hit since. Display only: nothing here places an order.
 */
export function OpenRunnerCard({ runner: r, live = null }: { runner: Runner; live?: LiveRunner | null }) {
  const now = r.lastClose !== null && r.lastDay !== null ? paperValue(r.entry, r.lastClose) : null
  const bought = paperValue(r.entry, r.entry)
  const latest = live === null ? null : liveValue(live)
  const rNow = latest === null ? rSoFar(r) : latest.r
  return (
    <article className="card pick dt-card" data-testid="open-runner-card" aria-label={`${r.symbol} open runner`}>
      <div className="dt-who-t">
        <span>
          <Link className="sym" href={tickerHref(r.symbol, 'stock')}>
            {r.symbol}
          </Link>
        </span>
        {r.name && <span className="name">{r.name}</span>}
      </div>
      {r.entry !== null && bought !== null && (
        <p className="dt-line">
          {`Bought ${PAPER_SHARES} shares at ${usd(r.entry)}${r.entryDay === null ? '' : ` on ${shortDay(r.entryDay)}`} = ${usdMoney(bought.cost)}`}
        </p>
      )}
      {latest !== null ? (
        <p className="dt-line">
          {`${latest.text} · `}
          <span className={`num ${rTone(latest.paper.gain) ?? ''}`} data-testid="open-runner-gain">
            {gainText(latest.paper)}
          </span>
        </p>
      ) : now === null || r.lastClose === null || r.lastDay === null ? (
        <p className="dt-line">No close yet.</p>
      ) : (
        <p className="dt-line">
          {`Now ${usd(r.lastClose)} (${shortDay(r.lastDay)} close) · worth ${usdMoney(now.value)} · `}
          <span className={`num ${rTone(now.gain) ?? ''}`} data-testid="open-runner-gain">
            {gainText(now)}
          </span>
        </p>
      )}
      <ul className="dt-lines">
        <li>
          {r.entry === null
            ? `Stop ${usd(r.stop)} · target ${usd(r.target)} · hold by ${shortDay(r.holdBy)}`
            : `Stop ${usd(r.stop)} (${fmtMove(r.entry, r.stop)}) · target ${usd(r.target)} (${fmtMove(r.entry, r.target)}) · ` +
              `hold by ${shortDay(r.holdBy)}`}
        </li>
        <li>
          {live?.kind === 'exited' ? 'R at the exit ' : 'R so far '}
          <span className={`num ${rTone(rNow) ?? ''}`} data-testid="open-runner-r">
            {rNow === null ? DASH : fmtR(rNow)}
          </span>
        </li>
      </ul>
      {latest !== null && <p className="dt-live-note">{LIVE_NOTE}</p>}
    </article>
  )
}
