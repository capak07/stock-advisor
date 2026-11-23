import Link from 'next/link'
import { fmtPct } from '@/lib/format'
import { P_MIN } from '@/lib/invest/allocate'
import type { WatchGroup } from '@/lib/invest/watch'
import { tickerHref } from '@/lib/ticker'

const pct = (fraction: number) => fmtPct(fraction * 100)

/**
 * The model's best-ranked stocks grouped by how long to hold, for research only: no amounts and no orders. A stock
 * that meets the picks' rule says so; the rest are labelled as not picks.
 */
export function WatchList({ groups, runDay }: { groups: WatchGroup[]; runDay: string }) {
  if (groups.length === 0) return null
  const anyPasses = groups.some((g) => g.lines.some((l) => l.passes))
  return (
    <section className="card card-pad enter watch-list" aria-labelledby="watch-h">
      <div className="section-head">
        <h2 id="watch-h">Watch list, not picks</h2>
        <span className="sub">run of {runDay}</span>
      </div>
      <p className="sub wl-note">
        {anyPasses
          ? `The model's best-ranked stocks by how long to hold. Only those marked "passes the bar" meet the picks' rule (a ${Math.round(P_MIN * 100)}% chance of beating the benchmark, after costs); the rest are for research only.`
          : `None passes the ${Math.round(P_MIN * 100)}% bar. The model's best-ranked stocks by how long to hold, for research only.`}{' '}
        Chances and returns are against SPY (US) or XIU.TO (TSX), not plain gains.
      </p>
      {groups.map((g) => (
        <div key={g.label} className="wl-group">
          <h3 className="label">Hold {g.label}</h3>
          <table className="data-table wl-table">
            <thead>
              <tr>
                <th>Stock</th>
                <th className="r">Chance</th>
                <th className="r">Middle (range)</th>
                <th className="r">Costs</th>
              </tr>
            </thead>
            <tbody>
              {g.lines.map((l) => (
                <tr key={l.symbol}>
                  <td className="wl-what">
                    <Link className="sym" href={tickerHref(l.symbol, 'stock')}>
                      {l.symbol}
                    </Link>
                    {l.passes && <span className="chip buy">passes the bar</span>}
                    <span className="sub wl-about">{[l.name, l.market].filter(Boolean).join(' · ')}</span>
                  </td>
                  <td className="r num">{Math.round(l.pBeat * 1000) / 10}%</td>
                  <td className="r num">
                    {pct(l.q50)}{' '}
                    <span className="sub">
                      ({pct(l.q10)} to {pct(l.q90)})
                    </span>
                  </td>
                  <td className="r sub">{l.coversCosts ? 'covers costs' : 'below costs'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </section>
  )
}
