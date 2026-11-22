'use client'

import { useState } from 'react'
import { LineChart } from '@/components/LineChart'
import { Tabs } from '@/components/Tabs'
import { useForecast } from '@/components/ticker/ForecastCard'
import { fmtPrice } from '@/lib/format'
import { RANGES, inRange, type PriceSeries, type Range } from '@/lib/ticker'

/**
 * The header card's chart (ticker_2.html): the price history and, when the run forecast the asset, the likely
 * range ahead at the Outlook card's horizon; under it the period control and the legend.
 */
export function PriceChart({ symbol, series, coin }: { symbol: string; series: PriceSeries; coin: boolean }) {
  const [range, setRange] = useState<Range>('6m')
  const forecast = useForecast()
  const cone = series.values.length > 1 ? forecast?.cone : undefined
  const shown = inRange(series, range)
  const label = RANGES.find((r) => r.value === range)!.label
  const days = forecast?.row ? `${forecast.row.horizon} ${forecast.forecast.span}` : null
  return (
    <div className="t-chart">
      {/* The page's outline: the card is the price and its forecast. */}
      <h2 id="chart-h" className="sr-only">
        {cone ? 'Price and forecast' : 'Price'}
      </h2>
      {series.values.length > 1 ? (
        <>
          <LineChart
            series={shown.values}
            dates={shown.days}
            height={240}
            format={(v) => fmtPrice(v, series.currency)}
            label={`${symbol} closes over ${label}${cone ? `, with the forecast ${cone.label}` : ''}`}
            cone={cone}
          />
          <div className="chart-foot">
            <Tabs className="seg" items={RANGES} value={range} onChange={setRange} label="Range" />
            <div className="legend">
              <span>
                <i style={{ background: 'var(--chart-1)' }} />
                {coin ? "Close in CAD: Coinbase's USD close at that day's Bank of Canada rate" : `Close in ${series.currency}`}
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
