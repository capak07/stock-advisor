import { describe, expect, it } from 'vitest'
import { FxRates, PriceBook } from './lookup'
import type { Close, Trade } from './types'
import { portfolioView } from './view'

const TODAY = '2026-10-16'
const FX = new FxRates([{ day: '2026-09-01', usdCad: 1.4 }])
const closes = (currency: 'USD' | 'CAD', values: [string, number][]): Close[] =>
  values.map(([day, close]) => ({ day, close, currency }))
const PRICES = new PriceBook(
  new Map([
    ['stock:XIU.TO', closes('CAD', [['2026-09-01', 40], ['2026-10-16', 42]])],
    ['stock:SPY', closes('USD', [['2026-09-01', 500], ['2026-10-16', 520]])],
    ['stock:AAPL', closes('USD', [['2026-09-01', 200], ['2026-10-16', 220]])],
    ['crypto:ETH', closes('USD', [['2026-09-01', 3000], ['2026-10-16', 2800]])],
  ]),
)
const trade = (over: Partial<Trade>): Trade => ({
  side: 'buy',
  account: 'tfsa',
  symbol: 'AAPL',
  assetType: 'stock',
  qty: 10,
  price: 200,
  currency: 'USD',
  fxRateCad: 1.4,
  day: '2026-09-01',
  ...over,
})
const coin = { account: 'crypto' as const, symbol: 'ETH', assetType: 'crypto' as const, currency: 'CAD' as const, fxRateCad: null }
const TRADES = [
  trade({}),
  trade({ ...coin, qty: 2, price: 4200 }),
  trade({ ...coin, side: 'sell', qty: 1, price: 3900, day: '2026-10-03' }),
  trade({ symbol: 'NEWCO', qty: 5, price: 10 }),
]
const view = portfolioView(
  {
    trades: TRADES,
    prices: PRICES,
    fx: FX,
    names: new Map([['AAPL', 'Apple Inc.']]),
    guideline: { roundTrips: 24, shortHoldShare: 0.5 },
  },
  TODAY,
)

describe('portfolioView', () => {
  it('values and orders the holdings, largest first', () => {
    // ETH 1 × 2,800 × 1.4; AAPL 10 × 220 × 1.4; NEWCO has no close, so its cost, 5 × 10 × 1.4.
    expect(view.holdings.map((h) => [h.symbol, h.name, h.market, Math.round(h.valueCad)])).toEqual([
      ['ETH', null, null, 3920],
      ['AAPL', 'Apple Inc.', 'US', 3080],
      ['NEWCO', null, 'US', 70],
    ])
    expect(Math.round(view.totals.valueCad)).toBe(7070)
    expect(view.accounts).toEqual(['Crypto', 'TFSA'])
  })

  it('notes a holding valued at cost, a loss window and the taxable estimate', () => {
    const notes = Object.fromEntries(view.holdings.map((h) => [h.symbol, h.notes]))
    expect(notes.NEWCO).toEqual([{ text: 'No close yet; at cost', warn: true }])
    // ETH: 1 left at 4,200 cost, worth 2,800 × 1.4 = 3,920; the Oct 3 sell lost 300.
    expect(notes.ETH).toEqual([
      { text: 'Loss window to Nov 2', warn: true },
      { text: 'Taxable: est. −C$140', warn: false },
    ])
    expect(notes.AAPL).toEqual([])
  })

  it('lists the warnings that need no model', () => {
    expect(view.warnings.map((w) => w.title)).toEqual(['ETH: superficial-loss window'])
  })

  it('draws every period once there are two trading days', () => {
    expect(view.periods?.all.days).toEqual(['2026-09-01', '2026-10-16'])
    expect(view.firstBuy).toBe('2026-09-01')
    expect(view.fx).toEqual({ day: '2026-09-01', usdCad: 1.4 })
  })

  it('offers each open position for a sell, in its trade currency', () => {
    expect(view.sellable.map((s) => [s.key, s.qty, s.currency])).toEqual([
      ['tfsa:stock:AAPL', 10, 'USD'],
      ['crypto:crypto:ETH', 1, 'CAD'],
      ['tfsa:stock:NEWCO', 5, 'USD'],
    ])
  })

  it('is empty without trades', () => {
    const empty = portfolioView(
      { trades: [], prices: PRICES, fx: FX, names: new Map(), guideline: { roundTrips: 24, shortHoldShare: 0.5 } },
      TODAY,
    )
    expect(empty.holdings).toEqual([])
    expect(empty.periods).toBeNull()
    expect(empty.firstBuy).toBeNull()
    expect(empty.totals.valueCad).toBe(0)
  })
})
