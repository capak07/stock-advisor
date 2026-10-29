'use client'

import { useState } from 'react'
import { LineChart } from '@/components/LineChart'
import { Tabs } from '@/components/Tabs'
import { ForecastKpis, HorizonTabs, useForecast } from '@/components/ticker/ForecastCard'
import { fmtPrice } from '@/lib/format'
import { RANGES, inRange, type PriceSeries, type Range } from '@/lib/ticker'

/** The price history with the mockup's range tabs and, when the run forecast the stock, its cone and horizon tabs. */
export function PriceCard({ symbol, series, coin }: { symbol: string; series: PriceSeries; coin: boolean }) {
  const [range, setRange] = useState<Range>('6m')
  const forecast = useForecast()
  const cone = series.values.length > 1 ? forecast?.cone : undefined
  const shown = inRange(series, range)
  const label = RANGES.find((r) => r.value === range)!.label
  return (
    <section className="card card-pad enter" aria-labelledby="chart-h">
      <div className="section-head">
        <h2 id="chart-h">{cone ? 'Price and forecast' : 'Price'}</h2>
        {cone && <HorizonTabs />}
      </div>
      {series.values.length > 1 && (
        <div className="chart-ranges">
          <Tabs className="compact" items={RANGES} value={range} onChange={setRange} label="Range" />
        </div>
      )}
      {series.values.length > 1 ? (
        <>
          <LineChart
            series={shown.values}
            dates={shown.days}
            height={280}
            format={(v) => fmtPrice(v, series.currency)}
            label={`${symbol} closes over ${label}${cone ? `, with the forecast ${cone.label}` : ''}`}
            cone={cone}
          />
          <div className="legend" style={{ marginTop: 8 }}>
            <span>
              <i style={{ background: 'var(--chart-1)' }} />
              {coin ? "Close in CAD: Coinbase's USD close at that day's Bank of Canada rate" : `Close in ${series.currency}`}
            </span>
            {cone && (
              <>
                <span>
                  <i style={{ background: 'var(--chart-4)' }} />
                  Median forecast
                </span>
                <span>
                  <i style={{ background: 'var(--chart-5)', height: 8 }} />
                  Likely range, q10 to q90
                </span>
              </>
            )}
          </div>
        </>
      ) : (
        <p className="sub" style={{ margin: 0 }}>
          {series.values.length === 0
            ? 'No prices yet. The next run collects a year of closes for held and watched symbols.'
            : 'One close so far; the chart starts with the second.'}
        </p>
      )}
      <ForecastKpis />
    </section>
  )
}
