import Link from 'next/link'
import { fmtMoney } from '@/lib/format'
import { resultDetail, resultParts, type Results } from '@/lib/portfolio/results'
import { tickerHref } from '@/lib/ticker'

const STATUS = { holding: 'Holding', part: 'Part sold', sold: 'Sold' } as const

const tone = (cad: number) => (cad < 0 ? 'loss' : 'gain')

/**
 * Results by stock: one line per holding, from its first buy until it was all sold. A stock sold in full shows what it
 * made; one still held shows what it is up or down right now, as the holdings table values it.
 */
export function ResultsCard({ results }: { results: Results }) {
  const { lines, realizedCad, openCad } = results
  if (lines.length === 0) return null
  return (
    <section className="card card-pad enter" aria-labelledby="results-h">
      <div className="section-head">
        <h2 id="results-h">
          Results by stock <span className="count">{lines.length}</span>
        </h2>
        <span className="sub">at average cost, in C$</span>
      </div>
      <div className="table-scroll">
        <table className="data-table" id="results">
          <thead>
            <tr>
              <th>Stock</th>
              <th className="r">Profit / loss</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => {
              const [what, when] = resultDetail(line)
              return (
                <tr key={line.key} data-status={line.status}>
                  <td className="rs-what">
                    <div className="rs-name">
                      <Link className="sym" href={tickerHref(line.symbol, line.assetType)}>
                        {line.symbol}
                      </Link>
                      <span className={line.status === 'sold' ? 'chip' : 'chip buy'}>{STATUS[line.status]}</span>
                    </div>
                    <span className="sub num rs-line">{what}</span>
                    <span className="sub rs-line">{when}</span>
                  </td>
                  <td className="r num rs-result">
                    {resultParts(line).map((p) => (
                      <span key={p.label} className="rs-part">
                        <span className={p.tone ?? undefined}>{p.amount}</span>
                        {p.pct !== null && <span className={`sub ${p.tone}`}> {p.pct}</span>}
                        <span className="sub"> {p.label}</span>
                      </span>
                    ))}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="sub rs-total">
        Made on sales: <span className={`num ${tone(realizedCad)}`}>{fmtMoney(realizedCad, { signed: true })}</span>
        {' · '}
        Open now: <span className={`num ${tone(openCad)}`}>{fmtMoney(openCad, { signed: true })}</span>
      </p>
    </section>
  )
}
