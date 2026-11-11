import { etClock, fmtR, outcomeLine, priceOf, whyNotTop3, type Signal } from '@/lib/daytrade'

const r = (value: number | null) => (value === null ? '—' : fmtR(value))

/** Every signal of the day with its net R values and why it is (or isn't) in the after-costs top 3; the skill's top 3 are marked. */
export function SignalTable({ signals }: { signals: Signal[] }) {
  return (
    <section className="card card-pad enter" aria-labelledby="dt-other-h">
      <div className="section-head" style={{ marginBottom: 6 }}>
        <h2 id="dt-other-h">Other signals today</h2>
        <span className="sub">every signal the scan found · New York time</span>
      </div>
      <div className="dt-scroll">
        <table className="data-table dt-table" aria-labelledby="dt-other-h">
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
                <td className="r num">{r(s.netHistoryR)}</td>
                <td className="r num">{r(s.netReplayR)}</td>
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
    </section>
  )
}
