import { describe, expect, it } from 'vitest'
import { allocate, roundTripCost, type Candidate, type ForecastRow, type InvestInput } from './allocate'

const row = (horizonDays: number, q50: number, pBeat: number, width = 0.1): ForecastRow => ({
  horizonDays,
  q10: q50 - width / 2,
  q50,
  q90: q50 + width / 2,
  pBeat,
  benchmark: 'SPY',
})

const stock = (symbol: string, over: Partial<Candidate> = {}): Candidate => ({
  symbol,
  name: `${symbol} Inc.`,
  assetType: 'stock',
  market: symbol.endsWith('.TO') ? 'TSX' : 'US',
  sector: `Sector ${symbol}`,
  rows: [row(21, 0.05, 0.6)],
  vol60: 0.3,
  dollarVolume20: 2e7,
  jump5d: 0,
  priceCad: 10,
  price: 10,
  currency: symbol.endsWith('.TO') ? 'CAD' : 'USD',
  atrPct: 0.02,
  ...over,
})

const coin = (symbol: string, over: Partial<Candidate> = {}): Candidate =>
  stock(symbol, { name: symbol, assetType: 'crypto', market: null, sector: null, currency: 'CAD', rows: [row(14, 0.08, 0.62)], ...over })

const input = (candidates: Candidate[], over: Partial<InvestInput> = {}): InvestInput => ({
  amount: 1000,
  usdFxFeePct: 1.5,
  cryptoFeePct: 2,
  candidates,
  held: new Set(),
  topN: null,
  ...over,
})

describe('roundTripCost', () => {
  it('is the spread, plus a fee both ways for a US stock or a coin', () => {
    expect(roundTripCost('TSX', 2e7, 1.5)).toBeCloseTo(0.001)
    expect(roundTripCost('TSX', 5e6, 1.5)).toBeCloseTo(0.003)
    expect(roundTripCost('US', 2e7, 1.5)).toBeCloseTo(0.031)
    expect(roundTripCost('US', null, 1.5)).toBeCloseTo(0.033) // unknown volume counts as thin
    expect(roundTripCost('crypto', 2e7, 2)).toBeCloseTo(0.041)
    expect(roundTripCost('crypto', null, 2)).toBeCloseTo(0.043)
  })
})

describe('allocate: choosing the stocks', () => {
  it('takes the five best qualifying stocks by expected return per unit of range', () => {
    const candidates = ['A', 'B', 'C', 'D', 'E', 'F'].map((s, i) => stock(`${s}.TO`, { rows: [row(21, 0.02 + i / 100, 0.6)] }))
    const out = allocate(input(candidates))
    expect(out.stocks.map((l) => l.symbol)).toEqual(['F.TO', 'E.TO', 'D.TO', 'C.TO', 'B.TO'])
    expect(out.stocks.every((l) => l.qualifies)).toBe(true)
    expect(out.notValidated).toBe(false)
  })

  it("uses the stock's best qualifying horizon, the shorter on a tie", () => {
    const out = allocate(
      input([stock('A.TO', { rows: [row(63, 0.04, 0.62, 0.05), row(10, 0.04, 0.6, 0.05), row(5, 0.09, 0.4), row(21, 0.03, 0.6)] })]),
    )
    expect(out.stocks[0]).toMatchObject({ horizonDays: 10, q50: 0.04, pBeat: 0.6, qualifies: true })
  })

  it('needs P at least 0.58 and an expected return above the round-trip cost to qualify', () => {
    const out = allocate(
      input([
        stock('LOWP.TO', { rows: [row(21, 0.05, 0.57)] }),
        stock('CHEAP', { rows: [row(21, 0.03, 0.7)] }), // under the 3.1% US round trip
        stock('OK.TO', { rows: [row(21, 0.01, 0.58)] }),
      ]),
    )
    expect(out.stocks.map((l) => [l.symbol, l.qualifies])).toEqual([
      ['OK.TO', true],
      ['LOWP.TO', false], // fills: even odds or better, and clears its costs
    ]) // CHEAP doesn't even fill: its 3% median doesn't cover the 3.1% US round trip
    expect(out.notValidated).toBe(true)
  })

  it('fills from the best positive forecasts when fewer than five qualify, never a stock expected to lag', () => {
    const out = allocate(
      input([
        stock('LAG.TO', { rows: [row(5, -0.01, 0.45), row(21, -0.02, 0.4)] }),
        stock('WEAK.TO', { rows: [row(5, -0.01, 0.45), row(21, 0.01, 0.5)] }),
      ]),
    )
    expect(out.stocks.map((l) => [l.symbol, l.horizonDays, l.qualifies])).toEqual([['WEAK.TO', 21, false]])
    expect(out.notValidated).toBe(true)
  })

  it('never fills with a stock more likely to lag, or one whose median does not cover its costs', () => {
    const out = allocate(
      input([
        stock('SOIL.TO', { rows: [row(126, 0.23, 0.47, 0.9)] }), // a high median, but more likely to lag
        stock('MSFT', { rows: [row(21, 0.02, 0.52)] }), // beats SPY more often than not, but not by the 3.2% fees
        stock('CNQ.TO', { rows: [row(5, 0.019, 0.53, 0.055)] }),
      ]),
    )
    expect(out.stocks.map((l) => l.symbol)).toEqual(['CNQ.TO'])
  })

  it('leaves out held stocks, unconfirmed jumps and flat ranges', () => {
    const out = allocate(
      input(
        [
          stock('HELD.TO'),
          stock('JUMP.TO', { jump5d: 1 }),
          stock('UNKNOWN.TO', { jump5d: null }),
          stock('FLAT.TO', { rows: [row(21, 0.05, 0.7, 0)] }),
          stock('OK.TO'),
        ],
        { held: new Set(['HELD.TO']) },
      ),
    )
    expect(out.stocks.map((l) => l.symbol)).toEqual(['OK.TO'])
  })

  it('takes at most two stocks from one sector; an unlabelled stock counts alone', () => {
    const banks = ['A', 'B', 'C'].map((s, i) => stock(`${s}.TO`, { sector: 'Banks', rows: [row(21, 0.09 - i / 100, 0.6)] }))
    const loners = ['X', 'Y'].map((s) => stock(`${s}.TO`, { sector: null, rows: [row(21, 0.02, 0.6)] }))
    const out = allocate(input([...banks, ...loners]))
    expect(out.stocks.map((l) => l.symbol)).toEqual(['A.TO', 'B.TO', 'X.TO', 'Y.TO'])
  })
})

