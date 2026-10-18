'use client'

import { useState } from 'react'
import { LineChart } from '@/components/LineChart'
import { Tabs } from '@/components/Tabs'
import { fmtPrice } from '@/lib/format'
import { RANGES, inRange, type PriceSeries, type Range } from '@/lib/ticker'

/** The price history with the mockup's range tabs. The forecast cone joins it with the model. */
export function PriceCard({ symbol, series, coin }: { symbol: string; series: PriceSeries; coin: boolean }) {
  const [range, setRange] = useState<Range>('6m')
  const shown = inRange(series, range)
  const label = RANGES.find((r) => r.value === range)!.label
  return (
    <section className="card card-pad enter" aria-labelledby="chart-h">
      <div className="section-head">
        <h2 id="chart-h">Price</h2>
        {series.values.length > 1 && <Tabs items={RANGES} value={range} onChange={setRange} label="Range" />}
      </div>
      {series.values.length > 1 ? (
        <>
          <LineChart
            series={shown.values}
            dates={shown.days}
            height={280}
            format={(v) => fmtPrice(v, series.currency)}
            label={`${symbol} closes over ${label}`}
          />
          <div className="legend" style={{ marginTop: 8 }}>
            <span>
              <i style={{ background: 'var(--chart-1)' }} />
              {coin ? "Close in CAD: Coinbase's USD close at that day's Bank of Canada rate" : `Close in ${series.currency}`}
            </span>
          </div>
        </>
      ) : (
        <p className="sub" style={{ margin: 0 }}>
          {series.values.length === 0
            ? 'No prices yet. The next run collects a year of closes for held and watched symbols.'
            : 'One close so far; the chart starts with the second.'}
        </p>
      )}
    </section>
  )
}
