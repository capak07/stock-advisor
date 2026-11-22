'use client'

import { useMemo, useState } from 'react'
import { LineChart, type Benchmark } from '@/components/LineChart'
import { Tabs } from '@/components/Tabs'
import { TweenNumber } from '@/components/TweenNumber'
import { longDay, shortDay } from '@/lib/dates'
import { fmtMoney, fmtPct } from '@/lib/format'
import { dayMove, type Period, type PeriodReturns } from '@/lib/portfolio/returns'
import type { Totals } from '@/lib/portfolio/valuation'

const PERIOD_TABS = [
  { value: '1d', label: '1D' },
  { value: '1w', label: '1W' },
  { value: '1m', label: '1M' },
  { value: '3m', label: '3M' },
  { value: '12m', label: '12M' },
  { value: 'all', label: 'All' },
] as const

const last = (values: number[] | null) => (values && values.length > 0 ? values[values.length - 1] : null)

const tone = (value: number) => (value < 0 ? 'loss' : 'gain')

/**
 * The value hero (spec §7.2): total value in CAD, the unrealized gain, today's move, the return since the first buy,
 * and the chosen period's return against SPY and XIU.TO in CAD. No cash line: the app keeps no cash balance.
 */
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
    '1d': 'over the last day',
    '1w': 'over the last week',
    '1m': 'over the last month',
    '3m': 'over 3 months',
    '12m': 'over 12 months',
    all: firstBuy ? `since the first buy, ${longDay(firstBuy)}` : 'since the first buy',
  }[period]
  const portfolio = last(r?.portfolio ?? null)
  const xiu = last(r?.xiu ?? null)
  const spy = last(r?.spy ?? null)
  const move = dayMove(totals.valueCad, periods)
  const allTime = last(periods?.all.portfolio ?? null)

  return (
    <section className="card hero card-pad value-hero enter" aria-labelledby="value-h">
      <div className="hero-top">
        <div>
          <span className="label" id="value-h">
            Total value
          </span>
          <div className="big num" style={{ margin: '8px 0 6px' }}>
            {fmtMoney(totals.valueCad, { digits: 2 })}
          </div>
          {totals.costCad > 0 && (
            <div className={`num ${tone(totals.gainCad)}`} style={{ fontSize: 14 }}>
              {fmtMoney(totals.gainCad, { signed: true })} ({fmtPct((totals.gainCad / totals.costCad) * 100)}) unrealized
            </div>
          )}
        </div>
        {totals.costCad > 0 && (
          <div className="hero-meta">
            {move && (
              <div>
                <div className="label">Today</div>
                <div className={`num ${tone(move.pct)}`}>
                  {fmtMoney(move.cad, { digits: 2, signed: true })} ({fmtPct(move.pct)})
                </div>
              </div>
            )}
            {allTime !== null && (
              <div>
                <div className="label">All time</div>
                <div className={`num ${tone(allTime)}`}>{fmtPct(allTime)}</div>
              </div>
            )}
            <div>
              <div className="label">Cost</div>
              <div className="num">{fmtMoney(totals.costCad)}</div>
            </div>
          </div>
        )}
      </div>
      {r && portfolio !== null ? (
        <>
          <div className="chart-bar">
            <Tabs className="seg" items={PERIOD_TABS} value={period} onChange={setPeriod} label="Period" />
            <div className="legend">
              <span>
                <i style={{ background: 'var(--chart-1)' }} />
                You{' '}
                <b>
                  <TweenNumber value={portfolio} format={fmtPct} className={tone(portfolio)} />
                </b>
              </span>
              {spy !== null && (
                <span>
                  <i style={{ background: 'var(--chart-3)' }} />
                  SPY{' '}
                  <b>
                    <TweenNumber value={spy} format={fmtPct} />
                  </b>
                </span>
              )}
              {xiu !== null && (
                <span>
                  <i style={{ background: 'var(--chart-2)' }} />
                  XIU.TO{' '}
                  <b>
                    <TweenNumber value={xiu} format={fmtPct} />
                  </b>
                </span>
              )}
            </div>
          </div>
          <p className="sub chart-note">{label} · SPY and XIU.TO in CAD</p>
          <LineChart
            series={r.portfolio}
            dates={dates}
            benchmarks={benchmarks}
            height={210}
            format={(v) => fmtPct(v)}
            label="Portfolio return against XIU.TO and SPY in CAD"
          />
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