describe('allocate: rank mode', () => {
  const four = ['A', 'B', 'C', 'D'].map((s, i) => stock(`${s}.TO`, { rows: [row(21, 0.05, 0.49 - i / 100)] }))

  it('with topN, qualifies the top N by P per horizon that clear their costs', () => {
    const out = allocate(input(four, { topN: 2 }))
    expect(out.stocks.map((l) => [l.symbol, l.qualifies])).toEqual([
      ['A.TO', true],
      ['B.TO', true],
    ])
  })

  it('with topN, a top stock that does not clear its costs is not taken', () => {
    const out = allocate(
      input(
        [
          stock('A.TO', { rows: [row(21, 0, 0.9)] }),
          stock('B.TO', { rows: [row(21, 0.05, 0.48)] }),
          stock('C.TO', { rows: [row(21, 0.05, 0.47)] }),
        ],
        { topN: 2 },
      ),
    )
    expect(out.stocks.map((l) => l.symbol)).not.toContain('A.TO')
    expect(out.stocks.map((l) => [l.symbol, l.qualifies])).toEqual([['B.TO', true]])
  })

  it('ties rank by symbol', () => {
    const out = allocate(
      input(
        [
          stock('M.TO', { rows: [row(21, 0.05, 0.49)] }),
          stock('A.TO', { rows: [row(21, 0.05, 0.49)] }),
          stock('Z.TO', { rows: [row(21, 0.05, 0.4)] }),
        ],
        { topN: 1 },
      ),
    )
    expect(out.stocks.map((l) => [l.symbol, l.qualifies])).toEqual([['A.TO', true]])
  })

  it('without topN, behaves as today', () => {
    const out = allocate(input([...four, stock('OK.TO', { rows: [row(21, 0.05, 0.6)] })], { topN: null }))
    expect(out.stocks.map((l) => [l.symbol, l.qualifies])).toEqual([['OK.TO', true]])
  })
})

describe('allocate: how long to hold', () => {
  it("ranks only on the chosen hold's forecast, so its hold time is what was asked", () => {
    const candidates = [
      stock('SHORT.TO', { rows: [row(5, 0.09, 0.7), row(63, 0.02, 0.6)] }), // great over 5 days, modest over 3 months
      stock('LONG.TO', { rows: [row(5, 0.01, 0.6), row(63, 0.07, 0.62)] }),
      stock('NO63.TO', { rows: [row(5, 0.08, 0.7)] }), // no 3-month forecast at all
    ]
    const out = allocate(input(candidates, { horizons: [63] }))
    expect(out.stocks.map((l) => [l.symbol, l.horizonDays])).toEqual([
      ['LONG.TO', 63],
      ['SHORT.TO', 63],
    ])
    expect(allocate(input(candidates)).stocks[0].symbol).toBe('SHORT.TO') // any hold: its 5-day forecast wins
  })

  it('a month takes either of the 20- and 21-day forecasts', () => {
    const out = allocate(input([stock('A.TO', { rows: [row(5, 0.09, 0.7), row(21, 0.03, 0.6)] })], { horizons: [20, 21] }))
    expect(out.stocks[0].horizonDays).toBe(21)
  })
})

