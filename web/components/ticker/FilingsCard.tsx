import { shortDay, todayInToronto } from '@/lib/dates'
import { isImportant, itemLabels } from '@/lib/filings'
import { safeLink } from '@/lib/ticker'
import type { FilingRow } from '@/lib/data/monitor'

/** The last 90 days of 8-Ks, each item in words, linked to the document on sec.gov (US stocks). */
export function FilingsCard({ filings }: { filings: FilingRow[] }) {
  return (
    <section className="card card-pad enter" aria-labelledby="filings-h" id="filings">
      <div className="section-head" style={{ marginBottom: 4 }}>
        <h2 id="filings-h">Filings (8-K)</h2>
        <span className="sub">90 days</span>
      </div>
      {filings.length === 0 ? (
        <p className="sub" style={{ margin: '6px 0 0' }}>
          No 8-K in the last 90 days.
        </p>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <tbody>
              {filings.map((f) => {
                const labels = itemLabels(f.items)
                const label = labels.length ? `${f.form}: ${labels.join(', ')}` : f.form
                const link = safeLink(f.url)
                return (
                  <tr key={f.accession} data-testid="filing-row">
                    <td className="num">{shortDay(todayInToronto(new Date(f.filedAt)))}</td>
                    <td>
                      {link ? (
                        <a href={link} target="_blank" rel="noopener noreferrer">
                          {label}
                        </a>
                      ) : (
                        label
                      )}
                      {isImportant(f.items) && <span className="chip review" style={{ marginLeft: 6 }}>Important</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
