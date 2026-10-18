import { describe, expect, it } from 'vitest'
import { FxRates } from './portfolio/lookup'
import type { Close } from './portfolio/types'
import { fmtScore, inRange, lastMove, priceSeries, safeLink, tickerHref, tone } from './ticker'

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

  it('keeps the last 21 trading days plus the close before', () => {
    const month = inRange(series, '1m')
    expect(month.days).toHaveLength(22)
    expect(month.days[0]).toBe('d8')
    expect(inRange(series, '1y').days).toHaveLength(30)
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
