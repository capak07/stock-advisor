import Link from 'next/link'
import { shortDay } from '@/lib/dates'
import { fmtR, priceOf, rTone, sharesLine } from '@/lib/daytrade'
import { fmtMove } from '@/lib/format'
import { PAPER, PAPER_SHARES, ignitionLine, usdMoney, type Runner, type RunnerWarning } from '@/lib/runners'
import { LIVE_NOTE, gainText, liveValue, type LivePlan, type LiveRunner } from '@/lib/runners-live'
import { tickerHref } from '@/lib/ticker'

const WARNING_LABEL: Record<RunnerWarning['kind'], string> = {
  share_sale: 'Share sale',
  reverse_split: 'Reverse split',
  deficiency: 'Deficiency notice',
}

/** Target over risk: "2", "1.5". */
const multiple = (p: LivePlan) => Number(((p.target - p.entry) / (p.entry - p.stop)).toFixed(1))

/**
 * One of today's signals: the stock, its filing warnings, the ignition, the plan, shares sized to the max loss and
 * the spread's cost. Before the open the plan is a preview from the signal close (the entry is the next open); once
 * `live` has Yahoo's open, the plan is from that open and the paper trade shows what it cost, what it is worth and
 * the gain. `paper` labels it while the gate has not passed. Display only: nothing here places an order.
 */
export function RunnerCard({
  runner: r,
  maxLossCad,
  usdCad,
  paper,
  live = null,
}: {
  runner: Runner
  maxLossCad: number
  usdCad: number | null
  paper: boolean
  live?: LiveRunner | null
}) {
  const usd = (value: number) => priceOf(value, 'US')
  const bought = live !== null && live.kind !== 'skipped' ? live : null
  const plan: LivePlan = bought?.plan ?? { entry: r.signalClose, stop: r.stop, target: r.target }
  const risk = Number((plan.entry - plan.stop).toFixed(4))
  // the spread's cost in R from the real entry (cost.py cost_r), as the morning check will store it
  const costR = bought === null ? r.costR : (r.spreadPct * plan.entry) / (plan.entry - plan.stop) / 100
  const value = bought === null ? null : liveValue(bought)
  return (
    <article className="card pick dt-card" data-testid="runner-card" aria-label={`${r.symbol} signal`}>
      <div className="dt-who-t">
        <span>
          <Link className="sym" href={tickerHref(r.symbol, 'stock')}>
            {r.symbol}
          </Link>
          {paper && (
            <>
              {' '}
              <span className="chip neutral">{PAPER}</span>
            </>
          )}
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
        {live?.kind === 'skipped'
          ? `Opened ${usd(live.entry)} on ${shortDay(live.entryDay)}: skipped, ${live.reason}.`
          : `${bought === null ? `Enter at the open · if it opens near ${usd(r.signalClose)}` : `Bought at the open, ${usd(plan.entry)} on ${shortDay(bought.entryDay)}`}: ` +
            `stop ${usd(plan.stop)} (${fmtMove(plan.entry, plan.stop)}), target ${usd(plan.target)} (${fmtMove(plan.entry, plan.target)}, ${multiple(plan)}R) · ` +
            `hold by ${shortDay(r.holdBy)}`}
      </p>
      <ul className="dt-lines">
        {live?.kind !== 'skipped' && <li>{sharesLine(maxLossCad, risk, 'US', usdCad)}</li>}
        {live?.kind !== 'skipped' && <li>{`Est. spread ${r.spreadPct.toFixed(1)}% = ${costR.toFixed(2)}R`}</li>}
        {bought === null ? (
          <li>
            {live?.kind === 'skipped'
              ? 'Paper trade: none, skipped at the open.'
              : `Paper trade: ${PAPER_SHARES} shares at the open (about ${usdMoney(r.signalClose * PAPER_SHARES)} at the signal close)`}
          </li>
        ) : (
          <>
            <li>
              {`Paper trade: ${PAPER_SHARES} shares, ${usdMoney(r.signalClose * PAPER_SHARES)} at the signal close, ` +
                `bought for ${usdMoney(plan.entry * PAPER_SHARES)} at the open`}
            </li>
            {value !== null && (
              <li className="dt-outcome">
                {`${value.text} · `}
                <span className={`num ${rTone(value.paper.gain) ?? ''}`.trim()} data-testid="runner-gain">
                  {`${gainText(value.paper)} · ${fmtR(value.r)}`}
                </span>
              </li>
            )}
          </>
        )}
      </ul>
      {live !== null && <p className="dt-live-note">{LIVE_NOTE}</p>}
    </article>
  )
}
