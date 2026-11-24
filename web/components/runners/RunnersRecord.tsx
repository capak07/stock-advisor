import { addDays } from '@/lib/dates'
import { fmtR } from '@/lib/daytrade'
import { recordOf, type RecordSummary, type Runner } from '@/lib/runners'

const DASH = '—'
const r = (value: number | null) => (value === null ? DASH : fmtR(value))

/** The last 20 and 60 sessions as calendar windows (the web has no trading calendar). */
const WINDOWS = [
  { sessions: 20, days: 28 },
  { sessions: 60, days: 84 },
] as const

function Row({ sessions, summary: t }: { sessions: number; summary: RecordSummary }) {
  const none = t.count === 0
  return (
    <tr data-testid={`runners-record-${sessions}`}>
      <td>Last {sessions} sessions</td>
      <td className="r num">{t.count}</td>
      <td className="num">{none ? DASH : `${t.target} / ${t.stop} / ${t.held}`}</td>
      <td className="r num">{t.skipped}</td>
      <td className="r num">{r(t.avgNetR)}</td>
      <td className="r num">{r(t.medianNetR)}</td>
      <td className="r num">{none ? DASH : fmtR(t.sumNetR)}</td>
    </tr>
  )
}

/**
 * The live record of the settled signals over the last 20 and 60 sessions, after costs: what the rule's
 * trades would have done (paper; nothing is ordered).
 */
export function RunnersRecord({ closed, version, today }: { closed: readonly Runner[]; version: number; today: string }) {
  const finished = recordOf(closed).count > 0
  return (
    <section className="card card-pad" aria-labelledby="rn-record-h">
      <div className="section-head" style={{ marginBottom: 4 }}>
        <h2 id="rn-record-h">Track record</h2>
      </div>
      <p className="sub" style={{ margin: '0 0 12px' }}>
        Paper: what the rule&apos;s trades would have done, after costs · rule version {version}
        {version === 0 && ' (the starting values)'}
      </p>
      {finished ? (
        <div className="dt-scroll dt-record">
          <table className="data-table dt-table" aria-labelledby="rn-record-h">
            <thead>
              <tr>
                <th>Signalled</th>
                <th className="r">Trades</th>
                <th>Target / stop / held</th>
                <th className="r">Skipped</th>
                <th className="r">Average R</th>
                <th className="r">Median R</th>
                <th className="r">Sum R</th>
              </tr>
            </thead>
            <tbody>
              {WINDOWS.map((w) => {
                const from = addDays(today, -w.days)
                return <Row key={w.sessions} sessions={w.sessions} summary={recordOf(closed.filter((c) => c.signalDay >= from))} />
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="sub" style={{ margin: 0 }}>
          No finished runners yet.
        </p>
      )}
    </section>
  )
}
