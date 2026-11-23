import { describe, expect, it } from 'vitest'
import type { Candidate, ForecastRow } from './allocate'
import { WATCH_PER_HOLD, watchList } from './watch'

const row = (horizonDays: number, pBeat: number, q50 = 0.01, q10 = -0.05, q90 = 0.07): ForecastRow => ({
  horizonDays,
  pBeat,
  q10,
  q50,
  q90,
  benchmark: 'SPY',
})
const stock = (symbol: string, rows: ForecastRow[], over: Partial<Candidate> = {}): Candidate => ({
  symbol,
  name: `${symbol} Inc.`,
  assetType: 'stock',
  market: 'US',
  sector: null,
  rows,
  vol60: 0.3,
  dollarVolume20: 50_000_000,
  jump5d: 0,
  priceCad: 100,
  price: 70,
  currency: 'USD',
  atrPct: 0.02,
  ...over,
})
const NONE = new Set<string>()

describe('watchList', () => {
  it('puts each stock once, under the hold it is rated best at, shortest hold first', () => {
    const groups = watchList([stock('AAA', [row(5, 0.56), row(20, 0.51)]), stock('BBB', [row(5, 0.49), row(20, 0.53)])], NONE, 0)
    expect(groups.map((g) => [g.label, g.lines.map((l) => [l.symbol, l.horizonDays])])).toEqual([
      ['~1 week', [['AAA', 5]]],
      ['~1 month', [['BBB', 20]]],
    ])
  })

  it('ranks a group by chance, then by the middle forecast against the width of the range', () => {
    const groups = watchList(
      [
        stock('LOW', [row(5, 0.54)]),
        stock('WIDE', [row(5, 0.558, 0.01, -0.1, 0.1)]), // 0.01 / 0.2
        stock('NARROW', [row(5, 0.558, 0.01, -0.02, 0.03)]), // 0.01 / 0.05
      ],
      NONE,
      0,
    )
    expect(groups[0].lines.map((l) => l.symbol)).toEqual(['NARROW', 'WIDE', 'LOW'])
  })

  it(`keeps the best ${WATCH_PER_HOLD} of each hold`, () => {
    const many = Array.from({ length: WATCH_PER_HOLD + 3 }, (_, i) => stock(`S${i}`, [row(5, 0.5 + i / 100)]))
    const [group] = watchList(many, NONE, 0)
    expect(group.lines).toHaveLength(WATCH_PER_HOLD)
    expect(group.lines[0].symbol).toBe(`S${WATCH_PER_HOLD + 2}`)
  })

  it('names the holds the model forecasts and leaves out a hold with no stock', () => {
    const groups = watchList(
      [stock('A', [row(5, 0.6)]), stock('B', [row(10, 0.6)]), stock('C', [row(21, 0.6)]), stock('D', [row(126, 0.6)])],
      NONE,
      0,
    )
    expect(groups.map((g) => g.label)).toEqual(['~1 week', '~2 weeks', '~1 month', '~6 months'])
  })

  it('leaves out stocks already held and stocks with an earnings-size jump, as the picks do', () => {
    const groups = watchList(
      [stock('HELD', [row(5, 0.6)]), stock('JUMP', [row(5, 0.6)], { jump5d: 1 }), stock('NOJUMP', [row(5, 0.6)], { jump5d: null }), stock('OK', [row(5, 0.5)])],
      new Set(['HELD']),
      0,
    )
    expect(groups.flatMap((g) => g.lines.map((l) => l.symbol))).toEqual(['OK'])
  })

  it('says whether the middle forecast covers the cost of a round trip, and whether it passes the bar', () => {
    const [group] = watchList(
      [
        stock('PASSES', [row(5, 0.59, 0.01)]), // 1% clears the 0.1% spread, and 59% is over the bar
        stock('COVERS', [row(5, 0.55, 0.01)]), // clears its costs, under the bar
        stock('BELOW', [row(5, 0.55, 0.002)], { dollarVolume20: 1_000_000 }), // 0.2% under a 0.3% spread
      ],
      NONE,
      0,
    )
    expect(group.lines.map((l) => [l.symbol, l.coversCosts, l.passes])).toEqual([
      ['PASSES', true, true],
      ['COVERS', true, false],
      ['BELOW', false, false],
    ])
    // a 0.5% currency fee each way: 0.1% + 1% = 1.1%, so 1% no longer covers it
    const [fee] = watchList([stock('PASSES', [row(5, 0.59, 0.01)])], NONE, 0.5)
    expect(fee.lines[0]).toMatchObject({ coversCosts: false, passes: false })
  })

  it('is empty without stocks', () => {
    expect(watchList([], NONE, 0)).toEqual([])
  })
})
