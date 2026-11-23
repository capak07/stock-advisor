import Link from 'next/link'
import { fmtMoney } from '@/lib/format'
import { resultDetail, resultParts, resultTotals, type Results } from '@/lib/portfolio/results'
import { TAXABLE } from '@/lib/portfolio/types'
import { tickerHref } from '@/lib/ticker'

const STATUS = { holding: 'Holding', part: 'Part sold', sold: 'Sold' } as const

const tone = (cad: number) => (cad < 0 ? 'loss' : 'gain')

/** A total, or a dash after tax until the rate is set. */
function Money({ cad }: { cad: number | null }) {
  return cad === null ? <span className="num">—</span> : <span className={`num ${tone(cad)}`}>{fmtMoney(cad, { signed: true })}</span>
}

/**
 * Results by stock, on History: one line per holding, from its first buy until it was all sold, each with two
 * figures: what it made (sold in full), is up now (held) or has made so far (part sold), then the same after tax at
 * the owner's marginal rate from Settings (`taxPct`, null until set). A holding is valued as the holdings table values it.
 */
export function ResultsCard({ results, taxPct }: { results: Results; taxPct: number | null }) {
  const { lines } = results
  if (lines.length === 0) return null
  const totals = resultTotals(results, taxPct)
  const taxable = lines.some((l) => TAXABLE.has(l.account))
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
                    {resultParts(line, taxPct).map((p) => (
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
        <span>
          Made on sales: <Money cad={totals.realizedCad} /> · after tax <Money cad={totals.realizedAfterTax} />
        </span>
        <span>
          Open now: <Money cad={totals.openCad} /> · after tax <Money cad={totals.openAfterTax} />
        </span>
      </p>
      <p className="sub rs-note">
        {!taxable ? (
          "A TFSA, RRSP or FHSA isn't taxed."
        ) : taxPct === null ? (
          <>
            <Link href="/settings">Set your marginal tax rate in Settings</Link> to see results after tax.
          </>
        ) : (
          `After tax: half of a gain in a non-registered or crypto account is taxed at your ${taxPct}% rate, and a loss offsets gains the same way. A TFSA, RRSP or FHSA isn't taxed. An estimate, not tax advice.`
        )}
      </p>
    </section>
  )
}
