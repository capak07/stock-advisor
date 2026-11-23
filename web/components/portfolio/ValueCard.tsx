'use client'

import { useMemo, useState, useTransition } from 'react'
import { loadPortfolioDay, type PortfolioDay } from '@/app/(app)/intraday'
import { LineChart } from '@/components/LineChart'
import { Tabs } from '@/components/Tabs'
import { TweenNumber } from '@/components/TweenNumber'
import { longDay, shortDay, todayInToronto } from '@/lib/dates'
import { fmtMoney, fmtPct } from '@/lib/format'
import { priceDirection } from '@/lib/motion'
import { dayMove, type Period, type PeriodReturns } from '@/lib/portfolio/returns'
import type { Totals } from '@/lib/portfolio/valuation'
import { moveWhen } from '@/lib/today'

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
 * and the chosen period's return as one line (owner request 2026-11-23: no SPY or XIU.TO lines). 1D is the latest
 * session every 5 minutes, fetched live from Yahoo when picked (lib/intraday.ts); it falls back to the last two
 * closes when Yahoo doesn't answer. No cash line: the app keeps no cash balance.
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
  // the 1D chart: undefined until 1D is first picked
  const [day, setDay] = useState<PortfolioDay | undefined>(undefined)
  const [loading, startLoading] = useTransition()
  const pick = (p: Period) => {
    setPeriod(p)
    if (p === '1d' && day === undefined && !loading) {
      startLoading(async () => setDay(await loadPortfolioDay().catch(() => ({ chart: null, missing: [] }))))
    }
  }
  const r = periods?.[period] ?? null
  const live = period === '1d' ? (day?.chart ?? null) : null
  const dates = useMemo(() => r?.days.map(shortDay) ?? [], [r])
  const label = {
    '1d': live ? `every 5 minutes ${moveWhen(live.day, todayInToronto())}` : 'over the last day',
    '1w': 'over the last week',
    '1m': 'over the last month',
    '3m': 'over 3 months',
    '12m': 'over 12 months',
    all: firstBuy ? `since the first buy, ${longDay(firstBuy)}` : 'since the first buy',
  }[period]
  const portfolio = live ? last(live.values) : last(r?.portfolio ?? null)
  const waiting = period === '1d' && (loading || day === undefined)
  const missed =
    period !== '1d' || waiting
      ? null
      : !live
        ? "Yahoo didn't answer: the last two closes"
        : day && day.missing.length > 0
          ? `without ${day.missing.join(', ')} (no prices from Yahoo)`
          : null
  const move = dayMove(totals.valueCad, periods)
  const allTime = last(periods?.all.portfolio ?? null)

  return (
    <section className="card hero card-pad value-hero enter" aria-labelledby="value-h">
      <div className="hero-top">
        <div>
          <span className="label" id="value-h">
            Total value
          </span>
          <div className="big num" style={{ margin: '8px 0 6px' }} data-price={priceDirection(move?.pct)}>
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
            <Tabs className="seg" items={PERIOD_TABS} value={period} onChange={pick} label="Period" />
            <div className="legend">
              {!waiting && (
                <span>
                  <i style={{ background: 'var(--chart-1)' }} />
                  You{' '}
                  <b>
                    <TweenNumber value={portfolio} format={fmtPct} className={tone(portfolio)} />
                  </b>
                </span>
              )}
            </div>
          </div>
          <p className="sub chart-note">
            {label}
            {missed && ` · ${missed}`}
          </p>
          {waiting ? (
            <div className="chart chart-wait" style={{ height: 210 }} aria-busy="true">
              <span className="sub">Loading the day&apos;s prices…</span>
            </div>
          ) : live ? (
            <LineChart
              series={live.values}
              dates={live.labels}
              slots={live.slots}
              baseline={0}
              height={210}
              format={(v) => fmtPct(v)}
              label={`Portfolio return ${label}, against the previous close`}
            />
          ) : (
            <LineChart series={r.portfolio} dates={dates} height={210} format={(v) => fmtPct(v)} label={`Portfolio return ${label}`} />
          )}
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
