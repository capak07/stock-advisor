import { describe, expect, it } from 'vitest'
import { addDays } from '../dates'
import { FxRates } from './lookup'
import { replaceTrade, tradeList } from './trade-list'
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
  notes: null,
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

  it('lists 5,000 trades in well under a second', () => {
    // 40 symbols in one account, each three buys of 10 then a sell of 25: the first three buys of
    // each symbol strand its first sell, later ones don't.
    const trades = Array.from({ length: 5000 }, (_, i) => {
      const n = Math.floor(i / 40)
      return trade({
        id: i + 1,
        side: n % 4 === 3 ? 'sell' : 'buy',
        symbol: `S${i % 40}`,
        qty: n % 4 === 3 ? 25 : 10,
        day: addDays('2020-01-01', n),
      })
    })
    const started = performance.now()
    const lines = tradeList(trades, FX)
    const took = performance.now() - started
    expect(lines).toHaveLength(5000)
    expect(lines.filter((l) => l.strandsSells)).toHaveLength(120)
    expect(took).toBeLessThan(1000)
  })
})

describe('replaceTrade', () => {
  it('accepts a price change that still covers later sells', () => {
    const trades = [trade({ id: 1, qty: 10 }), trade({ id: 1, side: 'sell', qty: 4, day: '2026-09-20' })]
    expect(replaceTrade(trades, trade({ id: 1, qty: 10, price: 180 }), FX)).toEqual({ ok: true })
  })

  it('refuses a buy that would leave a later sell with more than was held', () => {
    const trades = [trade({ id: 1, qty: 10 }), trade({ id: 1, side: 'sell', qty: 8, day: '2026-09-20' })]
    const result = replaceTrade(trades, trade({ id: 1, qty: 5 }), FX)
    expect(result).toEqual({ error: 'RY.TO on 2026-09-20: sold 8 but held 5; counted as 5.' })
  })

  it('refuses a sell of more than is held', () => {
    const trades = [trade({ id: 1, qty: 10 }), trade({ id: 2, side: 'sell', qty: 4, day: '2026-09-20' })]
    const result = replaceTrade(trades, trade({ id: 2, side: 'sell', qty: 12, day: '2026-09-20' }), FX)
    expect(result).toEqual({ error: 'RY.TO on 2026-09-20: sold 12 but held 10; counted as 10.' })
  })

  it('says when the trade is already gone', () => {
    expect(replaceTrade([], trade({ id: 9 }), FX)).toEqual({ error: 'That buy was already gone.' })
  })
})
