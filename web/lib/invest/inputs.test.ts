import { describe, expect, it } from 'vitest'
import { addWeekdays, parseInvestInputs } from './inputs'

describe('parseInvestInputs', () => {
  it('shows only the form when no amount was given', () => {
    const r = parseInvestInputs({})
    expect(r).toMatchObject({ amount: null, amountError: null, cryptoPct: 10, cryptoError: null, cryptoText: '10' })
  })

  it('accepts commas, a dollar sign and C$', () => {
    expect(parseInvestInputs({ amount: '1,000' }).amount).toBe(1000)
    expect(parseInvestInputs({ amount: '$2,500.50' }).amount).toBe(2500.5)
    expect(parseInvestInputs({ amount: ' C$750 ' }).amount).toBe(750)
  })

  it('refuses text, blanks and amounts out of range', () => {
    for (const amount of ['abc', '', '0', '0.5', '10000001', '-5', '1e3']) {
      const r = parseInvestInputs({ amount })
      expect(r.amount, amount).toBeNull()
      expect(r.amountError, amount).not.toBeNull()
    }
    expect(parseInvestInputs({ amount: '10,000,000' }).amount).toBe(10_000_000)
  })

  it('takes a crypto share from 0 to 100, with 10 by default', () => {
    expect(parseInvestInputs({ amount: '100', crypto: '0' }).cryptoPct).toBe(0)
    expect(parseInvestInputs({ amount: '100', crypto: '100' }).cryptoPct).toBe(100)
    expect(parseInvestInputs({ amount: '100', crypto: '25%' }).cryptoPct).toBe(25)
    expect(parseInvestInputs({ amount: '100', crypto: '' }).cryptoPct).toBe(10)
    for (const crypto of ['101', 'x', '-1']) {
      const r = parseInvestInputs({ amount: '100', crypto })
      expect(r.cryptoPct, crypto).toBeNull()
      expect(r.cryptoError, crypto).not.toBeNull()
    }
  })

  it('takes how many stocks, from 1 to 5, with 5 by default', () => {
    expect(parseInvestInputs({ amount: '500' }).stocks).toBe(5)
    expect(parseInvestInputs({ amount: '500', stocks: '1' }).stocks).toBe(1)
    expect(parseInvestInputs({ amount: '500', stocks: '' }).stocks).toBe(5)
    for (const stocks of ['0', '6', '2.5', 'x']) {
      const r = parseInvestInputs({ amount: '500', stocks })
      expect(r.stocks, stocks).toBeNull()
      expect(r.stocksError, stocks).toBe('Choose 1 to 5 stocks.')
    }
  })

  it('takes how long to hold: any, about a month, 3 months or 6 months', () => {
    expect(parseInvestInputs({ amount: '500' })).toMatchObject({ hold: 'any', horizons: null, holdError: null })
    expect(parseInvestInputs({ amount: '500', hold: '21' })).toMatchObject({ hold: '21', horizons: [20, 21] })
    expect(parseInvestInputs({ amount: '500', hold: '63' })).toMatchObject({ hold: '63', horizons: [63] })
    expect(parseInvestInputs({ amount: '500', hold: '126' })).toMatchObject({ hold: '126', horizons: [126] })
    expect(parseInvestInputs({ amount: '500', hold: '' }).hold).toBe('any')
    const bad = parseInvestInputs({ amount: '500', hold: '7' })
    expect([bad.hold, bad.holdError]).toEqual([null, 'Choose how long to hold.'])
  })

  it('reads the first value of a repeated parameter', () => {
    expect(parseInvestInputs({ amount: ['500', '900'] }).amount).toBe(500)
  })
})

describe('addWeekdays', () => {
  it('skips weekends', () => {
    expect(addWeekdays('2026-10-23', 1)).toBe('2026-10-26') // Friday → Monday
    expect(addWeekdays('2026-10-27', 5)).toBe('2026-11-03')
    expect(addWeekdays('2026-10-27', 0)).toBe('2026-10-27')
  })
})
