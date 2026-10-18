import { describe, expect, it } from 'vitest'
import { FxRates } from './lookup'
import { tradeList } from './trade-list'
import type { RecordedTrade } from './types'

const FX = new FxRates([{ day: '2026-09-01', usdCad: 1.4 }])
const trade = (over: Partial<RecordedTrade>): RecordedTrade => ({
  id: 1,
  side: 'buy',
  account: 'tfsa',
  symbol: 'RY.TO',
  assetType: 'stock',
  qty: 10,
  price: 170,
  currency: 'CAD',
  fxRateCad: null,
  day: '2026-09-02',
  ...over,
})

describe('tradeList', () => {
  it("lists trades newest first, a day's sells before its buys", () => {
    const lines = tradeList(
      [
        trade({ id: 1, day: '2026-09-02' }),
        trade({ id: 2, day: '2026-09-20' }),
        trade({ id: 1, side: 'sell', qty: 5, day: '2026-09-20' }),
        trade({ id: 3, day: '2026-09-20', symbol: 'TD.TO' }),
      ],
      FX,
    )
    expect(lines.map((l) => l.key)).toEqual(['sell:1', 'buy:3', 'buy:2', 'buy:1'])
  })

  it('gives each trade its amount in CAD', () => {
    const [usd, cad] = tradeList(
      [
        trade({ id: 1 }),
        trade({ id: 2, symbol: 'AAPL', currency: 'USD', fxRateCad: 1.37, price: 200, day: '2026-09-03' }),
      ],
      FX,
    )
    expect(usd).toMatchObject({ symbol: 'AAPL', amountCad: 2740 })
    expect(cad).toMatchObject({ symbol: 'RY.TO', amountCad: 1700 })
  })

  it('marks a buy whose deletion would leave a later sell with too little held', () => {
    const lines = tradeList(
      [
        trade({ id: 1, qty: 10 }),
        trade({ id: 2, qty: 5, day: '2026-09-10' }),
        trade({ id: 1, side: 'sell', qty: 12, day: '2026-09-20' }),
        trade({ id: 3, symbol: 'TD.TO' }),
      ],
      FX,
    )
    const strands = Object.fromEntries(lines.map((l) => [l.key, l.strandsSells]))
    // Without buy 1 only 5 are held when 12 are sold; without buy 2, 10. TD.TO stands alone.
    expect(strands).toEqual({ 'sell:1': false, 'buy:2': true, 'buy:1': true, 'buy:3': false })
  })

  it('is empty without trades', () => {
    expect(tradeList([], FX)).toEqual([])
  })
})
