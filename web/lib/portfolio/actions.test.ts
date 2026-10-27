import { describe, expect, it } from 'vitest'
import { actionGroups, type HoldingAction } from './actions'

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
