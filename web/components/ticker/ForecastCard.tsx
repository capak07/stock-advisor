'use client'

import { Calendar, FileText } from 'lucide-react'
import { createContext, useContext, useMemo, useState } from 'react'
import type { Cone } from '@/components/LineChart'
import { Tabs } from '@/components/Tabs'
import { catalystText, costText, describeFactor, factorBars } from '@/lib/advice'
import type { ForecastHorizon, PastPick, TickerForecast } from '@/lib/data/ticker'
import { shortDay } from '@/lib/dates'
import { fmtPct } from '@/lib/format'

const pct = (fraction: number) => fmtPct(fraction * 100)
const STYLE = { swing: 'Swing', position: 'Position' } as const

interface Selected {
  forecast: TickerForecast
  row: ForecastHorizon | null
  setHorizon: (h: number) => void
  cone: Cone | undefined
}

const ForecastContext = createContext<Selected | null>(null)

/** The forecast's selected horizon, shared by the price chart's cone and its odds. */
export function ForecastProvider({ forecast, children }: { forecast: TickerForecast | null; children: React.ReactNode }) {
  const horizons = forecast?.horizons ?? []
  const preferred = forecast?.advice?.horizon
  const [horizon, setHorizon] = useState<number | null>(
    horizons.find((h) => h.horizon === preferred)?.horizon ?? horizons[0]?.horizon ?? null,
  )
  const row = horizons.find((h) => h.horizon === horizon) ?? null
  const benchmark = forecast?.benchmark
  const span = forecast?.span ?? 'trading days'
  // one object per horizon: the chart morphs whenever the cone changes identity
  const cone = useMemo(
    () =>
      row && benchmark
        ? { q10: row.q10, q50: row.q50, q90: row.q90, label: `+${row.horizon} ${span} · if ${benchmark} is flat`, short: `+${row.horizon}d` }
        : undefined,
    [row, benchmark, span],
  )
  const value = useMemo(() => (forecast ? { forecast, row, setHorizon, cone } : null), [forecast, row, cone])
  return <ForecastContext.Provider value={value}>{children}</ForecastContext.Provider>
}

export const useForecast = () => useContext(ForecastContext)

/** The horizon tabs: only the horizons this run forecast. */
export function HorizonTabs() {
  const f = useForecast()
  if (!f || !f.row) return null
  const items = f.forecast.horizons.map((h) => ({ value: String(h.horizon), label: `${h.horizon}d` }))
  return (
    <Tabs items={items} value={String(f.row.horizon)} onChange={(v) => f.setHorizon(Number(v))} label={`Forecast horizon in ${f.forecast.span}`} />
  )
}

/** Under the chart: the odds of beating the benchmark, the median and the likely range at the selected horizon. */
export function ForecastKpis() {
  const f = useForecast()
  if (!f || !f.row) return null
  const { row } = f
  const bench = f.forecast.benchmark
  return (
    <div className="kpis" id="forecast-kpis" style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
      <div className="kpi">
        <span className="label">Beats {bench}</span>
        <b>{Math.round(row.pBeat * 100)}%</b>
        <span className="sub">over {row.horizon} {f.forecast.span}</span>
        {f.forecast.advice?.basis && <span className="sub">{f.forecast.advice.basis}</span>}
      </div>
      <div className="kpi">
        <span className="label">Median</span>
        <b className={row.q50 < 0 ? 'loss' : 'gain'}>{pct(row.q50)}</b>
        <span className="sub">relative to {bench}</span>
      </div>
      <div className="kpi">
        <span className="label">Likely range</span>
        <b>
          {pct(row.q10)} to {pct(row.q90)}
        </b>
        <span className="sub">q10 to q90, relative to {bench}</span>
      </div>
    </div>
  )
}

function Result({ pick, benchmark }: { pick: PastPick; benchmark: string }) {
  const o = pick.outcome
  if (pick.status === 'open' || !o) return <span className="sub">{pick.status === 'exited_early' ? 'exited early' : 'open'}</span>
  const ret = <span className={`num ${o.ret < 0 ? 'loss' : 'gain'}`}>{pct(o.ret)}</span>
  if (pick.status === 'exited_early') {
    return (
      <span>
        <span className="sub">exited early</span> · {ret}
      </span>
    )
  }
  return (
    <span>
      {ret}{' '}
      <span className="sub">
        vs {benchmark} <span className={`num ${o.excess < 0 ? 'loss' : 'gain'}`}>{pct(o.excess)}</span>
      </span>{' '}
      <span className={o.beat ? 'gain' : 'loss'} aria-label={o.beat ? 'beat' : 'missed'}>
        {o.beat ? '✓' : '✗'}
      </span>
    </span>
  )
}

