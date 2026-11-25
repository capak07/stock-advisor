import Link from 'next/link'
import { shortDay } from '@/lib/dates'
import { fmtR, priceOf, rTone } from '@/lib/daytrade'
import { fmtMove, fmtPct } from '@/lib/format'
import { PAPER_SHARES, paperValue, rSoFar, usdMoney, usdSigned, type Runner } from '@/lib/runners'
import { tickerHref } from '@/lib/ticker'

const DASH = '—'
const usd = (value: number) => priceOf(value, 'US')

/**
 * An open runner as a paper position: 100 shares bought at the entry, what they are worth at the last close,
 * the plan, and its R so far. Display only: nothing here places an order.
 */
export function OpenRunnerCard({ runner: r }: { runner: Runner }) {
  const now = r.lastClose !== null && r.lastDay !== null ? paperValue(r.entry, r.lastClose) : null
  const bought = paperValue(r.entry, r.entry)
  const rNow = rSoFar(r)
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
      {now === null || r.lastClose === null || r.lastDay === null ? (
        <p className="dt-line">No close yet.</p>
      ) : (
        <p className="dt-line">
          {`Now ${usd(r.lastClose)} (${shortDay(r.lastDay)} close) · worth ${usdMoney(now.value)} · `}
          <span className={`num ${rTone(now.gain) ?? ''}`} data-testid="open-runner-gain">
            {`${usdSigned(now.gain)} (${fmtPct(now.gainPct)})`}
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
          {'R so far '}
          <span className={`num ${rTone(rNow) ?? ''}`} data-testid="open-runner-r">
            {rNow === null ? DASH : fmtR(rNow)}
          </span>
        </li>
      </ul>
    </article>
  )
}
