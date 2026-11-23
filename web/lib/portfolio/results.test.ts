import { describe, expect, it } from 'vitest'
import { FxRates, PriceBook } from './lookup'
import { resultDetail, resultParts, stockResults } from './results'
import type { Close, Trade } from './types'
import { portfolioView } from './view'

const FX = new FxRates([{ day: '2026-09-01', usdCad: 1.4 }])
const closes = (currency: 'USD' | 'CAD', values: [string, number][]): Close[] =>
  values.map(([day, close]) => ({ day, close, currency }))
const book = (entries: [string, Close[]][]) => new PriceBook(new Map(entries))
const AAPL_220 = book([['stock:AAPL', closes('USD', [['2026-10-16', 220]])]])
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
const sell = (over: Partial<Trade>) => trade({ side: 'sell', ...over })

describe('stockResults', () => {
  it('gives a stock bought and sold its profit, prices and dates', () => {
    const { lines } = stockResults([trade({}), sell({ price: 220, fxRateCad: 1.35, day: '2026-10-01' })], AAPL_220, FX)
    expect(lines).toHaveLength(1)
    const [line] = lines
    expect(line).toMatchObject({
      status: 'sold',
      symbol: 'AAPL',
      account: 'tfsa',
      currency: 'USD',
      openedOn: '2026-09-01',
      closedOn: '2026-10-01',
      heldDays: 30,
      avgBuy: 200,
      avgSell: 220,
      soldQty: 10,
      open: null,
    })
    // cost 10 × 200 × 1.4 = 2,800; proceeds 10 × 220 × 1.35 = 2,970
    expect(line.realized?.cad).toBeCloseTo(170)
    expect(line.realized?.pct).toBeCloseTo(6.071, 2)
  })

  it('gives a stock still held its profit right now at the latest price', () => {
    const { lines } = stockResults([trade({})], AAPL_220, FX)
    expect(lines).toHaveLength(1)
    expect(lines[0]).toMatchObject({ status: 'holding', closedOn: null, heldDays: null, realized: null, avgSell: null, soldQty: 0 })
    expect(lines[0].open).toMatchObject({ qty: 10, avgCost: 200, price: 220 })
    expect(lines[0].open?.cad).toBeCloseTo(280) // 10 × US$20 × 1.4
    expect(lines[0].open?.pct).toBeCloseTo(10)
  })

  it('shows a part-sold stock both ways: what the sales made and what is left now', () => {
    const { lines } = stockResults([trade({}), sell({ qty: 4, price: 210, day: '2026-10-01' })], AAPL_220, FX)
    expect(lines).toHaveLength(1)
    expect(lines[0]).toMatchObject({ status: 'part', soldQty: 4, avgSell: 210, closedOn: null })
    // 4 of 10 cost 1,120 and sold for 4 × 210 × 1.4 = 1,176
    expect(lines[0].realized?.cad).toBeCloseTo(56)
    expect(lines[0].realized?.pct).toBeCloseTo(5)
    // 6 left cost 1,680, worth 6 × 220 × 1.4 = 1,848
    expect(lines[0].open?.qty).toBeCloseTo(6)
    expect(lines[0].open?.cad).toBeCloseTo(168)
    expect(lines[0].open?.pct).toBeCloseTo(10)
  })

  it('starts a new line when a stock sold in full is bought again', () => {
    const { lines } = stockResults(
      [trade({}), sell({ price: 190, day: '2026-09-10' }), trade({ qty: 5, price: 205, day: '2026-10-01' })],
      AAPL_220,
      FX,
    )
    expect(lines.map((l) => [l.status, l.openedOn, l.closedOn])).toEqual([
      ['holding', '2026-10-01', null],
      ['sold', '2026-09-01', '2026-09-10'],
    ])
    expect(lines[0].open).toMatchObject({ qty: 5, avgCost: 205 })
    expect(lines[1].realized?.cad).toBeCloseTo(-140) // 10 × −US$10 × 1.4
  })

  it('averages the buy price over every buy of the holding', () => {
    const { lines } = stockResults([trade({}), trade({ qty: 30, price: 240, day: '2026-09-05' })], AAPL_220, FX)
    expect(lines[0].avgBuy).toBeCloseTo(230) // (10 × 200 + 30 × 240) / 40
  })

  it('lists holdings first, largest first, then sold stocks, most recently sold first', () => {
    const prices = book([
      ['stock:AAPL', closes('USD', [['2026-10-16', 220]])],
      ['stock:MSFT', closes('USD', [['2026-10-16', 400]])],
    ])
    const { lines } = stockResults(
      [
        trade({ symbol: 'AAPL', qty: 1 }),
        trade({ symbol: 'MSFT', qty: 1, price: 390 }),
        trade({ symbol: 'NVDA', price: 100 }),
        sell({ symbol: 'NVDA', price: 110, day: '2026-09-20' }),
        trade({ symbol: 'AMD', price: 100 }),
        sell({ symbol: 'AMD', price: 90, day: '2026-10-05' }),
      ],
      prices,
      FX,
    )
    expect(lines.map((l) => l.symbol)).toEqual(['MSFT', 'AAPL', 'AMD', 'NVDA'])
  })

  it('leaves the open result empty for a stock without a price yet', () => {
    const { lines, openCad } = stockResults([trade({ symbol: 'NEWCO', price: 10 })], AAPL_220, FX)
    expect(lines[0].open).toMatchObject({ qty: 10, avgCost: 10, price: null, cad: null, pct: null })
    expect(openCad).toBe(0)
  })

  it("prices a coin's holding in CAD, as coins trade", () => {
    const coin = { account: 'crypto' as const, symbol: 'ETH', assetType: 'crypto' as const, currency: 'CAD' as const, fxRateCad: null }
    const prices = book([['crypto:ETH', closes('USD', [['2026-10-16', 3000]])]])
    const { lines } = stockResults([trade({ ...coin, qty: 1, price: 4000 })], prices, FX)
    expect(lines[0].currency).toBe('CAD')
    expect(lines[0].open?.price).toBeCloseTo(4200) // US$3,000 × 1.4
    expect(lines[0].open?.cad).toBeCloseTo(200)
  })

  it('counts an over-sell as selling what was held, as the ledger does', () => {
    const { lines } = stockResults([trade({}), sell({ qty: 12, price: 220, day: '2026-10-01' })], AAPL_220, FX)
    expect(lines).toHaveLength(1)
    expect(lines[0]).toMatchObject({ status: 'sold', soldQty: 10 })
    expect(lines[0].realized?.cad).toBeCloseTo(280) // 10 × US$20 × 1.4
  })

  it('totals what the sales made and what the holdings are up right now', () => {
    const { realizedCad, openCad } = stockResults(
      [trade({}), sell({ qty: 4, price: 210, day: '2026-10-01' }), trade({ symbol: 'NVDA', price: 100 }), sell({ symbol: 'NVDA', price: 90, day: '2026-09-20' })],
      AAPL_220,
      FX,
    )
    expect(realizedCad).toBeCloseTo(56 - 140)
    expect(openCad).toBeCloseTo(168)
  })

  it("agrees with the holdings table's profit for each holding", () => {
    const trades = [trade({}), sell({ qty: 4, price: 210, day: '2026-10-01' }), trade({ qty: 3, price: 215, fxRateCad: 1.38, day: '2026-10-02' })]
    const view = portfolioView(
      { trades, prices: AAPL_220, fx: FX, names: new Map(), guideline: { roundTrips: 24, shortHoldShare: 0.5 }, actions: [], sectors: new Map() },
      '2026-10-16',
    )
    const { lines } = stockResults(trades, AAPL_220, FX)
    expect(lines[0].open?.cad).toBeCloseTo(view.holdings[0].gainCad, 6)
    expect(lines[0].open?.pct).toBeCloseTo(view.holdings[0].gainPct, 6)
    // a sell leaves the average cost alone: 6 left at 200, then 3 at 215
    expect(lines[0].open?.avgCost).toBeCloseTo(205)
    expect(lines[0].avgBuy).toBeCloseTo((10 * 200 + 3 * 215) / 13)
  })

  it('is empty without trades', () => {
    expect(stockResults([], AAPL_220, FX)).toEqual({ lines: [], realizedCad: 0, openCad: 0 })
  })
})

