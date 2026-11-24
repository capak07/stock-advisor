import { TriangleAlert } from 'lucide-react'
import { longDay } from '@/lib/dates'
import { fmtR, fmtShare } from '@/lib/daytrade'
import { BIAS_NOTE, type Backtest, type BacktestReport } from '@/lib/runners'

const DASH = '—'
const r = (value: number | null) => (value === null ? DASH : fmtR(value))

const ROWS: { label: string; value: (t: BacktestReport) => string }[] = [
  { label: 'Signals', value: (t) => String(t.signals) },
  { label: 'Target / stop / held', value: (t) => `${t.target} / ${t.stop} / ${t.held}` },
  { label: 'Average R after costs', value: (t) => r(t.avg_net_r) },
  { label: 'Median R after costs', value: (t) => r(t.median_net_r) },
  { label: 'Lost more than 1R', value: (t) => (t.lost_over_1r === null ? DASH : fmtShare(t.lost_over_1r)) },
  { label: 'Skipped for gaps', value: (t) => String(t.skipped_gap) },
]

/** The same trades: the search's pick is the frozen rule (or acts exactly like it). */
const sameTrades = (a: { older: BacktestReport; newer: BacktestReport }, b: { older: BacktestReport; newer: BacktestReport }) =>
  JSON.stringify([a.older, a.newer]) === JSON.stringify([b.older, b.newer])

/**
 * The newest weekly backtest: the frozen rule's older two thirds (which chose it) beside the newest
 * third (unseen when it was chosen), what the search would pick now when that differs, and why the
 * figures are optimistic.
 */
export function BacktestCard({ backtest: b }: { backtest: Backtest | null }) {
  const shown = b === null ? null : (b.frozen ?? b.pick)
  return (
    <section className="card card-pad" aria-labelledby="rn-backtest-h">
      <div className="section-head" style={{ marginBottom: 4 }}>
        <h2 id="rn-backtest-h">Backtest</h2>
        {b !== null && b.ruleVersion !== null && <span className="label">rule version {b.ruleVersion}</span>}
      </div>
      {b === null || shown === null ? (
        <p className="sub" style={{ margin: 0 }}>
          It has not run yet: the weekly training job runs it and freezes the first rule.
        </p>
      ) : (
        <>
          <div className="dt-scroll dt-record rn-backtest">
            <table className="data-table dt-table" aria-labelledby="rn-backtest-h">
              <thead>
                <tr>
                  <th>{b.frozen === null ? "The search's pick" : 'Frozen rule'}</th>
                  <th className="r">Older 2/3</th>
                  <th className="r">Newest 1/3, unseen</th>
                </tr>
              </thead>
              <tbody>
                {ROWS.map((row) => (
                  <tr key={row.label}>
                    <td>{row.label}</td>
                    <td className="r num">{row.value(shown.older)}</td>
                    <td className="r num">{row.value(shown.newer)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="sub" style={{ margin: '12px 0 0' }}>
            {`Chosen on data before ${longDay(b.cutoff)}; the newest third was unseen. ${b.variantsTried} variations tried.`}
          </p>
          {b.frozen !== null && !sameTrades(b.frozen, b.pick) && (
            <p className="sub" style={{ margin: '6px 0 0' }}>
              {`The search would pick "${b.pick.name}" now: ${r(b.pick.newer.avg_net_r)} on the newest third over ` +
                `${b.pick.newer.signals} signals${b.pick.note ? ` (${b.pick.note})` : ''}.`}
            </p>
          )}
          <div className="banner warn" style={{ marginTop: 12 }}>
            <TriangleAlert />
            <div>{BIAS_NOTE}</div>
          </div>
        </>
      )}
    </section>
  )
}
