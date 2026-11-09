import { shortDay } from '@/lib/dates'
import { fmtMoney } from '@/lib/format'
import type { InsiderTrade } from '@/lib/data/monitor'

/** The last 90 days of insider open-market buys and sells (Form 4 codes P and S), US stocks only. */
export function InsidersCard({ trades }: { trades: InsiderTrade[] }) {
  return (
    <section className="card card-pad enter" aria-labelledby="insiders-h" id="insiders">
      <div className="section-head" style={{ marginBottom: 4 }}>
        <h2 id="insiders-h">Insider trades</h2>
        <span className="sub">90 days</span>
      </div>
      {trades.length === 0 ? (
        <p className="sub" style={{ margin: '6px 0 0' }}>
          No insider buys or sells in the last 90 days.
        </p>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <tbody>
              {trades.map((t, i) => (
                <tr key={`${t.filedAt}-${i}`} data-testid="insider-row">
                  <td className="num">{shortDay(t.tradeDate)}</td>
                  <td>
                    {t.owner}
                    {t.role && <span className="sub"> ({t.role})</span>} {t.code === 'P' ? 'bought' : 'sold'}
                    {t.planned && <span className="sub"> (10b5-1 plan)</span>}
                  </td>
                  <td className="r num">{t.shares.toLocaleString('en-CA', { maximumFractionDigits: 4 })} shares</td>
                  <td className="r num">{t.price === null ? '—' : fmtMoney(t.price, { prefix: '$', digits: 2 })}</td>
                  <td className="r num">{t.value === null ? '—' : fmtMoney(t.value, { prefix: '$' })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