describe('allocate: splitting the money', () => {
  it('gives steadier stocks more, in proportion to 1 / volatility, and adds up exactly', () => {
    const out = allocate(
      input([
        stock('A.TO', { vol60: 0.2, rows: [row(21, 0.06, 0.6)] }),
        stock('B.TO', { vol60: 0.4, rows: [row(21, 0.05, 0.6)] }),
        stock('C.TO', { vol60: 0.4, rows: [row(21, 0.04, 0.6)] }),
      ]),
    )
    expect(out.stocks.map((l) => l.amount)).toEqual([400, 300, 300]) // 0.5 / 0.25 / 0.25, A capped at 40%
    expect(out.stocks.reduce((s, l) => s + l.amount, 0)).toBe(1000)
  })

  it('caps one stock at 40% of the stock money and spreads the excess', () => {
    const out = allocate(
      input(['A', 'B', 'C', 'D'].map((s, i) => stock(`${s}.TO`, { vol60: i === 0 ? 0.05 : 0.5, rows: [row(21, 0.06 - i / 100, 0.6)] }))),
    )
    expect(out.stocks.map((l) => l.amount)).toEqual([400, 200, 200, 200])
  })

  it('splits evenly when there are too few stocks for the cap to hold', () => {
    const out = allocate(input([stock('A.TO', { vol60: 0.1 }), stock('B.TO', { vol60: 0.9, rows: [row(21, 0.04, 0.6)] })]))
    expect(out.evenSplit).toBe(true)
    expect(out.stocks.map((l) => l.amount)).toEqual([500, 500])
  })

  it('puts everything in the top-ranked stock when one is asked for', () => {
    const candidates = ['A', 'B', 'C'].map((s, i) => stock(`${s}.TO`, { rows: [row(21, 0.06 - i / 100, 0.6)] }))
    const out = allocate(input(candidates, { amount: 500, stocks: 1 }))
    expect(out.stocks.map((l) => [l.symbol, l.amount])).toEqual([['A.TO', 500]])
    expect(out.evenSplit).toBe(false) // one stock is all of it, not an even split
  })

  it('takes as many from the top of the ranking as asked, still at most two per sector', () => {
    const banks = ['A', 'B', 'C'].map((s, i) => stock(`${s}.TO`, { sector: 'Banks', rows: [row(21, 0.09 - i / 100, 0.6)] }))
    const loners = ['X', 'Y', 'Z'].map((s, i) => stock(`${s}.TO`, { rows: [row(21, 0.03 - i / 100, 0.6)] }))
    const out = allocate(input([...banks, ...loners], { stocks: 3 }))
    expect(out.stocks.map((l) => l.symbol)).toEqual(['A.TO', 'B.TO', 'X.TO'])
  })

  it('treats a missing volatility as the median of the stocks shown', () => {
    const out = allocate(
      input([
        stock('A.TO', { vol60: 0.2, rows: [row(21, 0.06, 0.6)] }),
        stock('B.TO', { vol60: null, rows: [row(21, 0.05, 0.6)] }),
        stock('C.TO', { vol60: 0.4, rows: [row(21, 0.04, 0.6)] }),
      ]),
    )
    // the median of 0.2 and 0.4 is 0.3: weights 5, 3.33, 2.5 over 10.83
    expect(out.stocks.map((l) => l.amount)).toEqual([400, 343, 257])
  })

  it('gives the dollars left after rounding down to the largest fractions, so the total matches', () => {
    const out = allocate(input([stock('A.TO', { vol60: 0.3 }), stock('B.TO', { vol60: 0.3 }), stock('C.TO', { vol60: 0.3 })]))
    const total = out.stocks.reduce((s, l) => s + l.amount, 0) + out.uninvested
    expect(total).toBe(1000)
    expect(out.stocks.map((l) => l.amount)).toEqual([334, 333, 333])
  })

  it('never gives a line less than nothing when the amount is small', () => {
    const five = ['A.TO', 'B.TO', 'C.TO', 'D.TO', 'E.TO'].map((s) => stock(s, { vol60: 0.3 }))
    const out = allocate(input(five, { amount: 3, stocks: 5 }))
    expect(out.stocks.map((l) => l.amount)).toEqual([1, 1, 1, 0, 0])
    expect(out.uninvested).toBe(0)
  })

  it('keeps every line in whole dollars, leaving the cents uninvested', () => {
    const out = allocate(input([stock('A.TO', { vol60: 0.3 }), stock('B.TO', { vol60: 0.3 }), stock('C.TO', { vol60: 0.3 })], { amount: 1000.5 }))
    expect(out.stocks.map((l) => l.amount)).toEqual([334, 333, 333])
    expect(out.uninvested).toBeCloseTo(0.5)
  })

  it('leaves the money uninvested when nothing is expected to beat its benchmark', () => {
    const out = allocate(input([stock('LAG.TO', { rows: [row(21, -0.02, 0.4)] })]))
    expect(out.stocks).toEqual([])
    expect(out.uninvested).toBe(1000)
  })

  it('ranks coins the same way, and a coin that is expected to lag is left out', () => {
    const out = allocate(
      input([
        coin('SOL', { rows: [row(14, 0.06, 0.62, 0.2)] }), // ratio 0.3, above the 4.1% round trip
        coin('ETH', { rows: [row(14, 0.08, 0.7)] }), // ratio 0.8
        coin('DOGE', { rows: [row(14, -0.02, 0.4)] }),
        coin('HELD', { rows: [row(14, 0.2, 0.9)] }),
      ], { held: new Set(['HELD']) }),
    )
    expect(out.stocks.map((l) => [l.symbol, l.qualifies, l.horizonDays])).toEqual([
      ['ETH', true, 14],
      ['SOL', true, 14],
    ])
    expect(out.stocks[0].cost).toBeCloseTo(0.041)
    expect(out.stocks.reduce((s, l) => s + l.amount, 0)).toBe(1000)
    expect(out.evenSplit).toBe(true)
  })
})

