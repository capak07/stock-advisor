import { describe, expect, it } from 'vitest'
import { dayReturn } from './day-return'
import type { Close } from './types'

const close = (day: string, value: number, currency: 'USD' | 'CAD' = 'CAD'): Close => ({ day, close: value, currency })
const held = { qty: 10, costCad: 1000, openedOn: '2026-09-01' }

describe('dayReturn', () => {
  it('is the move from the close before, times the shares, for a position held before it', () => {
    expect(dayReturn(held, close('2026-11-20', 105), close('2026-11-19', 100), 1.4)).toEqual({ cad: 50, pct: 5, day: '2026-11-20' })
  })

  it("converts a US stock's move to CAD at the latest rate; the percent stays in its own currency", () => {
    const r = dayReturn(held, close('2026-11-20', 190, 'USD'), close('2026-11-19', 200, 'USD'), 1.4)
    expect(r?.cad).toBeCloseTo(-140)
    expect(r?.pct).toBeCloseTo(-5)
  })

  it('is null for a US stock without a rate, and for an asset without a close', () => {
    expect(dayReturn(held, close('2026-11-20', 190, 'USD'), close('2026-11-19', 200, 'USD'), null)).toBeNull()
    expect(dayReturn(held, null, null, 1.4)).toBeNull()
  })

  it('counts a position opened since the close before from what it cost, not from that close', () => {
    const bought = { ...held, openedOn: '2026-11-20' }
    expect(dayReturn(bought, close('2026-11-20', 105), close('2026-11-19', 90), 1.4)).toEqual({ cad: 50, pct: 5, day: '2026-11-20' })
    // opened on a holiday between the two closes: also since it was bought
    expect(dayReturn({ ...held, openedOn: '2026-11-19' }, close('2026-11-20', 105), close('2026-11-18', 90), 1.4)?.cad).toBe(50)
    // a live quote dated today on a position bought today, with only that one price
    expect(dayReturn(bought, close('2026-11-20', 105), null, 1.4)).toEqual({ cad: 50, pct: 5, day: '2026-11-20' })
  })

  it('is null with one close for a position held before it: there is nothing to compare with', () => {
    expect(dayReturn(held, close('2026-11-20', 105), null, 1.4)).toBeNull()
  })

  it("compares a coin's CAD live quote with its USD close in CAD", () => {
    const coin = { qty: 1, costCad: 2000, openedOn: '2026-09-01' }
    const r = dayReturn(coin, close('2026-11-22', 2900), close('2026-11-21', 2000, 'USD'), 1.4) // C$2,800 before
    expect(r?.cad).toBeCloseTo(100)
    expect(r?.pct).toBeCloseTo((100 / 2800) * 100)
    expect(dayReturn(coin, close('2026-11-22', 2900), close('2026-11-21', 2000, 'USD'), null)).toBeNull()
  })

  it('has no percent for a free position bought since the close before', () => {
    expect(dayReturn({ qty: 10, costCad: 0, openedOn: '2026-11-20' }, close('2026-11-20', 5), close('2026-11-19', 4), 1.4)).toEqual({
      cad: 50,
      pct: null,
      day: '2026-11-20',
    })
  })
})
