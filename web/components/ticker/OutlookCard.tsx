'use client'

import { Info, Scale } from 'lucide-react'
import { LowRankChip } from '@/components/LowRankChip'
import { PICK_BAR } from '@/components/picks/BestChance'
import { RangeBar } from '@/components/picks/RangeBar'
import { Tabs } from '@/components/Tabs'
import { useForecast } from '@/components/ticker/ForecastCard'
import { fmtPct, fmtPrice } from '@/lib/format'
import { edgeWords } from '@/lib/outlook'
import type { Currency } from '@/lib/portfolio/types'
import type { Verdict } from '@/lib/verdicts'

const chance = (p: number) => `${Math.round(p * 100)}%`

/**
 * The stock page's Outlook (spec §7.7, ticker_2.html): the run's verdict in words as the headline ("No clear
 * edge" for a Hold or no verdict), the chance of beating the market as a number at the selected horizon, the
 * horizon control (only the horizons the run forecast), the picks' bar, and the likely price range there if
 * the benchmark is flat. `judgedAt` is the horizon the verdict was judged at. Without a forecast it says when
 * one appears (`emptyText`).
 */
export function OutlookCard({
  verdict,
  judgedAt,
  price,
  currency,
  coin,
  lowRank,
  emptyText,
}: {
  verdict: Verdict | null
  judgedAt: number | null
  /** The last price, in `currency`; null before the first close. */
  price: number | null
  currency: Currency
  coin: boolean
  /** How many stocks the run ranked, when it flagged this one's low model rank. */
  lowRank?: number
  emptyText: string
}) {
  const f = useForecast()
  const head = (
    <h2 id="outlook-h">
      <Scale aria-hidden="true" />
      Outlook
    </h2>
  )
  if (!f || !f.row) {
    return (
      <section className="card card-pad enter t-outlook" id="outlook" aria-labelledby="outlook-h">
        <div className="section-head">{head}</div>
        {f ? (
          <p className="sub" style={{ margin: 0 }}>
            No forecast this run. Its earlier picks are under Past picks.
          </p>
        ) : (
          <div className="banner info">
            <Info />
            <div>{emptyText}</div>
          </div>
        )}
      </section>
    )
  }
  const { row, forecast } = f
  const span = forecast.span
  const bench = forecast.benchmark
  const n = row.horizon
  const at = (q: number) => (price === null ? null : fmtPrice(price * (1 + q), currency))
  const scale = [
    { label: 'Low (q10)', q: row.q10 },
    { label: 'Median', q: row.q50 },
    { label: 'High (q90)', q: row.q90 },
  ]
  return (
    <section className="card card-pad enter t-outlook" id="outlook" aria-labelledby="outlook-h">
      <div className="section-head">
        {head}
        <Tabs
          className="seg"
          items={forecast.horizons.map((h) => ({ value: String(h.horizon), label: `${h.horizon}d` }))}
          value={String(n)}
          onChange={(v) => f.setHorizon(Number(v))}
          label={`Forecast horizon in ${span}`}
        />
      </div>
      <div className="edge-line">
        <span className="headline-edge" data-testid="edge">
          {edgeWords(verdict)}
        </span>
        {lowRank !== undefined && <LowRankChip scored={lowRank} />}
      </div>
      {verdict !== null && judgedAt !== null && judgedAt !== n && (
        <p className="sub small" style={{ margin: '0 0 4px' }}>
          The verdict is for {judgedAt} {span}.
        </p>
      )}
      <div className="chance" data-testid="chance">
        <span className="num">{chance(row.pBeat)}</span>
        <span className="sub">
          chance to beat {coin ? bench : 'the market'} over {n} {span}
        </span>
      </div>
      <p className="sub small" style={{ margin: '8px 0 0' }}>
        A coin flip is 50%.{coin ? '' : ` Picks need ${PICK_BAR}.`}
      </p>
      <div className="outlook-range">
        <span className="label">
          Likely range at {n} {span}
        </span>
        <RangeBar q10={row.q10} q50={row.q50} q90={row.q90} benchmark={bench} />
        <div className="scale">
          {scale.map((s) => (
            <div key={s.label}>
              <span className="label">{s.label}</span>
              <b>{at(s.q) ?? fmtPct(s.q * 100)}</b>
              {price !== null && <span className="num sub">{fmtPct(s.q * 100)}</span>}
            </div>
          ))}
        </div>
        <p className="sub small" style={{ margin: '10px 0 0' }}>
          {price !== null && <>The circle is the last price, {fmtPrice(price, currency)}. </>}
          If {bench} is flat, the price should land inside the range about 8 times in 10.
        </p>
        {forecast.advice?.basis && (
          <p className="sub small" style={{ margin: '6px 0 0' }}>
            {forecast.advice.basis}
          </p>
        )}
      </div>
    </section>
  )
}

/** On a phone, under the price: the outlook in one line, linking to the Outlook card. Nothing without a forecast. */
export function PhoneOutlook({ verdict, coin }: { verdict: Verdict | null; coin: boolean }) {
  const f = useForecast()
  if (!f || !f.row) return null
  const words = edgeWords(verdict)
  return (
    <a className="phone-outlook" href="#outlook">
      <Scale aria-hidden="true" />
      <span>
        <b>
          Outlook ({f.row.horizon} {f.forecast.span}): {words === 'No clear edge' ? 'no clear edge' : words}.
        </b>{' '}
        <span className="sub">
          {chance(f.row.pBeat)} chance to beat {coin ? f.forecast.benchmark : 'the market'}.
        </span>
      </span>
    </a>
  )
}