/**
 * The forecast's explanation (spec §9, ticker_1.html): top factors and catalysts at the stock's
 * representative horizon, and its earlier picks. A stock the latest run didn't forecast keeps its past picks.
 */
export function ForecastCard({ usdFxFeePct, market }: { usdFxFeePct: number; market: 'US' | 'TSX' }) {
  const f = useForecast()
  if (!f) return null
  const { forecast } = f
  const bench = forecast.benchmark
  const advice = forecast.advice
  const bars = advice ? factorBars(advice.topFactors) : []
  const graded = forecast.pastPicks.filter((p) => p.status === 'graded' && p.outcome)
  const beat = graded.filter((p) => p.outcome!.beat).length
  return (
    <>
      {forecast.horizons.length === 0 && (
        <section className="card card-pad enter" aria-labelledby="forecast-h">
          <h2 id="forecast-h" style={{ marginBottom: 6 }}>
            Forecast
          </h2>
          <p className="sub" style={{ margin: 0 }}>
            No forecast this run. Its earlier picks are below.
          </p>
        </section>
      )}
      {advice && advice.topFactors.length > 0 && (
        <section className="card card-pad enter" aria-labelledby="factors-h">
          <div className="section-head" style={{ marginBottom: 4 }}>
            <h2 id="factors-h">Top factors</h2>
            <span className="sub">what moves the {advice.horizon}-day forecast, and which way</span>
          </div>
          {advice.topFactors.map((factor, i) => (
            <div key={factor.feature} className="factor">
              <span>{describeFactor(factor.feature, factor.value, bench)}</span>
              <div className="bar" role="img" aria-label={bars[i].up ? 'raises the forecast' : 'lowers the forecast'}>
                <span
                  style={{
                    left: `${bars[i].up ? 50 : 50 - bars[i].width}%`,
                    width: `${bars[i].width}%`,
                    background: bars[i].up ? 'var(--gain)' : 'var(--loss)',
                  }}
                />
              </div>
            </div>
          ))}
          {advice.cost !== null && (
            <p className="sub" style={{ margin: '8px 0 0' }}>
              Est. cost {costText(market, advice.cost, usdFxFeePct)}
            </p>
          )}
        </section>
      )}
      {advice && (
        <section className="card card-pad enter" aria-labelledby="catalysts-h">
          <h2 id="catalysts-h" style={{ marginBottom: 10 }}>
            Catalysts
          </h2>
          <div className="grid gap-2" id="catalysts" style={{ fontSize: 13 }}>
            {advice.catalysts.length === 0 ? (
              <span className="sub">No catalysts inside the hold</span>
            ) : (
              advice.catalysts.map((c) => (
                <span key={`${c.type}:${c.date}`} className="flex items-center gap-2">
                  {c.type === '8-K' ? <FileText style={{ width: 15, height: 15 }} /> : <Calendar style={{ width: 15, height: 15 }} />}
                  {catalystText(c)}
                </span>
              ))
            )}
          </div>
        </section>
      )}
      {forecast.pastPicks.length > 0 && (
        <section className="card card-pad enter" aria-labelledby="past-h">
          <div className="section-head" style={{ marginBottom: 6 }}>
            <h2 id="past-h">Past picks</h2>
            {graded.length > 0 && (
              <span className="sub">
                {graded.length} graded · {beat} beat {bench}
              </span>
            )}
          </div>
          <div className="table-scroll">
            <table className="data-table" id="past-picks">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Style</th>
                  <th className="r">Horizon</th>
                  <th className="r">P(beat)</th>
                  <th>Exit by</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {forecast.pastPicks.map((p) => (
                  <tr key={p.id}>
                    <td className="num">{shortDay(p.day)}</td>
                    <td>{STYLE[p.style]}</td>
                    <td className="r num">{p.horizon}d</td>
                    <td className="r num">{p.pBeat === null ? '—' : `${Math.round(p.pBeat * 100)}%`}</td>
                    <td className="num">{shortDay(p.exitBy)}</td>
                    <td>
                      <Result pick={p} benchmark={bench} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  )
}
