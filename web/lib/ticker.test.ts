import { describe, expect, it } from 'vitest'
import { addDays } from './dates'
import { FxRates } from './portfolio/lookup'
import type { Close } from './portfolio/types'
import { fmtScore, headlineSince, inRange, lastMove, priceSeries, safeLink, tickerHref, tone, type PriceSeries } from './ticker'

const FX = new FxRates([
  { day: '2026-10-01', usdCad: 1.4 },
  { day: '2026-10-05', usdCad: 1.5 },
])
const closes = (currency: 'USD' | 'CAD', points: [string, number][]): Close[] =>
  points.map(([day, close]) => ({ day, close, currency }))

describe('priceSeries', () => {
  it('keeps a stock in its own currency', () => {
    expect(priceSeries(closes('USD', [['2026-10-01', 200], ['2026-10-02', 210]]), 'stock', FX)).toEqual({
      days: ['2026-10-01', '2026-10-02'],
      values: [200, 210],
      currency: 'USD',
    })
    expect(priceSeries(closes('CAD', [['2026-10-01', 180]]), 'stock', FX).currency).toBe('CAD')
  })

  it("converts a coin to CAD at each day's rate, leaving out days before any rate", () => {
    const series = priceSeries(closes('USD', [['2026-09-30', 1], ['2026-10-01', 100], ['2026-10-06', 100]]), 'crypto', FX)
    expect(series).toEqual({ days: ['2026-10-01', '2026-10-06'], values: [140, 150], currency: 'CAD' })
  })
})

describe('ranges and the last move', () => {
  const series = { days: Array.from({ length: 30 }, (_, i) => `d${i}`), values: Array.from({ length: 30 }, (_, i) => 100 + i), currency: 'CAD' as const }

  /** Closes from `from` to `to`, every day or only on weekdays. */
  const dated = (from: string, to: string, weekdaysOnly = false): PriceSeries => {
    const days: string[] = []
    for (let day = from; day <= to; day = addDays(day, 1)) {
      const weekday = new Date(`${day}T12:00:00Z`).getUTCDay()
      if (!weekdaysOnly || (weekday !== 0 && weekday !== 6)) days.push(day)
    }
    return { days, values: days.map((_, i) => 100 + i), currency: 'CAD' }
  }

  it('cuts a range by calendar date, from the last close on or before its cutoff', () => {
    // A coin closes every day: its month and year are a month and a year of days.
    const daily = dated('2025-09-01', '2026-10-16')
    const month = inRange(daily, '1m')
    const year = inRange(daily, '1y')
    expect([month.days[0], month.days.at(-1)]).toEqual(['2026-09-15', '2026-10-16'])
    expect(month.values[0]).toBe(daily.values[daily.days.indexOf('2026-09-15')])
    expect([year.days[0], year.days.at(-1)]).toEqual(['2025-10-16', '2026-10-16'])
    expect([inRange(daily, '1d').days[0], inRange(daily, '1w').days[0]]).toEqual(['2026-10-15', '2026-10-09'])
    // A stock to Wednesday Oct 14: the month's cutoff is Sunday Sep 13, so it starts on Friday Sep 11.
    const stock = dated('2026-01-01', '2026-10-14', true)
    expect(inRange(stock, '1m').days[0]).toBe('2026-09-11')
    expect(inRange(stock, '1d').days[0]).toBe('2026-10-13')
    expect(inRange(stock, '1w').days[0]).toBe('2026-10-07')
  })

  it('starts at the first close when none is as old as the range', () => {
    expect(inRange(dated('2026-08-01', '2026-10-16'), '6m').days[0]).toBe('2026-08-01')
  })

  it('gives the latest close and its move from the one before', () => {
    expect(lastMove(series)).toEqual({ price: 129, day: 'd29', change: 1, pct: (1 / 128) * 100 })
    expect(lastMove({ ...series, days: ['d0'], values: [100] })).toEqual({ price: 100, day: 'd0', change: null, pct: null })
    expect(lastMove({ ...series, days: [], values: [] })).toBeNull()
  })
})

describe('tickerHref', () => {
  it('links a stock by its symbol and a coin with its asset type', () => {
    expect(tickerHref('RY.TO', 'stock')).toBe('/ticker/RY.TO')
    expect(tickerHref('BTC', 'crypto')).toBe('/ticker/BTC?asset=crypto')
  })
})

describe('news', () => {
  it('only links to web pages', () => {
    expect(safeLink('https://finance.yahoo.com/news/x.html')).toBe('https://finance.yahoo.com/news/x.html')
    expect(safeLink('javascript:alert(1)')).toBeNull()
    expect(safeLink('not a url')).toBeNull()
  })

  it('writes scores with a sign and colours them past ±0.2', () => {
    expect([fmtScore(0.25), fmtScore(-0.224), fmtScore(0), fmtScore(-0.001)]).toEqual(['+0.25', '−0.22', '+0.00', '+0.00'])
    expect([tone(0.25), tone(-0.22), tone(0.08), tone(null)]).toEqual(['pos', 'neg', 'neu', 'neu'])
  })
})

describe('headlineSince', () => {
  const now = new Date('2026-11-01T22:00:00Z') // a Sunday evening: the last run was Friday's

  it("starts 48 hours before the run whose counts the page shows, not before now", () => {
    expect(headlineSince({ started_at: '2026-10-30T13:00:00Z' }, now)).toBe('2026-10-28T13:00:00.000Z')
  })

  it('starts 48 hours before now when there is no run yet', () => {
    expect(headlineSince(null, now)).toBe('2026-10-30T22:00:00.000Z')
  })
})
