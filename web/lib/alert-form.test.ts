import { describe, expect, it } from 'vitest'
import { alertCurrency, alertTitle, parseAlert } from './alert-form'

const good = { symbol: 'TSLA', assetType: 'stock', direction: 'above', level: '400', note: '' }

describe('parseAlert', () => {
  it('accepts a good alert', () => {
    expect(parseAlert({ ...good, level: '$1,400.50', note: ' trim me ' })).toEqual({
      ok: true,
      value: { symbol: 'TSLA', assetType: 'stock', direction: 'above', level: 1400.5, note: 'trim me' },
    })
  })
  it('stores no note as null', () => {
    expect(parseAlert(good)).toMatchObject({ ok: true, value: { note: null } })
  })
  it('rejects a bad level', () => {
    expect(parseAlert({ ...good, level: 'abc' })).toEqual({ ok: false, errors: { level: expect.any(String) } })
    expect(parseAlert({ ...good, level: '' })).toMatchObject({ ok: false })
    expect(parseAlert({ ...good, level: '-5' })).toMatchObject({ ok: false })
  })
  it('rejects zero', () => {
    expect(parseAlert({ ...good, level: '0' })).toMatchObject({ ok: false, errors: { level: expect.any(String) } })
  })
  it('allows 8 decimals but not 9', () => {
    expect(parseAlert({ ...good, level: '0.00000123' })).toMatchObject({ ok: true })
    expect(parseAlert({ ...good, level: '0.000001234' })).toMatchObject({ ok: false })
  })
  it('rejects a note over 200 characters', () => {
    expect(parseAlert({ ...good, note: 'x'.repeat(201) })).toMatchObject({ ok: false, errors: { note: expect.any(String) } })
    expect(parseAlert({ ...good, note: 'x'.repeat(200) })).toMatchObject({ ok: true })
  })
  it('rejects a bad direction, asset type or symbol', () => {
    expect(parseAlert({ ...good, direction: 'sideways' })).toMatchObject({ ok: false, errors: { direction: expect.any(String) } })
    expect(parseAlert({ ...good, assetType: 'bond' })).toMatchObject({ ok: false })
    expect(parseAlert({ ...good, symbol: 'not a symbol' })).toMatchObject({ ok: false })
  })
})

describe('alertCurrency', () => {
  it('is USD for US stocks and coins, CAD for TSX', () => {
    expect(alertCurrency('TSLA', 'stock')).toBe('USD')
    expect(alertCurrency('ETH', 'crypto')).toBe('USD')
    expect(alertCurrency('RY.TO', 'stock')).toBe('CAD')
  })
})

describe('alertTitle', () => {
  it('names the direction and level', () => {
    expect(alertTitle('above', 400)).toBe('crossed above $400.00 by the last run')
    expect(alertTitle('below', 0.5)).toBe('crossed below $0.50 by the last run')
  })
})
