import { describe, expect, it } from 'vitest'
import { isMarketHours, planBuy, planRecurring, planSell, planStop, planTrim, type Instrument } from './orders'

// Tuesday Oct 27, 2026: 2 PM and 10 PM in Toronto (EDT, UTC−4)
const OPEN = new Date('2026-10-27T18:00:00Z')
const EVENING = new Date('2026-10-28T02:00:00Z')
const SATURDAY = new Date('2026-10-31T16:00:00Z')

const tsx = (over: Partial<Instrument> = {}): Instrument => ({
  assetType: 'stock',
  currency: 'CAD',
  price: 10,
  atrPct: 0.02,
  dollarVolume20: 5e6,
  ...over,
})
const veea = tsx({ currency: 'USD', price: 6, atrPct: 0.166, dollarVolume20: 6e7 })

describe('isMarketHours', () => {
  it('is weekdays 9:30 to 16:00 in Toronto', () => {
    expect(isMarketHours(OPEN)).toBe(true)
    expect(isMarketHours(EVENING)).toBe(false)
    expect(isMarketHours(SATURDAY)).toBe(false)
    expect(isMarketHours(new Date('2026-10-27T13:29:00Z'))).toBe(false) // 9:29
    expect(isMarketHours(new Date('2026-10-27T13:30:00Z'))).toBe(true) // 9:30
  })
})

