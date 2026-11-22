import { ChevronDown } from 'lucide-react'
import { etClock, fmtR, outcomeLine, priceOf, rTone, whyNotTop3, type Signal } from '@/lib/daytrade'

const r = (value: number | null) => (value === null ? '—' : fmtR(value))

/**
 * Every signal of the day with its net R values and why it is (or isn't) in the after-costs top 3; the
 * skill's top 3 are marked. Collapsed under "All signals" with the count (spec §7.3).
 */
export function SignalTable({ signals }: { signals: Signal[] }) {
  return (
    <details className="card card-pad enter dt-all">
      <summary>
        <h2 id="dt-all-h">
          All signals <span className="count">{signals.length}</span>
        </h2>
        <span className="sub dt-all-hint">every signal the scan found · New York time</span>
        <ChevronDown className="chev" aria-hidden />
      </summary>
      <div className="dt-scroll">
        <table className="data-table dt-table" aria-label="All signals">
          <thead>
            <tr>
              <th>Stock</th>
              <th>Signal</th>
              <th className="r">History, net</th>
              <th className="r">Replays, net</th>
              <th>Cost, round trip</th>
              <th>Now</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((s) => (
              <tr key={s.id} data-symbol={s.symbol}>
                <td>
                  <span className="sym">{s.symbol}</span> <span className="sub">{s.market}</span>
                  {s.skillRank != null && (
                    <>
                      {' '}
                      <span className="chip">skill #{s.skillRank}</span>
                    </>
                  )}
                </td>
                <td className="num">
                  {etClock(s.triggerAt)} at {priceOf(s.entry, s.market)}
                </td>
                <td className={`r num ${rTone(s.netHistoryR) ?? ''}`}>{r(s.netHistoryR)}</td>
                <td className={`r num ${rTone(s.netReplayR) ?? ''}`}>{r(s.netReplayR)}</td>
                <td className="num">
                  {s.costPct.toFixed(2)}% = {s.costR.toFixed(2)}R
                </td>
                <td className="dt-wrap">{outcomeLine(s)}</td>
                <td className="dt-wrap">{whyNotTop3(s)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}