describe('resultDetail', () => {
  const only = (trades: Trade[], prices = AAPL_220) => stockResults(trades, prices, FX).lines[0]

  it('says what a holding cost and what it is worth now', () => {
    expect(resultDetail(only([trade({})]))).toEqual(['10 @ US$200.00 avg · now US$220.00', 'TFSA · since Sep 1'])
  })

  it('says what was sold and what is left of a part-sold holding', () => {
    expect(resultDetail(only([trade({}), sell({ qty: 4, price: 210, day: '2026-10-01' })]))).toEqual([
      'Sold 4 @ US$210.00 avg · 6 left @ US$200.00 avg · now US$220.00',
      'TFSA · since Sep 1',
    ])
  })

  it('says the buy and sell prices, the dates and the days held of a stock sold in full', () => {
    expect(resultDetail(only([trade({}), sell({ price: 220, day: '2026-10-01' })]))).toEqual([
      '10 · bought @ US$200.00 avg → sold @ US$220.00 avg',
      'TFSA · Sep 1 – Oct 1 · held 30 days',
    ])
    expect(resultDetail(only([trade({}), sell({ price: 220, day: '2026-09-02' })]))[1]).toBe('TFSA · Sep 1 – Sep 2 · held 1 day')
  })

  it('says when a holding has no price yet', () => {
    expect(resultDetail(only([trade({ symbol: 'NEWCO', price: 10 })]))[0]).toBe('10 @ US$10.00 avg · no price yet')
  })
})

describe('resultParts', () => {
  const only = (trades: Trade[]) => stockResults(trades, AAPL_220, FX).lines[0]

  it('labels what the sales made and what the rest is up now', () => {
    expect(resultParts(only([trade({}), sell({ qty: 4, price: 210, day: '2026-10-01' })]))).toEqual([
      { label: 'sold', amount: '+C$56', pct: '+5.0%', tone: 'gain' },
      { label: 'now', amount: '+C$168', pct: '+10.0%', tone: 'gain' },
    ])
  })

  it('shows a loss in the loss colour and a holding without a price as a dash', () => {
    expect(resultParts(only([trade({}), sell({ price: 190, day: '2026-10-01' })]))).toEqual([
      { label: 'sold', amount: '−C$140', pct: '−5.0%', tone: 'loss' },
    ])
    expect(resultParts(only([trade({ symbol: 'NEWCO', price: 10 })]))).toEqual([{ label: 'now', amount: '—', pct: null, tone: null }])
  })
})
