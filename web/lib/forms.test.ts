import { describe, expect, it } from 'vitest'
import { parseSettings } from './settings-form'
import { parseWatch } from './watch-form'

describe('parseWatch', () => {
  it('reads US stocks, TSX stocks (adding .TO) and coins', () => {
    expect(parseWatch(' nvda ', 'us')).toEqual({ symbol: 'NVDA', assetType: 'stock' })
    expect(parseWatch('shop', 'tsx')).toEqual({ symbol: 'SHOP.TO', assetType: 'stock' })
    expect(parseWatch('rci.b', 'tsx')).toEqual({ symbol: 'RCI-B.TO', assetType: 'stock' })
    expect(parseWatch('dol.to', 'tsx')).toEqual({ symbol: 'DOL.TO', assetType: 'stock' })
    expect(parseWatch('eth', 'crypto')).toEqual({ symbol: 'ETH', assetType: 'crypto' })
  })

  it('explains what is wrong', () => {
    expect(parseWatch('', 'us')).toEqual({ error: 'Enter a symbol.' })
    expect(parseWatch('ry.to', 'us')).toEqual({ error: 'Symbols ending in .TO are TSX stocks; pick TSX stock.' })
    expect(parseWatch('TOOLONG', 'us')).toEqual({ error: 'Enter a US symbol, like NVDA or BRK.B.' })
    expect(parseWatch('E', 'crypto')).toEqual({ error: 'Enter a coin symbol, like ETH.' })
    expect(parseWatch('NVDA', 'bond')).toEqual({ error: 'Pick a type.' })
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