describe('planBuy', () => {
  it('sets the limit a quarter of the daily range above the price, between 0.2% and 1.5%', () => {
    const limit = (atrPct: number | null) => planBuy(tsx({ atrPct }), { amountCad: 1000, usdCad: 1.4, now: OPEN }).steps[0].price
    expect(limit(0.02)).toBe(10.05)
    expect(limit(0.2)).toBe(10.15) // capped at 1.5%
    expect(limit(0.001)).toBe(10.02) // at least 0.2%
    expect(limit(null)).toBe(10.1) // no range known: 1%
  })

  it('buys whole shares with a limit order, converting a US price to CAD for the count', () => {
    const plan = planBuy(veea, { amountCad: 1000, usdCad: 1.4, now: OPEN })
    expect(plan.steps[0]).toMatchObject({ kind: 'limit', side: 'buy', qty: 117, price: 6.09 }) // 1000 / (6.09 × 1.4) = 117.3
    expect(plan.steps[0].text).toBe('Limit buy 117 sh at US$6.09 · Day order')
  })

  it("puts a fractional remainder of C$25 or more in a market order, Wealthsimple's only order for fractions", () => {
    const plan = planBuy(tsx({ price: 100 }), { amountCad: 1000, usdCad: 1.4, now: OPEN })
    expect(plan.steps.map((s) => [s.kind, s.qty, s.amountCad])).toEqual([
      ['limit', 9, null], // 9 × 100.50 = 904.50
      ['market', null, 96], // the C$95.50 left over
    ])
    expect(plan.steps[1].text).toMatch(/^Market buy C\$96 \(fractional: Wealthsimple fills fractions only as market orders/)
    expect(planBuy(tsx(), { amountCad: 1000, usdCad: 1.4, now: OPEN }).steps).toHaveLength(1) // 99 sh leave C$5.05
  })

  it('buys less than one share as a fractional market order', () => {
    const plan = planBuy(tsx({ currency: 'USD', price: 500 }), { amountCad: 300, usdCad: 1.4, now: OPEN })
    expect(plan.steps.map((s) => [s.kind, s.amountCad])).toEqual([['market', 300]])
  })

  it('says a market buy is fine for a liquid stock, away from the open', () => {
    expect(planBuy(veea, { amountCad: 1000, usdCad: 1.4, now: OPEN }).notes).toContain(
      'A market buy is fine too for a stock this liquid, but not in the first 15 minutes after the open.',
    )
    expect(planBuy(tsx(), { amountCad: 1000, usdCad: 1.4, now: OPEN }).notes.join(' ')).not.toMatch(/liquid/)
  })

  it('in the evening, the limit lasts to the end of the next trading day', () => {
    expect(planBuy(veea, { amountCad: 1000, usdCad: 1.4, now: EVENING }).steps[0].text).toBe(
      'Limit buy 117 sh at US$6.09 · set it to expire at the end of the next trading day',
    )
    expect(planBuy(veea, { amountCad: 1000, usdCad: 1.4, now: SATURDAY }).steps[0].expiry).toBe('next trading day')
  })

  it('follows a stock buy with a 90-day stop-limit on the whole shares, its limit half a range lower', () => {
    const plan = planBuy(veea, { amountCad: 1000, usdCad: 1.4, now: OPEN, stop: 3.51 })
    expect(plan.steps[1]).toMatchObject({ kind: 'stop-limit', side: 'sell', qty: 117, stop: 3.51, limit: 3.33, expiry: '90 days' })
    expect(plan.steps[1].text).toBe('Then a stop-limit sell 117 sh: stop US$3.51, limit US$3.33, expiry 90 days')
    expect(plan.notes).toContain(
      'A stop-limit won’t fill if the price gaps below its limit; a stop-market order sells in a gap at whatever price comes.',
    )
  })

  it('limits a coin in CAD, with the 24-hour expiry, and no stop order', () => {
    const bonk: Instrument = { assetType: 'crypto', currency: 'CAD', price: 0.0000043, atrPct: null, dollarVolume20: null }
    const plan = planBuy(bonk, { amountCad: 500, usdCad: 1.4, now: OPEN, stop: 0.000003 })
    expect(plan.steps).toHaveLength(1)
    expect(plan.steps[0]).toMatchObject({ kind: 'limit', price: 0.000004343 })
    expect(plan.steps[0].text).toBe('Limit buy C$500 of it at C$0.000004343 · it cancels after 24 hours unless you extend it')
  })
})

describe('planSell', () => {
  it('sells everything with a limit just under the price, the fraction at market', () => {
    const plan = planSell(tsx({ currency: 'USD', price: 15.115, atrPct: 0.15 }), { qty: 10.147, now: OPEN })
    expect(plan.steps.map((s) => [s.kind, s.side, s.qty, s.price])).toEqual([
      ['limit', 'sell', 10, 14.89], // 15.115 × 0.985
      ['market', 'sell', 0.147, null],
    ])
    expect(plan.steps[0].text).toBe('Limit sell 10 sh at US$14.89 · Day order')
  })

  it('says a market sell is fine for a liquid stock that needs out', () => {
    expect(planSell(veea, { qty: 100, now: OPEN }).notes).toContain('A market sell is fine for a stock this liquid; this one needs out.')
  })
})

describe('planTrim', () => {
  it('sells about a third of the shares, at least one, a little above the price', () => {
    // a 4% range: a 1% buffer, half of it above the price
    expect(planTrim(tsx({ atrPct: 0.04 }), { qty: 118, now: OPEN }).steps[0]).toMatchObject({ kind: 'limit', side: 'sell', qty: 39, price: 10.05 })
    expect(planTrim(tsx(), { qty: 2, now: OPEN }).steps[0].qty).toBe(1)
  })

  it('trims a holding under one share at market', () => {
    const [step] = planTrim(tsx(), { qty: 0.6, now: OPEN }).steps
    expect([step.kind, step.qty]).toEqual(['market', 0.2])
  })
})

describe('planStop', () => {
  it('keeps a 90-day stop-limit on the whole shares and says when to raise it', () => {
    const plan = planStop(veea, { qty: 118, stop: 3.6, previousStop: 3.51 })
    expect(plan.steps[0].text).toBe('Stop-limit sell 118 sh: stop US$3.60, limit US$3.42, expiry 90 days · raise it from US$3.51')
    expect(planStop(veea, { qty: 118, stop: 3.6, previousStop: 3.6 }).steps[0].text).not.toMatch(/raise/)
  })

  it('notes that a fraction of a share carries no stop order', () => {
    expect(planStop(veea, { qty: 10.147, stop: 3.6, previousStop: null }).notes).toContain(
      'The 0.147 sh fraction can’t carry a stop order; Wealthsimple trades fractions only at market.',
    )
  })

  it('for a coin, a stop order only if Wealthsimple offers one, else a price alert', () => {
    const coin: Instrument = { assetType: 'crypto', currency: 'CAD', price: 0.35, atrPct: 0.067, dollarVolume20: null }
    expect(planStop(coin, { qty: 1383.6, stop: 0.24, previousStop: null }).steps[0].text).toBe(
      'If Wealthsimple offers a stop order for this coin, stop C$0.2400, limit C$0.2320; otherwise set a price alert at C$0.2400',
    )
  })
})

describe('planRecurring', () => {
  it('spreads the BTC share weekly over four weeks', () => {
    expect(planRecurring({ amountCad: 100, symbol: 'BTC' }).steps[0].text).toBe(
      'Or a recurring buy of C$25 of BTC weekly for 4 weeks (Wealthsimple offers daily, weekly, every two weeks or monthly)',
    )
  })
})
