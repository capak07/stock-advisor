import { describe, expect, it } from 'vitest'
import type { HoldingAction } from './actions'
import { FxRates, PriceBook } from './lookup'
import type { Close, Position } from './types'
import { breakdown, byRisk, sectorWarnings, taxableEstimate, totals, valueHoldings, type Holding } from './valuation'

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

const holding = (symbol: string, valueCad: number, over: Partial<Holding> = {}): Holding => ({
  account: 'tfsa',
  symbol,
  assetType: 'stock',
  qty: 1,
  costCad: valueCad,
  openedOn: '2026-09-01',
  market: 'US',
  priceCad: valueCad,
  priceDay: '2026-10-16',
  valueCad,
  gainCad: 0,
  gainPct: 0,
  ...over,
})
const rated = (symbol: string, riskLevel: HoldingAction['riskLevel'], over: Partial<HoldingAction> = {}): HoldingAction => ({
  account: 'tfsa',
  symbol,
  assetType: 'stock',
  action: 'hold',
  review: false,
  reasons: ['Hold.'],
  warnings: [],
  trailingStop: null,
  q10: null,
  q50: null,
  q90: null,
  horizonDays: null,
  exitBy: null,
  riskLevel,
  ...over,
})
const shares = (slices: { label: string; share: number }[]) => slices.map((s) => [s.label, Math.round(s.share * 10) / 10])

describe('byRisk', () => {
  it("byRisk groups value by the action's risk level, unrated last", () => {
    const holdings = [
      holding('NEWCO', 100),
      holding('NVDA', 300),
      holding('RY.TO', 200, { market: 'TSX' }),
      holding('RY.TO', 100, { account: 'rrsp', market: 'TSX' }),
      holding('BTC', 200, { account: 'crypto', assetType: 'crypto', market: null }),
      holding('MSFT', 100),
    ]
    const actions = [
      rated('NVDA', 'high'),
      rated('RY.TO', 'low'),
      rated('RY.TO', 'medium', { account: 'rrsp' }),
      rated('BTC', 'very_high', { account: 'crypto', assetType: 'crypto' }),
      rated('MSFT', null),
      rated('GONE', 'low'),
    ]
    // 1,000 in all. NEWCO has no action row and MSFT no risk level: 200 not rated.
    expect(shares(byRisk(holdings, actions))).toEqual([
      ['Low', 20],
      ['Medium', 10],
      ['High', 30],
      ['Very high', 20],
      ['Not rated', 20],
    ])
    expect(byRisk([], actions)).toEqual([])
  })
})

describe('sectorWarnings', () => {
  it('a sector over 25% of the portfolio is warned about', () => {
    const sectors = new Map([
      ['AAPL', 'Technology'],
      ['MSFT', 'Technology'],
      ['RY.TO', 'Financials'],
      ['BTC', 'Technology'],
    ])
    const holdings = [
      holding('AAPL', 160),
      holding('MSFT', 100),
      holding('MSFT', 50, { account: 'rrsp' }),
      holding('RY.TO', 250, { market: 'TSX' }),
      holding('NEWCO', 140),
      holding('BTC', 300, { account: 'crypto', assetType: 'crypto', market: null }),
    ]
    // 1,000 in all. Technology 310 (31%) is warned; Financials at exactly 25% isn't; the coin isn't
    // a stock, so its 30% is in no sector, though it counts toward the total.
    expect(sectorWarnings(holdings, sectors)).toEqual([
      { title: 'Technology is 31.0% of the portfolio (guideline 25%)', detail: 'AAPL and MSFT' },
    ])
    expect(sectorWarnings([holding('BTC', 300, { account: 'crypto', assetType: 'crypto', market: null })], sectors)).toEqual([])
    expect(sectorWarnings([], sectors)).toEqual([])
  })
})
