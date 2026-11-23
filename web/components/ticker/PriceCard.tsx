'use client'

import { useState, useTransition } from 'react'
import { loadTickerDay } from '@/app/(app)/intraday'
import { LineChart } from '@/components/LineChart'
import { Tabs } from '@/components/Tabs'
import { useForecast } from '@/components/ticker/ForecastCard'
import { todayInToronto } from '@/lib/dates'
import { fmtPrice } from '@/lib/format'
import type { DayChart } from '@/lib/intraday'
import { RANGES, inRange, type PriceSeries, type Range } from '@/lib/ticker'
import { moveWhen } from '@/lib/today'

/**
 * The header card's chart (ticker_2.html): the price history and, when the run forecast the asset, the likely
 * range ahead at the Outlook card's horizon; under it the period control and the legend. 1D is the latest session
 * every 5 minutes against the previous close, fetched live from Yahoo when picked (lib/intraday.ts); it falls back to
 * the last two closes when Yahoo doesn't answer.
 */
export function PriceChart({ symbol, series, coin }: { symbol: string; series: PriceSeries; coin: boolean }) {
  const [range, setRange] = useState<Range>('6m')
  // the 1D chart: undefined until 1D is first picked, null when Yahoo didn't answer
  const [day, setDay] = useState<DayChart | null | undefined>(undefined)
  const [loading, startLoading] = useTransition()
  const pick = (r: Range) => {
    setRange(r)
    if (r === '1d' && day === undefined && !loading) {
      startLoading(async () => setDay(await loadTickerDay(symbol, coin ? 'crypto' : 'stock').catch(() => null)))
    }
  }
  const live = range === '1d' ? (day ?? null) : null
  const waiting = range === '1d' && (loading || day === undefined)
  const forecast = useForecast()
  // the forecast starts from the last close: it belongs to the daily ranges, not to a day's 5-minute line
  const cone = series.values.length > 1 && !live ? forecast?.cone : undefined
  const shown = inRange(series, range)
  const label = live ? `the day ${moveWhen(live.day, todayInToronto())}` : RANGES.find((r) => r.value === range)!.label
  const days = forecast?.row ? `${forecast.row.horizon} ${forecast.forecast.span}` : null
  return (
    <div className="t-chart">
      {/* The page's outline: the card is the price and its forecast. */}
      <h2 id="chart-h" className="sr-only">
        {cone ? 'Price and forecast' : 'Price'}
      </h2>
      {series.values.length > 1 ? (
        <>
          {waiting ? (
            <div className="chart chart-wait" style={{ height: 240 }} aria-busy="true">
              <span className="sub">Loading the day&apos;s prices…</span>
            </div>
          ) : live ? (
            <LineChart
              series={live.values}
              dates={live.labels}
              slots={live.slots}
              baseline={live.base}
              height={240}
              format={(v) => fmtPrice(v, series.currency)}
              label={`${symbol} every 5 minutes over ${label}, against the previous close`}
            />
          ) : (
            <LineChart
              series={shown.values}
              dates={shown.days}
              height={240}
              format={(v) => fmtPrice(v, series.currency)}
              label={`${symbol} closes over ${label}${cone ? `, with the forecast ${cone.label}` : ''}`}
              cone={cone}
            />
          )}
          <div className="chart-foot">
            <Tabs className="seg" items={RANGES} value={range} onChange={pick} label="Range" />
            <div className="legend">
              <span>
                <i style={{ background: 'var(--chart-1)' }} />
                {live
                  ? `Every 5 minutes ${moveWhen(live.day, todayInToronto())} in ${coin ? 'CAD' : series.currency}; dashed: the previous close`
                  : range === '1d' && day === null
                    ? `Close in ${coin ? 'CAD' : series.currency} · Yahoo didn't answer: the last two closes`
                    : coin
                      ? "Close in CAD: Coinbase's USD close at that day's Bank of Canada rate"
                      : `Close in ${series.currency}`}
              </span>
              {cone && (
                <>
                  <span>
                    <i style={{ background: 'var(--chart-5)', height: 8 }} />
                    Likely range, {days}
                  </span>
                  <span>
                    <i style={{ background: 'var(--chart-4)' }} />
                    Median
                  </span>
                </>
              )}
            </div>
          </div>
        </>
      ) : (
        <p className="sub" style={{ margin: 0 }}>
          {series.values.length === 0
            ? 'No prices yet. The next run collects a year of closes for held and watched symbols.'
            : 'One close so far; the chart starts with the second.'}
        </p>
      )}
    </div>
  )
}
