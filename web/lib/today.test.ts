import { describe, expect, it } from 'vitest'
import type { DayRow } from './daytrade'
import type { ActionKind, HoldingAction } from './portfolio/actions'
import type { HoldingRow } from './portfolio/view'
import { PICK_P_FLOOR, bestChanceLine, needsAttention, todayLine } from './today'

let n = 0
/** A minimal holding with an action of `kind` (or none when `kind` is null). */
const holding = (kind: ActionKind | null, review = false, symbol = 'AAA'): HoldingRow => ({
  key: `tfsa:stock:${symbol}:${(n += 1)}`,
  account: 'tfsa',
  symbol,
  name: null,
  market: 'US',
  valueCad: 100,
  gainCad: 0,
  gainPct: 0,
  action:
    kind === null
      ? null
      : ({ account: 'tfsa', symbol, assetType: 'stock', action: kind, review, reasons: ['why'], warnings: [] } as unknown as HoldingAction),
  notes: [],
  priceMove: null,
})

const dayRow = (status: DayRow['status']): DayRow => ({
  day: '2026-11-23',
  status,
  cycles: 3,
  lastUpdate: '2026-11-23T15:00:00Z',
  scanned: 5000,
  usable: 4000,
  candidates: 40,
  error: null,
})

describe('needsAttention', () => {
  it('lists what needs action, in order, and counts the rest (Review Focus 1)', () => {
    const r = needsAttention([holding('add'), holding('hold'), holding('sell'), holding('hold', true), holding('trim')])
    expect(r.items.map((h) => h.action?.action + (h.action?.review ? '+review' : ''))).toEqual(['sell', 'trim', 'hold+review', 'add'])
    expect(r.onHold).toBe(1)
    expect(needsAttention([])).toEqual({ items: [], onHold: 0 })
  })

  it('orders by symbol within a group, and a holding without an action is neither listed nor on Hold', () => {
    const r = needsAttention([holding('sell', false, 'ZZZ'), holding('sell', false, 'AAA'), holding(null), holding('hold')])
    expect(r.items.map((h) => h.symbol)).toEqual(['AAA', 'ZZZ'])
    expect(r.onHold).toBe(1)
  })

  it('keeps a Sell with a review flag in the Sell group', () => {
    const r = needsAttention([holding('add'), holding('sell', true)])
    expect(r.items.map((h) => h.action?.action)).toEqual(['sell', 'add'])
  })
})

describe('todayLine', () => {
  it('says markets closed without a live session (Review Focus 3)', () => {
    expect(todayLine(null, '2026-11-21T15:00:00Z')).toBe('Saturday, Nov 21 · markets closed')
  })

  it('says market open while the day trade session is live, closed once it is done', () => {
    // 10:00 AM in New York on Monday, Nov 23
    expect(todayLine(dayRow('scanning'), '2026-11-23T15:00:00Z')).toBe('Monday, Nov 23 · market open')
    expect(todayLine(dayRow('done'), '2026-11-23T15:00:00Z')).toBe('Monday, Nov 23 · markets closed')
    expect(todayLine(dayRow('closed'), '2026-11-23T15:00:00Z')).toBe('Monday, Nov 23 · markets closed')
  })

  it('needs the session row: a weekday with no row reads closed (a holiday)', () => {
    expect(todayLine(null, '2026-11-26T15:00:00Z')).toBe('Thursday, Nov 26 · markets closed')
  })

  it("uses New York's date late in the evening", () => {
    // 11:30 PM Monday in New York is already Tuesday in UTC
    expect(todayLine(null, '2026-11-24T04:30:00Z')).toBe('Monday, Nov 23 · markets closed')
  })
})

describe('bestChanceLine', () => {
  it('formats the best chance per market, US first', () => {
    expect(bestChanceLine([{ benchmark: 'XIU.TO', pBeat: 0.5512 }, { benchmark: 'SPY', pBeat: 0.527 }])).toBe('US 52.7% vs SPY · TSX 55.1% vs XIU.TO')
    expect(bestChanceLine([])).toBeNull()
  })

  it('shows one market alone', () => {
    expect(bestChanceLine([{ benchmark: 'XIU.TO', pBeat: 0.5 }])).toBe('TSX 50.0% vs XIU.TO')
  })

  it("the picks' bar is 58%", () => {
    expect(PICK_P_FLOOR).toBe(0.58)
  })
})
