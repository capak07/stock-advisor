import { describe, expect, it } from 'vitest'
import { FxRates, PriceBook } from './lookup'
import type { Close, Position } from './types'
import { breakdown, taxableEstimate, totals, valueHoldings } from './valuation'

const FX = new FxRates([
  { day: '2026-10-15', usdCad: 1.35 },
  { day: '2026-10-16', usdCad: 1.4 },
])
const usd = (day: string, close: number): Close => ({ day, close, currency: 'USD' })
const cad = (day: string, close: number): Close => ({ day, close, currency: 'CAD' })
const PRICES = new PriceBook(
  new Map([
    ['stock:AAPL', [usd('2026-10-15', 200), usd('2026-10-16', 210)]],
    ['stock:RY.TO', [cad('2026-10-16', 180)]],
    ['crypto:BTC', [usd('2026-10-17', 100000)]],
  ]),
)
const position = (over: Partial<Position>): Position => ({
  account: 'tfsa',
  symbol: 'AAPL',
  assetType: 'stock',
  qty: 10,
  costCad: 2500,
  openedOn: '2026-09-01',
  ...over,
})

describe('valueHoldings', () => {
  const [aapl, ry, btc, newco] = valueHoldings(
    [
      position({}),
      position({ symbol: 'RY.TO', costCad: 1900 }),
      position({ account: 'crypto', symbol: 'BTC', assetType: 'crypto', qty: 0.05, costCad: 6000 }),
      position({ symbol: 'NEWCO', qty: 5, costCad: 500 }),
    ],
    PRICES,
    FX,
  )

  it('converts a US close at the latest Bank of Canada rate', () => {
    expect(aapl).toMatchObject({ market: 'US', priceCad: 294, valueCad: 2940, gainCad: 440, priceDay: '2026-10-16' })
    expect(aapl.gainPct).toBeCloseTo(17.6)
  })

  it('takes a TSX close as is, and puts coins in no market', () => {
    expect(ry).toMatchObject({ market: 'TSX', valueCad: 1800, gainCad: -100 })
    expect(btc).toMatchObject({ market: null, valueCad: 7000, gainCad: 1000 })
  })

  it('values an asset with no close yet at cost', () => {
    expect(newco).toMatchObject({ priceCad: null, priceDay: null, valueCad: 500, gainCad: 0, gainPct: 0 })
  })

  it('adds up, naming what is valued at cost', () => {
    expect(totals([aapl, ry, btc, newco])).toEqual({
      valueCad: 12240,
      costCad: 10900,
      gainCad: 1340,
      unpriced: ['NEWCO'],
    })
  })

  it('splits value by market and by account', () => {
    const shares = (slices: { label: string; share: number }[]) =>
      slices.map((s) => [s.label, Math.round(s.share * 10) / 10])
    // 2,940 + 1,800 + 7,000 = 11,740
    expect(shares(breakdown([aapl, ry, btc], 'market'))).toEqual([
      ['Crypto', 59.6],
      ['US', 25],
      ['TSX', 15.3],
    ])
    expect(shares(breakdown([aapl, ry, btc], 'account'))).toEqual([
      ['Crypto', 59.6],
      ['TFSA', 40.4],
    ])
    expect(breakdown([], 'market')).toEqual([])
  })

  it('estimates tax on gains in taxable accounts only', () => {
    expect(taxableEstimate(btc)).toBe(500)
    expect(taxableEstimate(aapl)).toBeNull()
  })
})
