import { changes, margins, ttm, yearAgo, type Quarter } from '@/lib/earnings'
import type { EarningsReport } from '@/lib/data/monitor'
import { longDay, shortDay, todayInToronto } from '@/lib/dates'
import { fmtPct } from '@/lib/format'

const SHOWN = 6

const compact = (value: number | null): string => {
  if (value === null) return '—'
  const abs = Math.abs(value)
  const [div, unit] = abs >= 1e9 ? [1e9, 'B'] : abs >= 1e6 ? [1e6, 'M'] : [1, '']
  return `${value < 0 ? '−' : ''}$${(abs / div).toFixed(div === 1 ? 0 : 2)}${unit}`
}
const eps = (value: number | null): string => (value === null ? '—' : `${value < 0 ? '−' : ''}$${Math.abs(value).toFixed(2)}`)
const pct = (value: number | null): string => (value === null ? '—' : `${(value * 100).toFixed(1)}%`)
const share = (part: number | null, whole: number | null): number | null =>
  part === null || whole === null || whole === 0 ? null : part / whole
const dayOf = (iso: string): string => todayInToronto(new Date(iso))

type Column = { label: string; of: (q: Quarter) => string }
const COLUMNS: Column[] = [
  { label: 'Revenue', of: (q) => compact(q.revenue) },
  { label: 'Gross margin', of: (q) => pct(margins(q).gross) },
  { label: 'Operating margin', of: (q) => pct(margins(q).operating) },
  { label: 'Net margin', of: (q) => pct(margins(q).net) },
  { label: 'Net income', of: (q) => compact(q.netIncome) },
  { label: 'Diluted EPS', of: (q) => eps(q.epsDiluted) },
]

/** The last six quarters beside the same quarter a year earlier, the trailing twelve months, what
 * changed, and the earnings dates (the quarters table is US only: `quarters` is empty for a TSX stock). */
export function EarningsCard({
  quarters,
  derived,
  latestFiling,
  earnings,
  now,
}: {
  quarters: Quarter[]
  derived: string[]
  latestFiling: { form: string; filed: string } | null
  earnings: EarningsReport[]
  now: string
}) {
  const shown = quarters.slice(0, SHOWN)
  const trailing = ttm(quarters)
  const sentences = changes(quarters)
  const next = earnings.find((e) => e.reportAt >= now)
  const past = earnings.filter((e) => e.reportAt < now).slice(0, 4)
  return (
    <section className="card card-pad enter" aria-labelledby="earnings-h" id="earnings">
      <div className="section-head" style={{ marginBottom: 4 }}>
        <h2 id="earnings-h">Earnings</h2>
        {shown.length > 0 && <span className="sub">each beside the same quarter a year earlier</span>}
      </div>

      {next ? (
        <p style={{ margin: '4px 0 8px' }} data-testid="next-earnings">
          Next report <b>{longDay(next.reportDate)}</b>
          {next.epsEstimate !== null && <> · EPS estimate {eps(next.epsEstimate)}</>}
        </p>
      ) : (
        <p className="sub" style={{ margin: '4px 0 8px' }}>
          No upcoming earnings date yet.
        </p>
      )}

      {shown.length > 0 && (
        <div className="table-scroll">
          <table className="data-table" id="quarters">
            <thead>
              <tr>
                <th>Quarter ended</th>
                {COLUMNS.map((c) => (
                  <th key={c.label} className="r">
                    {c.label}
                    <span className="sub"> · year ago</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((q) => {
                const before = yearAgo(q, quarters)
                return (
                  <tr key={q.periodEnd} data-testid="quarter-row">
                    <td className="num">
                      {q.fiscalPeriod ? `${q.fiscalPeriod} · ` : ''}
                      {shortDay(q.periodEnd)}
                      {derived.includes(q.periodEnd) && <span className="sub"> derived</span>}
                    </td>
                    {COLUMNS.map((c) => (
                      <td key={c.label} className="r num">
                        {c.of(q)}
                        <span className="sub" data-testid="year-ago">
                          {' · '}
                          {before ? c.of(before) : '—'}
                        </span>
                      </td>
                    ))}
                  </tr>
                )
              })}
              {trailing && (
                <tr data-testid="ttm-row">
                  <td className="num">
                    <b>Trailing 12 months</b>
                  </td>
                  <td className="r num">{compact(trailing.revenue)}</td>
                  <td className="r num">{pct(share(trailing.grossProfit, trailing.revenue))}</td>
                  <td className="r num">{pct(share(trailing.operatingIncome, trailing.revenue))}</td>
                  <td className="r num">{pct(share(trailing.netIncome, trailing.revenue))}</td>
                  <td className="r num">{compact(trailing.netIncome)}</td>
                  <td className="r num">{eps(trailing.epsDiluted)}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {sentences.length > 0 && (
        <ul style={{ margin: '10px 0 0', paddingLeft: 18 }} data-testid="changes">
          {sentences.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      )}
      {latestFiling && (
        <p className="sub" style={{ margin: '8px 0 0' }}>
          Latest filing: {latestFiling.form} filed {shortDay(latestFiling.filed)}
        </p>
      )}

      {past.length > 0 && (
        <div className="table-scroll" style={{ marginTop: 10 }}>
          <table className="data-table" id="past-earnings">
            <thead>
              <tr>
                <th>Reported</th>
                <th className="r">EPS actual</th>
                <th className="r">EPS estimate</th>
                <th className="r">Surprise</th>
              </tr>
            </thead>
            <tbody>
              {past.map((e) => (
                <tr key={e.reportDate} data-testid="past-earnings-row">
                  <td className="num">{shortDay(dayOf(e.reportAt))}</td>
                  <td className="r num">{eps(e.epsActual)}</td>
                  <td className="r num">{eps(e.epsEstimate)}</td>
                  <td className={`r num ${e.surprisePct === null ? '' : e.surprisePct < 0 ? 'loss' : 'gain'}`}>
                    {e.surprisePct === null ? '—' : fmtPct(e.surprisePct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {shown.some((q) => derived.includes(q.periodEnd)) && (
        <p className="sub" style={{ margin: '8px 0 0' }}>
          Derived: a fourth quarter worked out as the full year minus the first nine months.
        </p>
      )}
    </section>
  )
}
