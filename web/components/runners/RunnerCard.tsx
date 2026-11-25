import Link from 'next/link'
import { More } from '@/components/More'
import { LevelTiles } from '@/components/daytrade/LevelTiles'
import { shortDay } from '@/lib/dates'
import { fmtR, priceOf, rTone, sharesLine } from '@/lib/daytrade'
import { fmtPct } from '@/lib/format'
import { PAPER, PAPER_SHARES, ignitionLine, usdMoney, usdSigned, type Runner, type RunnerWarning } from '@/lib/runners'
import { LIVE_NOTE, liveValue, type LivePlan, type LiveRunner } from '@/lib/runners-live'
import { tickerHref } from '@/lib/ticker'

const WARNING_LABEL: Record<RunnerWarning['kind'], string> = {
  share_sale: 'Share sale',
  reverse_split: 'Reverse split',
  deficiency: 'Exchange notice',
}

const usd = (value: number) => priceOf(value, 'US')

/**
 * One of today's signals, leading with its answer (owner request 2026-11-25). Before the open: buy at the open,
 * about what 100 shares cost, and the plan from the signal close. Once `live` has Yahoo's open: the paper trade's
 * gain, what the 100 shares cost and are worth, and the plan from that open; a skip at the open says so. Then the
 * entry / target / stop tiles and the hold-by day; the ignition, the filings' warnings, shares sized to the max
 * loss, the spread and the paper trade's lines go under Details. The warnings' chips stay on the card. `paper`
 * labels it while the gate has not passed. Display only: nothing here places an order.
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
  const bought = live !== null && live.kind !== 'skipped' ? live : null
  const plan: LivePlan = bought?.plan ?? { entry: r.signalClose, stop: r.stop, target: r.target }
  const risk = Number((plan.entry - plan.stop).toFixed(4))
  // the spread's cost in R from the real entry (cost.py cost_r), as the morning check will store it
  const costR = bought === null ? r.costR : (r.spreadPct * plan.entry) / (plan.entry - plan.stop) / 100
  const value = bought === null ? null : liveValue(bought)
  const atClose = usdMoney(r.signalClose * PAPER_SHARES)
  return (
    <article className="card pick dt-card" data-testid="runner-card" aria-label={`${r.symbol} signal`}>
      <div className="dt-who-t">
        <span className="rn-chips">
          <Link className="sym" href={tickerHref(r.symbol, 'stock')}>
            {r.symbol}
          </Link>
          {paper && <span className="chip neutral">{PAPER}</span>}
          {r.warnings.map((w) => (
            <span key={`${w.kind}-${w.filed}-${w.form}`} className="chip review">
              {WARNING_LABEL[w.kind]}
            </span>
          ))}
          {!r.warningsChecked && <span className="chip neutral">Filings not checked</span>}
        </span>
        {r.name && <span className="name">{r.name}</span>}
      </div>
      <div className="answer" data-testid="runner-answer">
        {live?.kind === 'skipped' ? (
          <>
            <b className="answer-big">Skipped</b>
            <span className="answer-note">{`Opened ${usd(live.entry)} on ${shortDay(live.entryDay)}: ${live.reason}`}</span>
          </>
        ) : value !== null ? (
          <>
            <span className="answer-row">
              <b className={`answer-big num ${rTone(value.paper.gain) ?? ''}`.trim()} data-testid="runner-gain">
                {`${usdSigned(value.paper.gain)} ${fmtPct(value.paper.gainPct)}`}
              </b>
              <b className={`answer-r num ${rTone(value.r) ?? ''}`.trim()}>{fmtR(value.r)}</b>
            </span>
            <span className="answer-note">
              {`${PAPER_SHARES} shares: paid ${usdMoney(value.paper.cost)} · ${bought?.kind === 'exited' ? 'got back' : 'worth'} ${usdMoney(value.paper.value)}`}
            </span>
          </>
        ) : (
          <>
            <b className="answer-big">Buy at the open</b>
            <span className="answer-note">{`About ${atClose} for ${PAPER_SHARES} shares at the signal close`}</span>
          </>
        )}
      </div>
      {live?.kind !== 'skipped' && (
        <LevelTiles
          entry={plan.entry}
          target={plan.target}
          stop={plan.stop}
          market="US"
          entryLabel={bought === null ? 'Entry ≈' : 'Bought'}
          entryNote={bought === null ? undefined : shortDay(bought.entryDay)}
        />
      )}
      {live?.kind !== 'skipped' && (
        <p className="dt-line sub">
          {value === null
            ? `Hold until ${shortDay(r.holdBy)}`
            : bought?.kind === 'exited'
              ? value.lead
              : `${value.lead} · hold until ${shortDay(r.holdBy)}`}
        </p>
      )}
      <More testId="runner-details">
        <p className="dt-line">{ignitionLine(r)}</p>
        {r.warnings.length > 0 && (
          <ul className="dt-lines">
            {r.warnings.map((w) => (
              <li key={`${w.kind}-${w.filed}-${w.form}`}>{w.text}</li>
            ))}
          </ul>
        )}
        <ul className="dt-lines">
          {live?.kind !== 'skipped' && <li>{sharesLine(maxLossCad, risk, 'US', usdCad)}</li>}
          {live?.kind !== 'skipped' && <li>{`Est. spread ${r.spreadPct.toFixed(1)}% = ${costR.toFixed(2)}R`}</li>}
          {live?.kind === 'skipped' ? (
            <li>Paper trade: none, skipped at the open.</li>
          ) : bought === null ? (
            <li>{`Paper trade: ${PAPER_SHARES} shares at the open (about ${atClose} at the signal close)`}</li>
          ) : (
            <>
              <li>{`Paper trade: ${PAPER_SHARES} shares, ${atClose} at the signal close, bought for ${usdMoney(plan.entry * PAPER_SHARES)} at the open`}</li>
              {value !== null && <li>{value.text}</li>}
            </>
          )}
        </ul>
        {live !== null && <p className="dt-live-note">{LIVE_NOTE}</p>}
      </More>
    </article>
  )
}
