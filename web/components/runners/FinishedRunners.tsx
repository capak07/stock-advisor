import Link from 'next/link'
import { shortDay } from '@/lib/dates'
import { priceOf, rTone } from '@/lib/daytrade'
import { fmtPct } from '@/lib/format'
import { PAPER_SHARES, isFinishedPaper, paperTotal, paperValue, usdMoney, usdSigned, type Runner } from '@/lib/runners'
import { tickerHref } from '@/lib/ticker'

/** How many finished trades the list shows; the total covers them all. */
const LISTED = 20

const HOW: Partial<Record<Runner['status'], string>> = { target: 'target', stop: 'stop', held: 'time up' }

const usd = (value: number) => priceOf(value, 'US')

/** One finished trade after its symbol: " · bought at US$2.00 = US$200.00 · sold at US$3.00 = US$300.00 (target, Nov 24) · "
 * and then its gain, "+US$100.00 (+50.0%)", in green or red. */
function TradeLine({ r }: { r: Runner }) {
  const paper = paperValue(r.entry, r.exitPrice)
  if (paper === null || r.entry === null || r.exitPrice === null) return null
  const when = r.exitDay === null ? '' : `, ${shortDay(r.exitDay)}`
  return (
    <>
      {` · bought at ${usd(r.entry)} = ${usdMoney(paper.cost)} · sold at ${usd(r.exitPrice)} = ${usdMoney(paper.value)}` +
        ` (${HOW[r.status] ?? r.status}${when}) · `}
      <span className={`num ${rTone(paper.gain) ?? ''}`}>{`${usdSigned(paper.gain)} (${fmtPct(paper.gainPct)})`}</span>
    </>
  )
}

/**
 * The live rule version's finished paper trades, 100 shares each, in plain US$: the total put in and got
 * back, before and after the estimated spread, and the latest 20 trades. Paper: nothing is ordered.
 */
export function FinishedRunners({ closed, version }: { closed: readonly Runner[]; version: number }) {
  const done = closed.filter((r) => r.ruleVersion === version && isFinishedPaper(r))
  const t = paperTotal(done)
  return (
    <section className="card card-pad enter" aria-labelledby="rn-finished-h">
      <div className="section-head" style={{ marginBottom: 4 }}>
        <h2 id="rn-finished-h">Finished paper trades</h2>
        <span className="label">{PAPER_SHARES} shares each</span>
      </div>
      {done.length === 0 ? (
        <p className="sub" style={{ margin: 0 }}>
          No finished paper trades yet.
        </p>
      ) : (
        <>
          <p className="dt-line" data-testid="runners-paper-total">
            {`${t.trades} finished ${t.trades === 1 ? 'trade' : 'trades'}: put in ${usdMoney(t.cost)}, got back ${usdMoney(t.value)}, ` +
              `${usdSigned(t.gain)} (${fmtPct(t.gainPct)}). After the estimated spread: ${usdSigned(t.gainAfterSpread)}.`}
          </p>
          <ul className="dt-lines">
            {done.slice(0, LISTED).map((r) => (
              <li key={r.id}>
                <Link className="sym" href={tickerHref(r.symbol, 'stock')}>
                  {r.symbol}
                </Link>
                <TradeLine r={r} />
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
