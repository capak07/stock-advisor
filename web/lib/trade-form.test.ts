import { describe, expect, it } from 'vitest'
import { parseBuy, parseSell, type Held } from './trade-form'

const TODAY = '2026-10-16'
const buy = (over: Record<string, string> = {}) => ({
  account: 'tfsa',
  symbol: 'aapl',
  qty: '10',
  price: '182.50',
  day: '2026-10-15',
  fxRate: '1.3712',
  notes: '',
  ...over,
})

describe('parseBuy', () => {
  it('reads a US buy in USD with its rate', () => {
    expect(parseBuy(buy(), TODAY)).toEqual({
      input: {
        account: 'tfsa', symbol: 'AAPL', assetType: 'stock', currency: 'USD',
        qty: 10, price: 182.5, day: '2026-10-15', fxRateCad: 1.3712, notes: null,
      },
    })
  })

  it('leaves the rate to the Bank of Canada when it is blank', () => {
    expect(parseBuy(buy({ fxRate: '' }), TODAY)).toMatchObject({ input: { fxRateCad: null } })
  })

  it('reads TSX stocks and coins in CAD, with no rate', () => {
    expect(parseBuy(buy({ symbol: 'rci.b.to', price: '1,234.5' }), TODAY)).toMatchObject({
      input: { symbol: 'RCI-B.TO', currency: 'CAD', price: 1234.5, fxRateCad: null },
    })
    expect(parseBuy(buy({ account: 'crypto', symbol: 'btc', qty: '0.015' }), TODAY)).toMatchObject({
      input: { assetType: 'crypto', currency: 'CAD', qty: 0.015 },
    })
  })

  it('names every field that is wrong', () => {
    expect(
      parseBuy(
        buy({ account: 'margin', symbol: 'not a symbol', qty: '0', price: 'abc', day: '2026-10-17', fxRate: '137', notes: 'x'.repeat(501) }),
        TODAY,
      ),
    ).toEqual({
      errors: {
        account: 'Pick an account.',
        symbol: 'Enter a symbol like AAPL or RY.TO.',
        qty: 'Enter a quantity above 0.',
        price: 'Enter a price above 0.',
        day: "The date can't be after today.",
        fxRate: 'Enter the USD/CAD rate, for example 1.37.',
        notes: 'Keep notes under 500 characters.',
      },
    })
  })

  it('asks for a coin symbol in the crypto account', () => {
    expect(parseBuy(buy({ account: 'crypto', symbol: 'RY.TO' }), TODAY)).toEqual({
      errors: { symbol: 'Enter a coin symbol, like BTC.' },
    })
  })
})

describe('parseSell', () => {
  const HELD: Held[] = [
    { key: 'tfsa:stock:SHOP.TO', account: 'tfsa', symbol: 'SHOP.TO', assetType: 'stock', qty: 15, openedOn: '2026-05-01' },
    { key: 'tfsa:stock:NVDA', account: 'tfsa', symbol: 'NVDA', assetType: 'stock', qty: 8, openedOn: '2026-01-10' },
  ]
  const sell = (over: Record<string, string> = {}) => ({
    holding: 'tfsa:stock:SHOP.TO', qty: '15', price: '141', day: '2026-10-16', fxRate: '', ...over,
  })

  it('sells from a held position in its currency', () => {
    expect(parseSell(sell(), HELD, TODAY)).toEqual({
      input: {
        account: 'tfsa', symbol: 'SHOP.TO', assetType: 'stock', currency: 'CAD',
        qty: 15, price: 141, day: '2026-10-16', fxRateCad: null,
      },
    })
    expect(parseSell(sell({ holding: 'tfsa:stock:NVDA', qty: '4', fxRate: '1.38' }), HELD, TODAY)).toMatchObject({
      input: { symbol: 'NVDA', currency: 'USD', fxRateCad: 1.38 },
    })
  })

  it('refuses more than is held, a day before the buy, and an unknown holding', () => {
    expect(parseSell(sell({ qty: '16' }), HELD, TODAY)).toEqual({ errors: { qty: 'You hold 15 in your TFSA.' } })
    expect(parseSell(sell({ day: '2026-04-30' }), HELD, TODAY)).toEqual({
      errors: { day: "That's before you bought it, on May 1, 2026." },
    })
    expect(parseSell(sell({ holding: 'tfsa:stock:AAPL' }), HELD, TODAY)).toEqual({ errors: { holding: 'Pick a holding.' } })
  })
})
