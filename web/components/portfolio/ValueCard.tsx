'use client'

import { useMemo, useState } from 'react'
import { LineChart, type Benchmark } from '@/components/LineChart'
import { Tabs } from '@/components/Tabs'
import { TweenNumber } from '@/components/TweenNumber'
import { longDay, shortDay } from '@/lib/dates'
import { fmtMoney, fmtPct } from '@/lib/format'
import type { Period, PeriodReturns } from '@/lib/portfolio/returns'
import type { Totals } from '@/lib/portfolio/valuation'

const PERIOD_TABS = [
  { value: '1m', label: '1M' },
  { value: '3m', label: '3M' },
  { value: '12m', label: '12M' },
  { value: 'all', label: 'All' },
] as const

const last = (values: number[] | null) => (values ? values[values.length - 1] : null)

/** Value and returns (spec §7.4): total value in CAD, and the return against XIU.TO and SPY in CAD. */
export function ValueCard({
  totals,
  periods,
  firstBuy,
}: {
  totals: Totals
  periods: Record<Period, PeriodReturns> | null
  firstBuy: string | null
}) {
  const [period, setPeriod] = useState<Period>('all')
  const r = periods?.[period] ?? null
  const dates = useMemo(() => r?.days.map(shortDay) ?? [], [r])
  const benchmarks = useMemo(() => {
    const lines: Benchmark[] = []
    if (r?.xiu) lines.push({ values: r.xiu, color: 'var(--chart-2)' })
    if (r?.spy) lines.push({ values: r.spy, color: 'var(--chart-3)' })
    return lines
  }, [r])
  const label = {
    '1m': 'over the last month',
    '3m': 'over 3 months',
    '12m': 'over 12 months',
    all: firstBuy ? `since the first buy, ${longDay(firstBuy)}` : 'since the first buy',
  }[period]
  const portfolio = last(r?.portfolio ?? null)
  const xiu = last(r?.xiu ?? null)
  const spy = last(r?.spy ?? null)

  return (
    <section className="card card-pad enter" aria-labelledby="value-h">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <span className="label" id="value-h">
            Portfolio value
          </span>
          <div className="value-big" style={{ marginTop: 8 }}>
            {fmtMoney(totals.valueCad)}
          </div>
          <div className="num" style={{ marginTop: 6, fontSize: 13 }}>
            <span className={totals.gainCad < 0 ? 'loss' : 'gain'}>
              {fmtMoney(totals.gainCad, { signed: true })} unrealized
            </span>{' '}
            <span className="muted">· cost {fmtMoney(totals.costCad)}</span>
          </div>
        </div>
        {r && portfolio !== null && (
          <div className="grid gap-3 justify-items-end">
            <Tabs items={PERIOD_TABS} value={period} onChange={setPeriod} label="Period" />
            <div className="num" style={{ fontSize: 13, textAlign: 'right' }}>
              <span className="muted">{label}</span>
              <br />
              Portfolio{' '}
              <b>
                <TweenNumber value={portfolio} format={fmtPct} className={portfolio < 0 ? 'loss' : 'gain'} />
              </b>
              {xiu !== null && (
                <>
                  {' '}
                  <span className="muted">· XIU.TO</span> <TweenNumber value={xiu} format={fmtPct} />
                </>
              )}
              {spy !== null && (
                <>
                  {' '}
                  <span className="muted">· SPY in CAD</span> <TweenNumber value={spy} format={fmtPct} />
                </>
              )}
            </div>
          </div>
        )}
      </div>
      {r ? (
        <>
          <div style={{ marginTop: 14 }}>
            <LineChart
              series={r.portfolio}
              dates={dates}
              benchmarks={benchmarks}
              height={230}
              format={(v) => fmtPct(v)}
              label="Portfolio return against XIU.TO and SPY in CAD"
            />
          </div>
          <div className="legend" style={{ marginTop: 6 }}>
            <span>
              <i style={{ background: 'var(--chart-1)' }} />
              Portfolio
            </span>
            {r.xiu && (
              <span>
                <i style={{ background: 'var(--chart-2)' }} />
                XIU.TO
              </span>
            )}
            {r.spy && (
              <span>
                <i style={{ background: 'var(--chart-3)' }} />
                SPY in CAD
              </span>
            )}
          </div>
        </>
      ) : (
        <p className="sub" style={{ margin: '14px 0 0' }}>
          {firstBuy
            ? 'The chart starts once your holdings have closes on two trading days. The pipeline stores them each run.'
            : 'No holdings yet. Add your first buy to start.'}
        </p>
      )}
    </section>
  )
}
