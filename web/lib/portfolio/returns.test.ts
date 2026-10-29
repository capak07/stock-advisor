import { describe, expect, it } from 'vitest'
import { FxRates, PriceBook } from './lookup'
import { growth, periodReturns } from './returns'
import type { Close, Trade } from './types'

const FX = new FxRates([
  { day: '2026-10-01', usdCad: 1.4 },
  { day: '2026-10-05', usdCad: 1.5 },
])
const series = (currency: 'USD' | 'CAD', points: [string, number][]): Close[] =>
  points.map(([day, close]) => ({ day, close, currency }))
const DAYS = ['2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06']
const flat = (value: number) => DAYS.map((day): [string, number] => [day, value])

const book = (extra: [string, Close[]][] = []) =>
  new PriceBook(
    new Map([
      ['stock:XIU.TO', series('CAD', [['2026-10-01', 40], ['2026-10-02', 41], ['2026-10-05', 42], ['2026-10-06', 44]])],
      ['stock:SPY', series('USD', flat(500))],
      ...extra,
    ]),
  )
const trade = (over: Partial<Trade>): Trade => ({
  side: 'buy',
  account: 'tfsa',
  symbol: 'RY.TO',
  assetType: 'stock',
  qty: 10,
  price: 100,
  currency: 'CAD',
  fxRateCad: null,
  day: '2026-10-01',
  ...over,
})

describe('growth', () => {
  it('is null without trades or without any closes', () => {
    expect(growth([], book(), FX)).toBeNull()
    expect(growth([trade({})], new PriceBook(new Map()), FX)).toBeNull()
  })

  it("measures from the buy price, on the benchmarks' trading days", () => {
    const prices = book([['stock:RY.TO', series('CAD', [['2026-10-01', 101], ['2026-10-02', 103], ['2026-10-06', 110]])]])
    const g = growth([trade({})], prices, FX)!
    expect(g.days).toEqual(DAYS)
    // 1000 paid; closes 1010, 1030, 1030 (carried over Oct 5), 1100.
    expect(g.portfolio.map((v) => +v.toFixed(4))).toEqual([1.01, 1.03, 1.03, 1.1])
    expect(g.xiu).toEqual([1, 41 / 40, 42 / 40, 44 / 40])
  })

  it('converts SPY to CAD at each day\'s rate', () => {
    const g = growth([trade({})], book([['stock:RY.TO', series('CAD', flat(100))]]), FX)!
    // SPY is flat in USD, but USD/CAD went from 1.40 to 1.50 on Oct 5.
    expect(g.spy!.map((v) => +v.toFixed(4))).toEqual([1, 1, 1.0714, 1.0714])
  })

  it("doesn't count money put in or taken out as a return", () => {
    const prices = book([['stock:RY.TO', series('CAD', [['2026-10-01', 100], ['2026-10-02', 110], ['2026-10-05', 110], ['2026-10-06', 121]])]])
    const g = growth(
      [
        trade({}),
        trade({ day: '2026-10-02', qty: 10, price: 110 }), // doubles the position at the close price
        trade({ side: 'sell', day: '2026-10-05', qty: 15, price: 110 }),
      ],
      prices,
      FX,
    )!
    // Oct 2: the 1,100 put in counts from the start of the day, so 2,200 / (1,000 + 1,100).
    // Oct 5: a sell at the close changes nothing. Oct 6: the 5 shares left gain 10%.
    expect(g.portfolio.map((v) => +v.toFixed(4))).toEqual([1, 1.0476, 1.0476, 1.1524])
  })

  it("doesn't let a big buy into a small position inflate the day's return", () => {
    const prices = book([['stock:RY.TO', series('CAD', [['2026-10-01', 100], ['2026-10-02', 101]])]])
    const g = growth([trade({ qty: 1 }), trade({ day: '2026-10-02', qty: 1000, price: 100 })], prices, FX)!
    // 100 held, then 100,000 more bought: the day's 1% move is ~1%, not 1,000%.
    expect(g.portfolio[1]).toBeCloseTo(1.01, 4)
  })

  it('counts a weekend coin buy on the next trading day and values it at cost until it has a close', () => {
    const prices = book([['crypto:BTC', series('USD', [['2026-10-05', 70000], ['2026-10-06', 77000]])]])
    const g = growth(
      [trade({ account: 'crypto', symbol: 'BTC', assetType: 'crypto', qty: 0.01, price: 98000, day: '2026-10-03' })],
      prices,
      FX,
    )!
    expect(g.days).toEqual(['2026-10-05', '2026-10-06'])
    // 980 paid; 0.01 × 70,000 × 1.5 = 1050, then 1155.
    expect(g.portfolio.map((v) => +v.toFixed(4))).toEqual([1.0714, 1.1786])
  })

  it("values an asset at its first close before then, so a gain since the buy lands on the buy day", () => {
    // Bought on the first day for 1,000; the first stored close is two trading days later.
    const coin = series('CAD', [['2026-10-05', 120], ['2026-10-06', 132]])
    const g = growth([trade({ symbol: 'BTC', assetType: 'crypto', account: 'crypto' })], book([['crypto:BTC', coin]]), FX)!
    expect(g.portfolio.map((v) => +v.toFixed(4))).toEqual([1.2, 1.2, 1.2, 1.32])
  })

  it('keeps the value at cost for an asset that never had a close', () => {
    const g = growth([trade({ symbol: 'NEWCO' })], book(), FX)!
    expect(g.portfolio).toEqual([1, 1, 1, 1])
  })

  it("leaves out a benchmark without a close on the first day", () => {
    const prices = new PriceBook(new Map([['stock:RY.TO', series('CAD', flat(100))]]))
    const g = growth([trade({})], prices, FX)!
    expect(g.xiu).toBeNull()
    expect(g.spy).toBeNull()
    expect(g.days).toEqual(DAYS)
  })
})

describe('periodReturns', () => {
  const g = {
    days: Array.from({ length: 30 }, (_, i) => `d${String(i).padStart(2, '0')}`),
    portfolio: Array.from({ length: 30 }, (_, i) => 1.1 + i * 0.01),
    xiu: Array.from({ length: 30 }, (_, i) => 1 + i * 0.02),
    spy: null,
  }

  it('measures "all" from cost for the portfolio and from the first close for benchmarks', () => {
    const all = periodReturns(g, 'all')
    expect(all.days).toHaveLength(30)
    expect(all.portfolio[0]).toBeCloseTo(10)
    expect(all.xiu![0]).toBe(0)
    expect(all.xiu!.at(-1)).toBeCloseTo(58)
    expect(all.spy).toBeNull()
  })

  it('starts every line at 0 over the last 21 trading days', () => {
    const month = periodReturns(g, '1m')
    expect(month.days).toHaveLength(22)
    expect(month.days[0]).toBe('d08')
    expect(month.portfolio[0]).toBe(0)
    expect(month.portfolio.at(-1)).toBeCloseTo(((1.39 / 1.18) - 1) * 100)
  })

  it('uses the whole history when it is shorter than the period', () => {
    expect(periodReturns(g, '12m').days).toHaveLength(30)
  })

  it('covers the last session and the last five trading days', () => {
    const day = periodReturns(g, '1d')
    const week = periodReturns(g, '1w')
    expect(day.days).toEqual(['d28', 'd29'])
    expect(day.portfolio[0]).toBe(0)
    expect(week.days).toEqual(['d24', 'd25', 'd26', 'd27', 'd28', 'd29'])
    expect(week.portfolio[0]).toBe(0)
    expect(week.xiu![0]).toBe(0)
  })
})
