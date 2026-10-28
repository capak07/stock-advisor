import { describe, expect, it } from 'vitest'
import { parseSettings } from './settings-form'
import { parseBuy } from './trade-form'
import { parseWatch } from './watch-form'

describe('parseBuy pick_id', () => {
  const form = { account: 'tfsa', symbol: 'AAPL', qty: '2', price: '229.50', day: '2026-10-15', fxRate: '1.37', notes: '' }
  const pickId = (raw: string) => {
    const parsed = parseBuy({ ...form, pick_id: raw }, '2026-10-16')
    return 'input' in parsed ? parsed.input.pickId : 'errors'
  }

  it('links the buy to the pick it came from', () => {
    expect(pickId('42')).toBe(42)
  })

  it('drops a missing or malformed pick id without an error', () => {
    expect(pickId('')).toBeNull()
    expect(pickId('abc')).toBeNull()
    expect(pickId('-3')).toBeNull()
  })
})

describe('parseWatch', () => {
  it('takes a stock or coin symbol in the form the lists store it', () => {
    expect(parseWatch('NVDA', 'stock')).toEqual({ symbol: 'NVDA', assetType: 'stock' })
    expect(parseWatch('RCI-B.TO', 'stock')).toEqual({ symbol: 'RCI-B.TO', assetType: 'stock' })
    expect(parseWatch('ETH', 'crypto')).toEqual({ symbol: 'ETH', assetType: 'crypto' })
  })

  it('refuses anything a pick from the list could not send', () => {
    expect(parseWatch('Royal Bank', 'stock')).toBeNull()
    expect(parseWatch('nvda', 'stock')).toBeNull()
    expect(parseWatch('E', 'crypto')).toBeNull()
    expect(parseWatch('NVDA', 'bond')).toBeNull()
    expect(parseWatch(42, 'stock')).toBeNull()
  })
})

describe('parseSettings', () => {
  const form = { usd_fx_fee_pct: '1.5', crypto_fee_pct: '2', tfsa_round_trips_warn: '24', tfsa_short_hold_share_warn: '50' }

  it('reads the four settings, the share as a fraction', () => {
    expect(parseSettings(form)).toEqual({
      input: { usd_fx_fee_pct: 1.5, crypto_fee_pct: 2, tfsa_round_trips_warn: 24, tfsa_short_hold_share_warn: 0.5 },
    })
    expect(parseSettings({ ...form, usd_fx_fee_pct: '0' })).toMatchObject({ input: { usd_fx_fee_pct: 0 } })
  })

  it("keeps each value within the database's limits", () => {
    expect(
      parseSettings({ usd_fx_fee_pct: '11', crypto_fee_pct: '', tfsa_round_trips_warn: '2.5', tfsa_short_hold_share_warn: '0' }),
    ).toEqual({
      errors: {
        usd_fx_fee_pct: 'Enter a fee from 0 to 10%.',
        crypto_fee_pct: 'Enter a spread from 0 to 10%.',
        tfsa_round_trips_warn: 'Enter a whole number from 1 to 1,000.',
        tfsa_short_hold_share_warn: 'Enter a share from 1 to 100%.',
      },
    })
  })
})
