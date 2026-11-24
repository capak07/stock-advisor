import Link from 'next/link'
import { shortDay } from '@/lib/dates'
import { priceOf, sharesLine } from '@/lib/daytrade'
import { ignitionLine, type Runner, type RunnerWarning } from '@/lib/runners'
import { tickerHref } from '@/lib/ticker'

const WARNING_LABEL: Record<RunnerWarning['kind'], string> = {
  share_sale: 'Share sale',
  reverse_split: 'Reverse split',
  deficiency: 'Deficiency notice',
}

/** Target over risk from the signal close: "2", "1.5". */
const multiple = (r: Runner) => Number(((r.target - r.signalClose) / (r.signalClose - r.stop)).toFixed(1))

/**
 * One of today's signals: the stock, its filing warnings, the ignition, the plan from the signal close
 * (the entry is the next open), shares sized to the max loss and the spread's cost. Display only:
 * nothing here places an order.
 */
export function RunnerCard({ runner: r, maxLossCad, usdCad }: { runner: Runner; maxLossCad: number; usdCad: number | null }) {
  const usd = (value: number) => priceOf(value, 'US')
  const risk = Number((r.signalClose - r.stop).toFixed(4))
  return (
    <article className="card pick dt-card" data-testid="runner-card" aria-label={`${r.symbol} signal`}>
      <div className="dt-who-t">
        <span>
          <Link className="sym" href={tickerHref(r.symbol, 'stock')}>
            {r.symbol}
          </Link>
        </span>
        {r.name && <span className="name">{r.name}</span>}
      </div>
      {(r.warnings.length > 0 || !r.warningsChecked) && (
        <ul className="dt-lines">
          {r.warnings.map((w) => (
            <li key={`${w.kind}-${w.filed}-${w.form}`}>
              <span className="chip review">{WARNING_LABEL[w.kind]}</span> {w.text}
            </li>
          ))}
          {!r.warningsChecked && (
            <li>
              <span className="chip neutral">Filings not checked</span>
            </li>
          )}
        </ul>
      )}
      <p className="dt-line">{ignitionLine(r)}</p>
      <p className="dt-line">
        {`Enter at the open · if it opens near ${usd(r.signalClose)}: stop ${usd(r.stop)}, target ${usd(r.target)} ` +
          `(${multiple(r)}R) · hold by ${shortDay(r.holdBy)}`}
      </p>
      <ul className="dt-lines">
        <li>{sharesLine(maxLossCad, risk, 'US', usdCad)}</li>
        <li>{`Est. spread ${r.spreadPct.toFixed(1)}% = ${r.costR.toFixed(2)}R`}</li>
      </ul>
    </article>
  )
}
