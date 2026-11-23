import { describe, expect, it } from 'vitest'
import { fetchIntraday, intradayUrl, parseIntraday, portfolioDay, priceDay, yahooSymbolOf, type Intraday } from './intraday'

// 2026-11-23, 9:30 to 4:00 New York time
const OPEN = 1795444200
const CLOSE = 1795467600
const at = (minutes: number) => OPEN + minutes * 60

const yahoo = (over: { timestamp?: unknown[]; close?: unknown[]; meta?: Record<string, unknown> } = {}) => ({
  chart: {
    result: [
      {
        meta: {
          currency: 'USD',
          chartPreviousClose: 148.18,
          tradingPeriods: [[{ start: OPEN, end: CLOSE }]],
          ...over.meta,
        },
        timestamp: over.timestamp ?? [at(0), at(5), at(10)],
        indicators: { quote: [{ close: over.close ?? [150, null, 161.98] }] },
      },
    ],
  },
})

const day = (over: Partial<Intraday>): Intraday => ({
  times: [at(0), at(5), at(10)],
  closes: [100, 110, 120],
  previousClose: 100,
  currency: 'USD',
  start: OPEN,
  end: CLOSE,
  ...over,
})

describe('parseIntraday', () => {
  it("reads the session's bars, skipping a 5 minutes without trades", () => {
    expect(parseIntraday(yahoo())).toEqual({
      times: [at(0), at(10)],
      closes: [150, 161.98],
      previousClose: 148.18,
      currency: 'USD',
      start: OPEN,
      end: CLOSE,
    })
  })

  it('falls back to the current trading period and the previous close', () => {
    const body = yahoo({ meta: { tradingPeriods: undefined, chartPreviousClose: undefined, previousClose: 10, currentTradingPeriod: { regular: { start: OPEN, end: CLOSE } } } })
    expect(parseIntraday(body)).toMatchObject({ previousClose: 10, start: OPEN, end: CLOSE })
  })

  it('leaves out bars outside the session and refuses a body without a previous close, a currency or a bar', () => {
    expect(parseIntraday(yahoo({ timestamp: [OPEN - 300, at(0)], close: [1, 2] }))?.times).toEqual([at(0)])
    expect(parseIntraday(yahoo({ meta: { chartPreviousClose: null } }))).toBeNull()
    expect(parseIntraday(yahoo({ meta: { currency: 'EUR' } }))).toBeNull()
    expect(parseIntraday(yahoo({ close: [null, null, null] }))).toBeNull()
    expect(parseIntraday({ chart: { result: null } })).toBeNull()
    expect(parseIntraday(null)).toBeNull()
  })
})

describe('priceDay', () => {
  it("charts the price against the previous close, over the whole session's 79 slots", () => {
    expect(priceDay(day({}))).toEqual({
      labels: ['9:30 a.m.', '9:35 a.m.', '9:40 a.m.'],
      values: [100, 110, 120],
      base: 100,
      slots: 79,
      day: '2026-11-23',
    })
  })
})

describe('portfolioDay', () => {
  it('values every holding each 5 minutes, as a percent of its value at the previous close', () => {
    // 2 shares at US$100 → 120 (1.4 CAD a USD) and 10 at C$50 → 45, which trades nothing at 9:35
    const chart = portfolioDay([
      { qty: 2, toCad: 1.4, day: day({}) },
      { qty: 10, toCad: 1, day: day({ times: [at(0), at(10)], closes: [50, 45], previousClose: 50, currency: 'CAD' }) },
    ])!
    // base 2 × 100 × 1.4 + 10 × 50 = 780
    expect(chart.labels).toEqual(['9:30 a.m.', '9:35 a.m.', '9:40 a.m.'])
    expect(chart.values.map((v) => +v.toFixed(4))).toEqual([0, +((808 / 780 - 1) * 100).toFixed(4), +((786 / 780 - 1) * 100).toFixed(4)])
    expect(chart).toMatchObject({ base: 0, slots: 79, day: '2026-11-23' })
  })

  it("holds a market that didn't trade in the latest session at its last price, so it moves nothing", () => {
    // RY.TO's last session was the day before (a TSX holiday): only the US stock moves
    const before = day({ times: [at(0) - 86_400], closes: [60], previousClose: 55, start: OPEN - 86_400, end: CLOSE - 86_400, currency: 'CAD' })
    const chart = portfolioDay([
      { qty: 1, toCad: 1, day: day({}) },
      { qty: 1, toCad: 1, day: before },
    ])!
    expect(chart.values.map((v) => +v.toFixed(4))).toEqual([0, 6.25, 12.5]) // (100+60 → 110+60 → 120+60) over 160
  })

  it('is null without holdings', () => {
    expect(portfolioDay([])).toBeNull()
  })
})

describe('fetchIntraday', () => {
  it('asks Yahoo once per asset, a coin as its CAD pair, and leaves out one that fails', async () => {
    const urls: string[] = []
    const fake = async (url: string) => {
      urls.push(url)
      if (url.includes('NVDA')) return new Response('nope', { status: 500 })
      return Response.json(yahoo())
    }
    const got = await fetchIntraday(
      [
        { symbol: 'POWL', assetType: 'stock' },
        { symbol: 'POWL', assetType: 'stock' },
        { symbol: 'NVDA', assetType: 'stock' },
        { symbol: 'MATIC', assetType: 'crypto' },
      ],
      fake,
    )
    expect(urls).toEqual([intradayUrl('POWL'), intradayUrl('NVDA'), intradayUrl('POL-CAD')])
    expect([...got.keys()]).toEqual(['stock:POWL', 'crypto:MATIC'])
    expect(yahooSymbolOf('RY.TO', 'stock')).toBe('RY.TO')
  })
})
