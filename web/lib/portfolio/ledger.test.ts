import { describe, expect, it } from 'vitest'
import { buildLedger, tradeCad } from './ledger'
import { FxRates } from './lookup'
import type { Trade } from './types'

const FX = new FxRates([
  { day: '2026-09-01', usdCad: 1.35 },
  { day: '2026-10-01', usdCad: 1.4 },
])

const buy = (over: Partial<Trade>): Trade => ({
  side: 'buy',
  account: 'tfsa',
  symbol: 'RY.TO',
  assetType: 'stock',
  qty: 10,
  price: 100,
  currency: 'CAD',
  fxRateCad: null,
  day: '2026-09-02',
  ...over,
})
const sell = (over: Partial<Trade>): Trade => buy({ side: 'sell', ...over })

describe('tradeCad', () => {
  it('converts a USD trade at its own rate', () => {
    expect(tradeCad(buy({ currency: 'USD', fxRateCad: 1.38, price: 50 }), FX)).toBeCloseTo(690)
  })

  it('uses the Bank of Canada rate of the day when a USD trade has none', () => {
    expect(tradeCad(buy({ currency: 'USD', price: 50, day: '2026-10-05' }), FX)).toBeCloseTo(700)
  })

  it('is null for a USD trade older than every known rate', () => {
    expect(tradeCad(buy({ currency: 'USD', price: 50, day: '2026-08-01' }), FX)).toBeNull()
  })
})

describe('buildLedger', () => {
  it('averages the cost of buys and keeps the first buy day', () => {
    const { positions } = buildLedger(
      [buy({ qty: 10, price: 100 }), buy({ qty: 10, price: 120, day: '2026-09-20' })],
      FX,
    )
    expect(positions).toEqual([
      { account: 'tfsa', symbol: 'RY.TO', assetType: 'stock', qty: 20, costCad: 2200, openedOn: '2026-09-02' },
    ])
  })

  it('realizes a sell at average cost and keeps the rest at the same average', () => {
    const { positions, sales } = buildLedger(
      [buy({ qty: 10, price: 100 }), buy({ qty: 10, price: 120 }), sell({ qty: 5, price: 130, day: '2026-09-12' })],
      FX,
    )
    expect(sales).toEqual([
      {
        account: 'tfsa', symbol: 'RY.TO', assetType: 'stock', day: '2026-09-12',
        qty: 5, proceedsCad: 650, costCad: 550, gainCad: 100, heldDays: 10,
      },
    ])
    expect(positions[0].qty).toBe(15)
    expect(positions[0].costCad).toBeCloseTo(1650)
  })

  it('keeps each account apart', () => {
    const { positions } = buildLedger([buy({}), buy({ account: 'rrsp', price: 90 })], FX)
    expect(positions.map((p) => [p.account, p.costCad])).toEqual([
      ['tfsa', 1000],
      ['rrsp', 900],
    ])
  })

  it('closes a position sold in full, and a later buy opens a new one', () => {
    const { positions, sales } = buildLedger(
      [buy({}), sell({ day: '2026-09-10', price: 90 }), buy({ day: '2026-09-25', price: 80 })],
      FX,
    )
    expect(sales[0].gainCad).toBe(-100)
    expect(positions).toHaveLength(1)
    expect(positions[0]).toMatchObject({ qty: 10, costCad: 800, openedOn: '2026-09-25' })
  })

  it("counts a day's buys before its sells", () => {
    const { sales, problems } = buildLedger([sell({ day: '2026-09-02' }), buy({ day: '2026-09-02' })], FX)
    expect(problems).toEqual([])
    expect(sales).toHaveLength(1)
  })

  it('applies a sell of more than is held to what is held, and says so', () => {
    const { positions, sales, problems } = buildLedger([buy({ qty: 10 }), sell({ qty: 12, price: 110 })], FX)
    expect(positions).toEqual([])
    expect(sales[0]).toMatchObject({ qty: 10, proceedsCad: 1100, gainCad: 100 })
    expect(problems).toEqual(['RY.TO on 2026-09-02: sold 12 but held 10; counted as 10.'])
  })

  it('leaves out a sell with nothing held, and a USD trade with no known rate', () => {
    const { positions, problems } = buildLedger(
      [sell({}), buy({ symbol: 'AAPL', currency: 'USD', day: '2026-08-01' })],
      FX,
    )
    expect(positions).toEqual([])
    expect(problems).toEqual([
      'AAPL on 2026-08-01: no USD/CAD rate for that day, so it\'s left out.',
      "RY.TO on 2026-09-02: a sell with nothing held, so it's left out.",
    ])
  })

  it('closes a coin position whose leftover is a rounding error', () => {
    const coin = { symbol: 'BTC', assetType: 'crypto' as const, account: 'crypto' as const }
    const { positions } = buildLedger(
      [buy({ ...coin, qty: 0.1 }), buy({ ...coin, qty: 0.2 }), sell({ ...coin, qty: 0.30000000000000004 })],
      FX,
    )
    expect(positions).toEqual([])
  })
})
