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
      <td className="r num">{r(t.avgNetR)}</td>
      <td className="r num">{t.count}</td>
      <td className="num">{none ? DASH : `${t.target} / ${t.stop} / ${t.held}`}</td>
      <td className="r num">{t.skipped}</td>
      <td className="r num">{r(t.medianNetR)}</td>
      <td className="r num">{none ? DASH : fmtR(t.sumNetR)}</td>
    </tr>
  )
}

/**
 * The live record of the live rule version's settled signals over the last 20 and 60 sessions, after costs:
 * what its trades would have done (paper; nothing is ordered). Earlier versions' runners are left out and
 * counted in one line. Average R comes second so a phone shows it without scrolling.
 */
export function RunnersRecord({ closed, version, today }: { closed: readonly Runner[]; version: number; today: string }) {
  const mine = closed.filter((c) => c.ruleVersion === version)
  const finished = recordOf(mine).count > 0
  const earlier = recordOf(closed.filter((c) => c.ruleVersion !== version)).count
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
                <th className="r">Average R</th>
                <th className="r">Trades</th>
                <th>Target / stop / held</th>
                <th className="r">Skipped</th>
                <th className="r">Median R</th>
                <th className="r">Sum R</th>
              </tr>
            </thead>
            <tbody>
              {WINDOWS.map((w) => {
                const from = addDays(today, -w.days)
                return <Row key={w.sessions} sessions={w.sessions} summary={recordOf(mine.filter((c) => c.signalDay >= from))} />
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="sub" style={{ margin: 0 }}>
          No finished runners yet.
        </p>
      )}
      {earlier > 0 && (
        <p className="sub" style={{ margin: '12px 0 0' }}>
          {earlier === 1
            ? '1 finished runner under earlier rule versions is not counted.'
            : `${earlier} finished runners under earlier rule versions are not counted.`}
        </p>
      )}
    </section>
  )
}