describe('allocate: the details', () => {
  it('gives approximate shares from the CAD price, and none without a price', () => {
    const out = allocate(input([stock('A.TO', { priceCad: 40 }), stock('B.TO', { priceCad: null }), stock('C.TO')]))
    const a = out.stocks.find((l) => l.symbol === 'A.TO')!
    expect(a.shares).toBeCloseTo(a.amount / 40, 9)
    expect(out.stocks.find((l) => l.symbol === 'B.TO')!.shares).toBeNull()
  })

  it("describes volatility by its percentile among the run's forecast stocks", () => {
    const vols = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    const candidates = vols.map((v, i) => stock(`S${i}.TO`, { vol60: v, sector: null, rows: [row(21, 0.02 + i / 1000, 0.6)] }))
    const out = allocate(input(candidates, { held: new Set(['S0.TO', 'S1.TO', 'S2.TO', 'S3.TO', 'S4.TO']) }))
    expect(Object.fromEntries(out.stocks.map((l) => [l.symbol, l.volatility]))).toEqual({
      'S5.TO': 'medium', // 0.6 is at the 55th percentile of all ten
      'S6.TO': 'high',
      'S7.TO': 'high',
      'S8.TO': 'high',
      'S9.TO': 'very high',
    })
  })

  it('carries the round-trip cost of each stock', () => {
    const out = allocate(input([stock('A', { rows: [row(21, 0.05, 0.6)] })]))
    expect(out.stocks[0].cost).toBeCloseTo(0.031)
  })
})

describe('allocate: who may take a top-N place (matches the pipeline)', () => {
  const four = ['A', 'B', 'C', 'D'].map((s, i) => stock(`${s}.TO`, { rows: [row(21, 0.05, 0.49 - i / 100)] }))
  const qualified = (cands: Candidate[], topN: number) =>
    allocate(input(cands, { topN })).stocks.filter((l) => l.qualifies).map((l) => l.symbol)

  it('a stock with an unconfirmed jump never takes a place', () => {
    const jumped = stock('J.TO', { rows: [row(21, 0.05, 0.6)], jump5d: 1 })
    expect(qualified([jumped, ...four], 2)).toEqual(['A.TO', 'B.TO'])
  })

  it('a NaN P never takes a place', () => {
    const blank = stock('N.TO', { rows: [row(21, 0.05, Number.NaN)] })
    expect(qualified([blank, ...four], 2)).toEqual(['A.TO', 'B.TO'])
  })

  it('ties break by code point, as Python compares symbols', () => {
    const tied = [stock('a.TO', { rows: [row(21, 0.05, 0.49)] }), stock('B.TO', { rows: [row(21, 0.05, 0.49)] })]
    expect(qualified(tied, 1)).toEqual(['B.TO']) // 'B' (66) sorts before 'a' (97)
  })
})
