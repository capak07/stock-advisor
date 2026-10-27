import { describe, expect, it } from 'vitest'
import type { HoldingAction } from './actions'
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
const AAPL_ACTION: HoldingAction = {
  account: 'tfsa',
  symbol: 'AAPL',
  assetType: 'stock',
  action: 'trim',
  review: false,
  reasons: ['Trim it.'],
  warnings: ['Above its max size'],
  trailingStop: 190,
  q10: -0.05,
  q50: 0.01,
  q90: 0.06,
  horizonDays: 21,
  exitBy: '2026-11-16',
  riskLevel: 'medium',
}
const GUIDE = { roundTrips: 24, shortHoldShare: 0.5 }
const INPUTS = {
  trades: TRADES,
  prices: PRICES,
  fx: FX,
  names: new Map([['AAPL', 'Apple Inc.']]),
  guideline: GUIDE,
  actions: [],
  sectors: new Map(),
}
const view = portfolioView(INPUTS, TODAY)
const modelView = portfolioView({ ...INPUTS, actions: [AAPL_ACTION], sectors: new Map([['AAPL', 'Technology']]) }, TODAY)

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

  it("gives each sell option its latest close, so a holdings report can price a position it no longer lists", () => {
    expect(view.sellable.map((s) => [s.symbol, s.lastClose])).toEqual([
      ['AAPL', { day: '2026-10-16', close: 220, currency: 'USD' }],
      ['ETH', { day: '2026-10-16', close: expect.closeTo(3920), currency: 'CAD' }],
      ['NEWCO', null],
    ])
  })

  it("a coin's last close is offered in CAD", () => {
    // Coinbase closes are in USD; coins trade in CAD: 2,800 × 1.4.
    const eth = view.sellable.find((s) => s.symbol === 'ETH')
    expect(eth?.currency).toBe('CAD')
    expect(eth?.lastClose).toEqual({ day: '2026-10-16', close: expect.closeTo(3920), currency: 'CAD' })
    const noRate = portfolioView({ ...INPUTS, fx: new FxRates([]) }, TODAY)
    expect(noRate.sellable.find((s) => s.symbol === 'ETH')?.lastClose).toBeNull()
    expect(noRate.sellable.find((s) => s.symbol === 'AAPL')?.lastClose).toEqual({ day: '2026-10-16', close: 220, currency: 'USD' })
  })

  it("gives each holding its action, with the action's warnings in the notes", () => {
    const rows = Object.fromEntries(modelView.holdings.map((h) => [h.symbol, h]))
    expect(rows.AAPL.action).toEqual(AAPL_ACTION)
    expect(rows.AAPL.notes).toEqual([{ text: 'Above its max size', warn: true }])
    expect(rows.ETH.action).toBeNull()
  })

  it('checks sectors and splits value by risk level', () => {
    // AAPL is 3,080 of 7,070: 43.6%.
    expect(modelView.warnings.map((w) => w.title)).toEqual([
      'ETH: superficial-loss window',
      'Technology is 43.6% of the portfolio (guideline 25%)',
    ])
    expect(modelView.byRisk.map((s) => s.label)).toEqual(['Medium', 'Not rated'])
    expect(view.byRisk.map((s) => s.label)).toEqual(['Not rated'])
  })

  it('is empty without trades', () => {
    const empty = portfolioView(
      { ...INPUTS, trades: [] },
      TODAY,
    )
    expect(empty.holdings).toEqual([])
    expect(empty.periods).toBeNull()
    expect(empty.firstBuy).toBeNull()
    expect(empty.totals.valueCad).toBe(0)
  })
})
