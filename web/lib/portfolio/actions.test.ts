import { describe, expect, it } from 'vitest'
import { actionGroups, cardReason, holdText, type HoldingAction } from './actions'
import type { ExitPlan } from './exit-plan'

const action = (over: Partial<HoldingAction>): HoldingAction => ({
  account: 'tfsa',
  symbol: 'AAPL',
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
  riskLevel: null,
  refPrice: null,
  atrPct: null,
  dollarVolume20: null,
  previousStop: null,
  maxPositionPct: null,
  exitPlan: null,
  ...over,
})

const names = (list: HoldingAction[]) => list.map((a) => `${a.symbol}:${a.action}${a.review ? '+review' : ''}`)

describe('actionGroups', () => {
  it('actionGroups orders Sell, Trim, Review, Add, and folds plain Holds', () => {
    const { cards, hold } = actionGroups([
      action({ symbol: 'MSFT' }),
      action({ symbol: 'RY.TO', action: 'add' }),
      action({ symbol: 'NVDA', action: 'trim' }),
      action({ symbol: 'AAPL', review: true }),
      action({ symbol: 'TD.TO', action: 'add', review: true }),
      action({ symbol: 'SHOP.TO', action: 'sell' }),
      action({ symbol: 'BTC', account: 'crypto', assetType: 'crypto' }),
      action({ symbol: 'CNQ.TO', action: 'sell' }),
      action({ symbol: 'BMO.TO', action: 'add' }),
    ])
    expect(names(cards)).toEqual([
      'CNQ.TO:sell',
      'SHOP.TO:sell',
      'NVDA:trim',
      'AAPL:hold+review',
      'TD.TO:add+review',
      'BMO.TO:add',
      'RY.TO:add',
    ])
    expect(names(hold)).toEqual(['BTC:hold', 'MSFT:hold'])
  })

  it('a Sell with a review badge stays a Sell card', () => {
    const { cards, hold } = actionGroups([
      action({ symbol: 'AAPL', review: true }),
      action({ symbol: 'NVDA', action: 'trim', review: true }),
      action({ symbol: 'SHOP.TO', action: 'sell', review: true }),
    ])
    expect(names(cards)).toEqual(['SHOP.TO:sell+review', 'NVDA:trim+review', 'AAPL:hold+review'])
    expect(hold).toEqual([])
  })
})

describe('cardReason', () => {
  it("a Review card shows its review reasons, capitalised", () => {
    expect(cardReason(action({ review: true, reasons: ['no rule fired', 'earnings on Oct 30'] }))).toBe('Earnings on Oct 30')
    expect(
      cardReason(action({ action: 'add', review: true, reasons: ['would be a Buy today', 'earnings on Oct 30', 'a data source failed'] })),
    ).toBe('Earnings on Oct 30; a data source failed')
    expect(cardReason(action({ review: true, reasons: ['no rule fired'] }))).toBe('No rule fired')
  })

  it('other cards show the headline, capitalised', () => {
    expect(cardReason(action({ action: 'sell', reasons: ['closed at 141.00, under its trailing stop 146.10'] }))).toBe(
      'Closed at 141.00, under its trailing stop 146.10',
    )
    // A Sell with review keeps its headline.
    expect(cardReason(action({ action: 'sell', review: true, reasons: ['stop hit', 'earnings on Oct 30'] }))).toBe('Stop hit')
    expect(cardReason(action({ reasons: [] }))).toBe('')
  })
})

const exitPlan = (over: Partial<ExitPlan> = {}): ExitPlan => ({
  status: 'pass',
  basis: 'volatility',
  horizon: 21,
  recheckBy: '2026-12-19',
  low: 4.2,
  mid: 5.05,
  high: 6.1,
  sellAt: 5.6,
  pTouch: 0.33,
  pStopFirst: 0.22,
  pUp: 0.55,
  breakeven: 1.9,
  pBreakeven: 0.06,
  drift: null,
  costPrice: 4.75,
  ...over,
})

describe('holdText', () => {
  it('names the horizon and exit day, or the capitalised reason without them', () => {
    expect(holdText(action({ horizonDays: 40, exitBy: '2026-12-11' }))).toBe('hold ~40 days · exit by Dec 11')
    expect(holdText(action({ reasons: ['no rule fired'] }))).toBe('No rule fired')
  })

  it("gives the plan's range, sell-at and re-check date when it has a plan and a currency", () => {
    const a = action({ horizonDays: 40, exitBy: '2026-12-11', exitPlan: exitPlan() })
    expect(holdText(a, 'USD')).toBe('hold ~21 days · range US$4.20–6.10 · sell at US$5.60 · re-check Dec 19')
    expect(holdText(action({ exitPlan: exitPlan(), reasons: ['no rule fired'] }), 'CAD')).toBe(
      'hold ~21 days · range C$4.20–6.10 · sell at C$5.60 · re-check Dec 19',
    )
  })

  it('drops the sell-at part without a sell-at price and the re-check part without a date', () => {
    const a = action({ exitPlan: exitPlan({ sellAt: null, recheckBy: null }) })
    expect(holdText(a, 'USD')).toBe('hold ~21 days · range US$4.20–6.10')
  })

  it("keeps today's text without a currency, without a plan, or when the plan has no range", () => {
    const base = { horizonDays: 40, exitBy: '2026-12-11' }
    expect(holdText(action({ ...base, exitPlan: exitPlan() }))).toBe('hold ~40 days · exit by Dec 11')
    expect(holdText(action({ ...base, exitPlan: null }), 'USD')).toBe('hold ~40 days · exit by Dec 11')
    expect(holdText(action({ ...base, exitPlan: exitPlan({ low: null, mid: null, high: null, sellAt: null }) }), 'USD')).toBe(
      'hold ~40 days · exit by Dec 11',
    )
  })

  it('shows the numbers of an unvalidated plan (R17)', () => {
    expect(holdText(action({ exitPlan: exitPlan({ status: 'unvalidated' }) }), 'USD')).toContain('range US$4.20–6.10')
  })
})
